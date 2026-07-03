from collections.abc import AsyncIterator

import pytest

from app.providers.base import Provider
from app.providers.registry import ProviderRegistry
from app.schemas.inference import InferenceRequest, InferenceResponse, StreamChunk, StreamResult
from app.schemas.providers import ProviderHealth, ProviderStatus


class HealthyProvider(Provider):
    name = "healthy"

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        return InferenceResponse(
            provider=self.name,
            model=request.model,
            output=request.prompt,
        )

    async def stream(self, request: InferenceRequest) -> StreamResult:
        async def chunks() -> AsyncIterator[StreamChunk]:
            yield StreamChunk(
                provider=self.name,
                model=request.model,
                delta=request.prompt,
                done=True,
            )

        return chunks()

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, status=ProviderStatus.healthy)


@pytest.mark.asyncio
async def test_registry_health_checks_registered_providers() -> None:
    registry = ProviderRegistry([HealthyProvider()])

    results = await registry.health_check_all()

    assert results == {"healthy": "healthy"}


def test_registry_rejects_duplicate_provider_names() -> None:
    registry = ProviderRegistry([HealthyProvider()])

    with pytest.raises(ValueError, match="Provider already registered"):
        registry.register(HealthyProvider())


@pytest.mark.asyncio
async def test_provider_contract_supports_generate_and_stream() -> None:
    provider = HealthyProvider()
    request = InferenceRequest(prompt="hello", model="test-model")

    response = await provider.generate(request)
    stream = await provider.stream(request)
    chunks = [chunk async for chunk in stream]

    assert response.output == "hello"
    assert chunks == [StreamChunk(provider="healthy", model="test-model", delta="hello", done=True)]
