import asyncio
import logging
from collections.abc import Iterable

from fastapi import Request

from app.core.config import Settings
from app.metrics.prometheus import CIRCUIT_STATE
from app.providers.adapters.dev import DevEchoProvider
from app.providers.adapters.ollama import OllamaProvider
from app.providers.base import Provider
from app.routing.circuit_breaker import CircuitBreaker, CircuitState

logger = logging.getLogger(__name__)


class ProviderRegistry:
    def __init__(
        self,
        providers: Iterable[Provider] | None = None,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._providers: dict[str, Provider] = {}
        self._circuits: dict[str, CircuitBreaker] = {}
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        for provider in providers or ():
            self.register(provider)

    def register(self, provider: Provider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"Provider already registered: {provider.name}")
        self._providers[provider.name] = provider
        self._circuits[provider.name] = CircuitBreaker(
            provider=provider.name,
            failure_threshold=self._failure_threshold,
            cooldown_seconds=self._cooldown_seconds,
        )
        self._set_circuit_metric(provider.name)

    def get(self, name: str) -> Provider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise KeyError(f"Provider is not registered: {name}") from exc

    def list_names(self) -> list[str]:
        return sorted(self._providers)

    def priority_order(self, configured_priority: str) -> list[str]:
        requested = [name.strip() for name in configured_priority.split(",") if name.strip()]
        ordered = [name for name in requested if name in self._providers]
        ordered.extend(name for name in self.list_names() if name not in ordered)
        return ordered

    def circuit_allows(self, provider_name: str) -> bool:
        allowed = self._circuits[provider_name].allow_request()
        self._set_circuit_metric(provider_name)
        return allowed

    def mark_success(self, provider_name: str) -> None:
        self._circuits[provider_name].record_success()
        self._set_circuit_metric(provider_name)

    def mark_failure(self, provider_name: str) -> None:
        self._circuits[provider_name].record_failure()
        self._set_circuit_metric(provider_name)

    def circuit_snapshots(self) -> dict[str, str]:
        return {name: circuit.snapshot().state.value for name, circuit in self._circuits.items()}

    def set_provider_forced_down(self, provider_name: str, forced_down: bool) -> None:
        provider = self.get(provider_name)
        setter = getattr(provider, "set_forced_down", None)
        if setter is None:
            raise TypeError(f"Provider does not support demo controls: {provider_name}")
        setter(forced_down)

    def demo_provider_states(self) -> dict[str, dict[str, bool | str]]:
        states: dict[str, dict[str, bool | str]] = {}
        for name, provider in self._providers.items():
            state = getattr(provider, "demo_state", None)
            if state is not None:
                states[name] = state()
        return states

    async def health_check_all(self) -> dict[str, str]:
        results: dict[str, str] = {}
        for name, provider in self._providers.items():
            health = await provider.health_check()
            results[name] = health.status.value
        return results

    async def probe_open_circuits(self) -> None:
        for name, circuit in self._circuits.items():
            if circuit.snapshot().state == CircuitState.closed:
                continue
            if not circuit.allow_request():
                self._set_circuit_metric(name)
                continue

            health = await self._providers[name].health_check()
            if health.status.value == "healthy":
                logger.info("provider circuit closed after health recovery provider=%s", name)
                circuit.record_success()
            else:
                logger.warning(
                    "provider circuit remains open provider=%s health_status=%s",
                    name,
                    health.status.value,
                )
                circuit.mark_open()
            self._set_circuit_metric(name)

    def _set_circuit_metric(self, provider_name: str) -> None:
        state = self._circuits[provider_name].snapshot().state
        value = {
            CircuitState.closed: 0,
            CircuitState.open: 1,
            CircuitState.half_open: 2,
        }[state]
        CIRCUIT_STATE.labels(provider_name).set(value)


def build_provider_registry(settings: Settings) -> ProviderRegistry:
    registry = ProviderRegistry(
        failure_threshold=settings.circuit_failure_threshold,
        cooldown_seconds=settings.circuit_cooldown_seconds,
    )

    if settings.enable_dev_provider:
        registry.register(
            DevEchoProvider(
                name="dev_echo",
                latency_ms=settings.dev_provider_latency_ms,
                stream_chunk_delay_ms=settings.dev_provider_stream_chunk_delay_ms,
            )
        )
        registry.register(
            DevEchoProvider(
                name="dev_backup",
                latency_ms=settings.dev_provider_latency_ms,
                stream_chunk_delay_ms=settings.dev_provider_stream_chunk_delay_ms,
            )
        )

    if settings.enable_ollama_provider:
        registry.register(
            OllamaProvider(
                base_url=settings.ollama_base_url,
                timeout_seconds=settings.provider_request_timeout_seconds,
            )
        )

    # TODO: Register Sarvam/OpenAI/Gemini/Groq adapters when those HTTP clients are implemented.
    return registry


def get_provider_registry(request: Request) -> ProviderRegistry:
    return request.app.state.provider_registry


async def provider_health_check_loop(registry: ProviderRegistry, interval_seconds: float) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await registry.probe_open_circuits()
