import asyncio
import itertools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import HTTPException, status

from app.metrics.prometheus import QUEUE_DEPTH
from app.schemas.inference import InferenceRequest, InferenceResponse
from app.services.auth import AuthenticatedAccount

logger = logging.getLogger(__name__)

QueueHandler = Callable[[InferenceRequest, AuthenticatedAccount], Awaitable[InferenceResponse]]


@dataclass(order=True)
class QueuedRequest:
    priority: int
    sequence: int
    request: InferenceRequest = field(compare=False)
    account: AuthenticatedAccount = field(compare=False)
    future: asyncio.Future[InferenceResponse] = field(compare=False)


class PriorityRequestQueue:
    def __init__(self, max_size: int, worker_count: int, handler: QueueHandler) -> None:
        self._queue: asyncio.PriorityQueue[QueuedRequest] = asyncio.PriorityQueue(maxsize=max_size)
        self._worker_count = worker_count
        self._handler = handler
        self._sequence = itertools.count()
        self._workers: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        self._workers = [
            asyncio.create_task(self._worker(), name=f"inferx-request-worker-{index}")
            for index in range(self._worker_count)
        ]

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        QUEUE_DEPTH.set(0)

    async def submit(
        self,
        request: InferenceRequest,
        account: AuthenticatedAccount,
    ) -> InferenceResponse:
        if self._queue.full():
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Inference request queue is full",
            )

        loop = asyncio.get_running_loop()
        future: asyncio.Future[InferenceResponse] = loop.create_future()
        queued = QueuedRequest(
            priority=priority_for_tier(account.tier),
            sequence=next(self._sequence),
            request=request,
            account=account,
            future=future,
        )
        await self._queue.put(queued)
        QUEUE_DEPTH.set(self._queue.qsize())
        return await future

    async def _worker(self) -> None:
        while True:
            queued = await self._queue.get()
            QUEUE_DEPTH.set(self._queue.qsize())
            try:
                response = await self._handler(queued.request, queued.account)
            except Exception as exc:
                if not queued.future.done():
                    queued.future.set_exception(exc)
            else:
                if not queued.future.done():
                    queued.future.set_result(response)
            finally:
                self._queue.task_done()
                QUEUE_DEPTH.set(self._queue.qsize())


def priority_for_tier(tier: str) -> int:
    return 0 if tier == "premium" else 10
