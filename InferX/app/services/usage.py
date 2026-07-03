import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import UsageRecord
from app.schemas.inference import InferenceRequest, InferenceResponse
from app.services.auth import AuthenticatedAccount

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    return max(1, len(text.split())) if text else 0


def estimate_cost_usd(provider: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    # Phase 2 records measured gateway usage. Local/dev and self-hosted providers
    # have no external billable API cost here, so their persisted cost is zero.
    if provider in {"dev_echo", "ollama"}:
        return Decimal("0.000000")

    # TODO: Replace these zeros with explicit provider pricing config before enabling
    # real hosted provider adapters.
    _ = prompt_tokens + completion_tokens
    return Decimal("0.000000")


@dataclass(frozen=True)
class UsageEvent:
    account: AuthenticatedAccount
    request: InferenceRequest
    response: InferenceResponse
    cache_tier: str
    latency_ms: int
    status: str
    error_message: str | None = None


class UsageWriter:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queue_size: int,
        worker_count: int,
    ) -> None:
        self.session_factory = session_factory
        self.queue: asyncio.Queue[UsageEvent] = asyncio.Queue(maxsize=queue_size)
        self.worker_count = worker_count
        self.workers: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        self.workers = [
            asyncio.create_task(self._worker(), name=f"inferx-usage-writer-{index}")
            for index in range(self.worker_count)
        ]

    async def stop(self) -> None:
        await self.queue.join()
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()

    def enqueue(self, event: UsageEvent) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.error(
                "usage writer queue full; dropping usage event provider=%s cache_tier=%s",
                event.response.provider,
                event.cache_tier,
            )

    async def _worker(self) -> None:
        while True:
            event = await self.queue.get()
            try:
                await record_usage_event(self.session_factory, event)
            except Exception:
                logger.exception("usage writer failed to persist event")
            finally:
                self.queue.task_done()


async def record_usage_event(
    session_factory: async_sessionmaker[AsyncSession],
    event: UsageEvent,
) -> None:
    await record_usage(
        session_factory=session_factory,
        account=event.account,
        request=event.request,
        response=event.response,
        cache_tier=event.cache_tier,
        latency_ms=event.latency_ms,
        status=event.status,
        error_message=event.error_message,
    )


async def record_usage(
    session_factory: async_sessionmaker[AsyncSession],
    account: AuthenticatedAccount,
    request: InferenceRequest,
    response: InferenceResponse,
    cache_tier: str,
    latency_ms: int,
    status: str,
    error_message: str | None = None,
) -> None:
    prompt_tokens = estimate_tokens(request.prompt)
    completion_tokens = estimate_tokens(response.output)
    total_tokens = prompt_tokens + completion_tokens
    cost_usd = estimate_cost_usd(response.provider, prompt_tokens, completion_tokens)

    async with session_factory() as session:
        session.add(
            UsageRecord(
                user_id=account.user_id,
                api_key_id=account.api_key_id,
                provider=response.provider,
                model=response.model,
                cache_tier=cache_tier,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                status=status,
                error_message=error_message,
            )
        )
        await session.commit()
