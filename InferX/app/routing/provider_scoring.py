import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import UsageRecord
from app.metrics.prometheus import (
    PROVIDER_RECENT_COST_PER_MILLION_TOKENS_USD,
    PROVIDER_RECENT_ERROR_RATE,
    PROVIDER_RECENT_LATENCY_MS,
    PROVIDER_SCORE,
)
from app.providers.registry import ProviderRegistry
from app.services.pricing import (
    DEFAULT_PRICE_CATALOG,
    TOKEN_MILLION,
    PriceEntry,
    calculate_token_cost,
    find_price_entry,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderAttemptObservation:
    provider: str
    model: str
    status: str
    latency_ms: float
    observed_at_monotonic: float


@dataclass(frozen=True)
class ProviderScoreSnapshot:
    provider: str
    score: float
    previous_score: float | None
    latency_ms: float | None
    error_rate: float
    cost_per_million_tokens_usd: Decimal | None
    request_count: int
    error_count: int
    healthy: bool
    circuit_state: str
    updated_at: datetime


@dataclass(frozen=True)
class ProviderCostSample:
    cost_usd: Decimal
    total_tokens: int


class ProviderScorer:
    def __init__(
        self,
        registry: ProviderRegistry,
        session_factory: async_sessionmaker[AsyncSession] | None,
        interval_seconds: float = 60.0,
        window_seconds: float = 300.0,
        catalog: tuple[PriceEntry, ...] = DEFAULT_PRICE_CATALOG,
    ) -> None:
        self.registry = registry
        self.session_factory = session_factory
        self.interval_seconds = interval_seconds
        self.window_seconds = window_seconds
        self.catalog = catalog
        self._attempts: deque[ProviderAttemptObservation] = deque()
        self._scores: dict[str, ProviderScoreSnapshot] = {}
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task is not None:
            return
        await self.score_once()
        self._task = asyncio.create_task(self._run(), name="inferx-provider-scorer")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    def record_attempt(
        self,
        provider: str,
        model: str,
        status: str,
        latency_ms: float,
    ) -> None:
        self._attempts.append(
            ProviderAttemptObservation(
                provider=provider,
                model=model,
                status=status,
                latency_ms=latency_ms,
                observed_at_monotonic=time.monotonic(),
            )
        )
        self._trim_attempts()

    def ranked_provider_names(self, priority_order: list[str]) -> list[str]:
        priority_index = {provider: index for index, provider in enumerate(priority_order)}
        return sorted(
            priority_order,
            key=lambda provider: (
                -self.score_for(provider),
                priority_index[provider],
            ),
        )

    def score_for(self, provider: str) -> float:
        snapshot = self._scores.get(provider)
        if snapshot is None:
            return 50.0
        return snapshot.score

    def snapshots(self) -> list[ProviderScoreSnapshot]:
        return sorted(
            self._scores.values(),
            key=lambda snapshot: (-snapshot.score, snapshot.provider),
        )

    async def score_once(self) -> list[ProviderScoreSnapshot]:
        async with self._lock:
            self._trim_attempts()
            provider_names = self.registry.list_names()
            if not provider_names:
                self._scores = {}
                return []

            observations = list(self._attempts)
            costs = await self._recent_provider_costs()
            health = await self.registry.health_check_all()
            circuits = self.registry.circuit_snapshots()
            updated_at = datetime.now(UTC)

            snapshots: dict[str, ProviderScoreSnapshot] = {}
            for provider in provider_names:
                provider_observations = [
                    observation
                    for observation in observations
                    if observation.provider == provider
                ]
                request_count = len(provider_observations)
                error_count = sum(
                    1 for observation in provider_observations if observation.status == "error"
                )
                error_rate = error_count / request_count if request_count else 0.0
                latency_ms = (
                    sum(observation.latency_ms for observation in provider_observations)
                    / request_count
                    if request_count
                    else None
                )
                circuit_state = circuits.get(provider, "unknown")
                healthy = health.get(provider) == "healthy" and circuit_state != "open"
                cost_per_million = self._cost_per_million(costs.get(provider))
                previous = self._scores.get(provider)
                score = self._calculate_score(
                    healthy=healthy,
                    latency_ms=latency_ms,
                    error_rate=error_rate,
                    cost_per_million=cost_per_million,
                    max_cost_per_million=self._max_cost_per_million(costs),
                )
                snapshot = ProviderScoreSnapshot(
                    provider=provider,
                    score=score,
                    previous_score=previous.score if previous else None,
                    latency_ms=latency_ms,
                    error_rate=error_rate,
                    cost_per_million_tokens_usd=cost_per_million,
                    request_count=request_count,
                    error_count=error_count,
                    healthy=healthy,
                    circuit_state=circuit_state,
                    updated_at=updated_at,
                )
                snapshots[provider] = snapshot
                self._publish_metrics(snapshot)
                self._log_score_change(previous, snapshot)

            self._scores = snapshots
            return self.snapshots()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            try:
                await self.score_once()
            except Exception:
                logger.exception("provider scoring loop failed")

    def _trim_attempts(self) -> None:
        cutoff = time.monotonic() - self.window_seconds
        while self._attempts and self._attempts[0].observed_at_monotonic < cutoff:
            self._attempts.popleft()

    async def _recent_provider_costs(self) -> dict[str, ProviderCostSample]:
        if self.session_factory is None:
            return {}

        cutoff = datetime.now(UTC) - timedelta(seconds=self.window_seconds)
        statement = (
            select(
                UsageRecord.provider,
                UsageRecord.model,
                func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
                func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
                func.coalesce(func.sum(UsageRecord.total_tokens), 0),
            )
            .where(
                UsageRecord.created_at >= cutoff,
                UsageRecord.status == "success",
                UsageRecord.cache_tier == "miss",
            )
            .group_by(UsageRecord.provider, UsageRecord.model)
        )
        provider_costs: dict[str, ProviderCostSample] = {}
        async with self.session_factory() as session:
            result = await session.execute(statement)
            for provider, model, prompt_tokens, completion_tokens, total_tokens in result.all():
                price = find_price_entry(provider, model, self.catalog)
                if price is None:
                    continue
                total_tokens = int(total_tokens)
                if total_tokens <= 0:
                    continue
                cost = calculate_token_cost(
                    price,
                    prompt_tokens=int(prompt_tokens),
                    completion_tokens=int(completion_tokens),
                )
                existing = provider_costs.get(provider)
                provider_costs[provider] = ProviderCostSample(
                    cost_usd=cost + (existing.cost_usd if existing else Decimal("0")),
                    total_tokens=total_tokens + (existing.total_tokens if existing else 0),
                )
        return provider_costs

    def _calculate_score(
        self,
        healthy: bool,
        latency_ms: float | None,
        error_rate: float,
        cost_per_million: Decimal | None,
        max_cost_per_million: Decimal | None,
    ) -> float:
        if not healthy:
            return 0.0

        latency_penalty = 0.0
        if latency_ms is not None:
            latency_penalty = min(45.0, (latency_ms / 1000.0) * 45.0)

        error_penalty = min(60.0, error_rate * 60.0)
        cost_penalty = 0.0
        if (
            cost_per_million is not None
            and max_cost_per_million is not None
            and max_cost_per_million > 0
        ):
            cost_penalty = min(20.0, float(cost_per_million / max_cost_per_million) * 20.0)

        return round(max(0.0, 100.0 - latency_penalty - error_penalty - cost_penalty), 2)

    def _cost_per_million(self, sample: ProviderCostSample | None) -> Decimal | None:
        if sample is None or sample.total_tokens <= 0:
            return None
        return ((sample.cost_usd / Decimal(sample.total_tokens)) * TOKEN_MILLION).quantize(
            Decimal("0.000001")
        )

    def _max_cost_per_million(
        self,
        costs: dict[str, ProviderCostSample],
    ) -> Decimal | None:
        provider_costs = [
            cost
            for sample in costs.values()
            if (cost := self._cost_per_million(sample)) is not None
        ]
        if not provider_costs:
            return None
        return max(provider_costs)

    def _publish_metrics(self, snapshot: ProviderScoreSnapshot) -> None:
        PROVIDER_SCORE.labels(snapshot.provider).set(snapshot.score)
        PROVIDER_RECENT_LATENCY_MS.labels(snapshot.provider).set(snapshot.latency_ms or 0.0)
        PROVIDER_RECENT_ERROR_RATE.labels(snapshot.provider).set(snapshot.error_rate)
        cost = snapshot.cost_per_million_tokens_usd
        PROVIDER_RECENT_COST_PER_MILLION_TOKENS_USD.labels(snapshot.provider).set(
            float(cost) if cost is not None else 0.0
        )

    def _log_score_change(
        self,
        previous: ProviderScoreSnapshot | None,
        current: ProviderScoreSnapshot,
    ) -> None:
        if previous is not None:
            score_changed = abs(previous.score - current.score) >= 0.5
            state_changed = (
                previous.healthy != current.healthy
                or previous.circuit_state != current.circuit_state
            )
            if not score_changed and not state_changed:
                return

        previous_score = f"{previous.score:.2f}" if previous else "none"
        latency_ms = f"{current.latency_ms:.1f}" if current.latency_ms is not None else "none"
        cost = (
            f"{current.cost_per_million_tokens_usd:f}"
            if current.cost_per_million_tokens_usd is not None
            else "unknown"
        )
        logger.info(
            "provider score changed provider=%s score=%.2f previous_score=%s "
            "latency_ms=%s error_rate=%.4f cost_per_million_usd=%s healthy=%s "
            "circuit=%s requests=%s errors=%s",
            current.provider,
            current.score,
            previous_score,
            latency_ms,
            current.error_rate,
            cost,
            current.healthy,
            current.circuit_state,
            current.request_count,
            current.error_count,
        )
