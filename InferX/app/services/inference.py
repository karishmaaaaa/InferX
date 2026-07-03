import logging
import time

from app.cache.redis_cache import SemanticCache
from app.metrics.prometheus import (
    CACHE_EVENTS_TOTAL,
    ERRORS_TOTAL,
    INFERENCE_LATENCY_SECONDS,
    INFERENCE_REQUESTS_TOTAL,
)
from app.routing.router import InferenceRouter
from app.schemas.inference import InferenceRequest, InferenceResponse
from app.services.auth import AuthenticatedAccount
from app.services.usage import UsageEvent, UsageWriter

logger = logging.getLogger(__name__)


class InferenceService:
    def __init__(
        self,
        cache: SemanticCache,
        router: InferenceRouter,
        usage_writer: UsageWriter,
    ) -> None:
        self.cache = cache
        self.router = router
        self.usage_writer = usage_writer

    async def generate(
        self,
        request: InferenceRequest,
        account: AuthenticatedAccount,
    ) -> InferenceResponse:
        start = time.perf_counter()
        cache_tier = "miss"
        status = "success"

        try:
            cache_hit = await self.cache.get(request)
            if cache_hit is not None:
                cache_tier = cache_hit.tier
                CACHE_EVENTS_TOTAL.labels(cache_tier, "hit").inc()
                logger.info(
                    "cache hit tier=%s similarity=%s model=%s key_prefix=%s",
                    cache_tier,
                    cache_hit.similarity,
                    request.model,
                    account.key_prefix,
                )
                response = cache_hit.response
            else:
                CACHE_EVENTS_TOTAL.labels("miss", "miss").inc()
                routed = await self.router.generate(request)
                response = routed.response
                logger.info(
                    "provider route success provider=%s attempted_chain=%s key_prefix=%s",
                    response.provider,
                    routed.attempted_chain,
                    account.key_prefix,
                )
                await self.cache.set(request, response)

            latency = time.perf_counter() - start
            INFERENCE_REQUESTS_TOTAL.labels(account.tier, status).inc()
            INFERENCE_LATENCY_SECONDS.labels(account.tier, cache_tier).observe(latency)
            self.usage_writer.enqueue(
                UsageEvent(
                    account=account,
                    request=request,
                    response=response,
                    cache_tier=cache_tier,
                    latency_ms=int(latency * 1000),
                    status=status,
                )
            )
            return response
        except Exception as exc:
            status = "error"
            latency = time.perf_counter() - start
            INFERENCE_REQUESTS_TOTAL.labels(account.tier, status).inc()
            INFERENCE_LATENCY_SECONDS.labels(account.tier, cache_tier).observe(latency)
            ERRORS_TOTAL.labels(exc.__class__.__name__).inc()
            logger.exception("inference request failed key_prefix=%s", account.key_prefix)
            raise
