from collections.abc import AsyncIterator

import pytest

from app.core.config import Settings
from app.providers.adapters.dev import DevEchoProvider
from app.providers.base import Provider
from app.providers.registry import ProviderRegistry
from app.routing.router import InferenceRouter
from app.schemas.inference import InferenceRequest, InferenceResponse, StreamChunk, StreamResult
from app.schemas.providers import ProviderHealth, ProviderStatus


class FailingProvider(Provider):
    name = "primary"

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        _ = request
        raise TimeoutError("provider timed out")

    async def stream(self, request: InferenceRequest) -> StreamResult:
        _ = request

        async def chunks() -> AsyncIterator[StreamChunk]:
            raise TimeoutError("provider timed out")
            yield

        return chunks()

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, status=ProviderStatus.unhealthy)


class BackupProvider(Provider):
    name = "backup"

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        return InferenceResponse(provider=self.name, model=request.model, output="ok")

    async def stream(self, request: InferenceRequest) -> StreamResult:
        async def chunks() -> AsyncIterator[StreamChunk]:
            yield StreamChunk(provider=self.name, model=request.model, delta="ok", done=True)

        return chunks()

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, status=ProviderStatus.healthy)


class StaticScorer:
    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def ranked_provider_names(self, priority_order: list[str]) -> list[str]:
        return sorted(priority_order, key=lambda provider: -self.scores[provider])

    def score_for(self, provider: str) -> float:
        return self.scores[provider]

    def record_attempt(
        self,
        provider: str,
        model: str,
        status: str,
        latency_ms: float,
    ) -> None:
        _ = provider, model, status, latency_ms


@pytest.mark.asyncio
async def test_router_fails_over_to_next_provider_and_opens_circuit() -> None:
    registry = ProviderRegistry(
        [FailingProvider(), BackupProvider()],
        failure_threshold=1,
        cooldown_seconds=60,
    )
    router = InferenceRouter(
        registry,
        Settings(
            provider_priority="primary,backup",
            provider_request_timeout_seconds=0.1,
        ),
    )

    routed = await router.generate(InferenceRequest(prompt="hello", model="test-model"))

    assert routed.response.provider == "backup"
    assert routed.attempted_chain == ["primary", "backup"]
    assert registry.circuit_snapshots()["primary"] == "open"


@pytest.mark.asyncio
async def test_router_prefers_highest_scoring_provider() -> None:
    registry = ProviderRegistry(
        [DevEchoProvider(name="dev_echo"), DevEchoProvider(name="dev_backup")],
        failure_threshold=1,
        cooldown_seconds=60,
    )
    router = InferenceRouter(
        registry,
        Settings(provider_priority="dev_echo,dev_backup"),
        StaticScorer({"dev_echo": 25.0, "dev_backup": 95.0}),
    )

    routed = await router.generate(InferenceRequest(prompt="hello", model="demo"))

    assert routed.response.provider == "dev_backup"
    assert routed.attempted_chain == ["dev_backup"]


@pytest.mark.asyncio
async def test_router_stream_fails_over_when_primary_is_forced_down() -> None:
    primary = DevEchoProvider(name="dev_echo", stream_chunk_delay_ms=0)
    primary.set_forced_down(True)
    backup = DevEchoProvider(name="dev_backup", stream_chunk_delay_ms=0)
    registry = ProviderRegistry([primary, backup], failure_threshold=1, cooldown_seconds=60)
    router = InferenceRouter(
        registry,
        Settings(
            provider_priority="dev_echo,dev_backup",
            provider_request_timeout_seconds=0.01,
        ),
    )

    routed = await router.stream(InferenceRequest(prompt="hello", model="demo"))
    chunks = [chunk async for chunk in routed.stream]

    assert routed.provider == "dev_backup"
    assert routed.attempted_chain == ["dev_echo", "dev_backup"]
    assert chunks[0].provider == "dev_backup"
    assert registry.circuit_snapshots()["dev_echo"] == "open"
