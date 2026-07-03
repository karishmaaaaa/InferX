import asyncio
import logging
import time
from dataclasses import dataclass

from app.core.config import Settings
from app.metrics.prometheus import (
    FAILOVERS_TOTAL,
    PROVIDER_REQUEST_LATENCY_SECONDS,
    PROVIDER_REQUESTS_TOTAL,
)
from app.providers.registry import ProviderRegistry
from app.routing.provider_scoring import ProviderScorer
from app.schemas.inference import InferenceRequest, InferenceResponse, StreamResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutedResponse:
    response: InferenceResponse
    attempted_chain: list[str]


@dataclass(frozen=True)
class RoutedStream:
    provider: str
    stream: StreamResult
    attempted_chain: list[str]


class NoHealthyProviderError(RuntimeError):
    pass


class InferenceRouter:
    def __init__(
        self,
        registry: ProviderRegistry,
        settings: Settings,
        scorer: ProviderScorer | None = None,
    ) -> None:
        self.registry = registry
        self.settings = settings
        self.scorer = scorer

    async def generate(self, request: InferenceRequest) -> RoutedResponse:
        provider_order = self._provider_order(request)
        attempted_chain: list[str] = []
        last_error: Exception | None = None

        for index, provider_name in enumerate(provider_order):
            if not self.registry.circuit_allows(provider_name):
                logger.info(
                    "provider skipped circuit_open provider=%s attempted_chain=%s",
                    provider_name,
                    attempted_chain,
                )
                continue

            provider = self.registry.get(provider_name)
            attempted_chain.append(provider_name)
            attempt_start = time.perf_counter()
            try:
                response = await asyncio.wait_for(
                    provider.generate(request),
                    timeout=self.settings.provider_request_timeout_seconds,
                )
            except Exception as exc:
                latency = time.perf_counter() - attempt_start
                last_error = exc
                self.registry.mark_failure(provider_name)
                PROVIDER_REQUESTS_TOTAL.labels(provider_name, "error").inc()
                PROVIDER_REQUEST_LATENCY_SECONDS.labels(provider_name, "error").observe(latency)
                self._record_attempt(provider_name, request.model, "error", latency)
                next_provider = self._next_available_provider(provider_order[index + 1 :])
                reason = exc.__class__.__name__
                FAILOVERS_TOTAL.labels(provider_name, next_provider or "none", reason).inc()
                logger.warning(
                    "provider failover provider=%s next_provider=%s reason=%s attempted_chain=%s",
                    provider_name,
                    next_provider,
                    reason,
                    attempted_chain,
                )
                continue

            latency = time.perf_counter() - attempt_start
            self.registry.mark_success(provider_name)
            PROVIDER_REQUESTS_TOTAL.labels(provider_name, "success").inc()
            PROVIDER_REQUEST_LATENCY_SECONDS.labels(provider_name, "success").observe(latency)
            self._record_attempt(provider_name, request.model, "success", latency)
            return RoutedResponse(response=response, attempted_chain=attempted_chain)

        chain = ",".join(attempted_chain) if attempted_chain else "none"
        raise NoHealthyProviderError(
            f"No healthy provider completed the request; attempted_chain={chain}; "
            f"last_error={last_error}"
        )

    async def stream(self, request: InferenceRequest) -> RoutedStream:
        provider_order = self._provider_order(request)
        attempted_chain: list[str] = []
        last_error: Exception | None = None

        for index, provider_name in enumerate(provider_order):
            if not self.registry.circuit_allows(provider_name):
                logger.info(
                    "stream provider skipped circuit_open provider=%s attempted_chain=%s",
                    provider_name,
                    attempted_chain,
                )
                continue

            provider = self.registry.get(provider_name)
            attempted_chain.append(provider_name)
            attempt_start = time.perf_counter()
            try:
                stream = await asyncio.wait_for(
                    provider.stream(request),
                    timeout=self.settings.provider_request_timeout_seconds,
                )
            except Exception as exc:
                latency = time.perf_counter() - attempt_start
                last_error = exc
                self.registry.mark_failure(provider_name)
                PROVIDER_REQUESTS_TOTAL.labels(provider_name, "error").inc()
                PROVIDER_REQUEST_LATENCY_SECONDS.labels(provider_name, "error").observe(latency)
                self._record_attempt(provider_name, request.model, "error", latency)
                next_provider = self._next_available_provider(provider_order[index + 1 :])
                reason = exc.__class__.__name__
                FAILOVERS_TOTAL.labels(provider_name, next_provider or "none", reason).inc()
                logger.warning(
                    "stream provider failover provider=%s next_provider=%s reason=%s "
                    "attempted_chain=%s",
                    provider_name,
                    next_provider,
                    reason,
                    attempted_chain,
                )
                continue

            latency = time.perf_counter() - attempt_start
            self.registry.mark_success(provider_name)
            PROVIDER_REQUESTS_TOTAL.labels(provider_name, "success").inc()
            PROVIDER_REQUEST_LATENCY_SECONDS.labels(provider_name, "success").observe(latency)
            self._record_attempt(provider_name, request.model, "success", latency)
            return RoutedStream(
                provider=provider_name,
                stream=stream,
                attempted_chain=attempted_chain,
            )

        chain = ",".join(attempted_chain) if attempted_chain else "none"
        raise NoHealthyProviderError(
            f"No healthy provider opened a stream; attempted_chain={chain}; last_error={last_error}"
        )

    def _provider_order(self, request: InferenceRequest) -> list[str]:
        priority = self.registry.priority_order(self.settings.provider_priority)
        scored_order = self.scorer.ranked_provider_names(priority) if self.scorer else priority
        if request.provider:
            requested = [request.provider] if request.provider in scored_order else []
            return requested + [name for name in scored_order if name not in requested]

        if self.scorer:
            score_labels = {
                provider: self.scorer.score_for(provider)
                for provider in scored_order
            }
            logger.info(
                "provider scored route order provider_order=%s scores=%s",
                scored_order,
                score_labels,
            )
        return scored_order

    def _next_available_provider(self, candidates: list[str]) -> str | None:
        for provider_name in candidates:
            if self.registry.circuit_allows(provider_name):
                return provider_name
        return None

    def _record_attempt(
        self,
        provider: str,
        model: str,
        status: str,
        latency_seconds: float,
    ) -> None:
        if self.scorer is None:
            return
        self.scorer.record_attempt(
            provider=provider,
            model=model,
            status=status,
            latency_ms=latency_seconds * 1000,
        )
