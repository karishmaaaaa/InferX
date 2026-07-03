from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dashboard import router as dashboard_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.demo import router as demo_router
from app.api.v1.health import router as health_router
from app.api.v1.inference import router as inference_router
from app.cache.redis_cache import SemanticCache, create_redis_client
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.telemetry import configure_telemetry
from app.db.session import create_session_factory
from app.metrics.prometheus import instrument_http_metrics, mount_prometheus_metrics
from app.providers.registry import build_provider_registry, provider_health_check_loop
from app.routing.provider_scoring import ProviderScorer
from app.routing.queue import PriorityRequestQueue
from app.routing.router import InferenceRouter
from app.services.auth import bootstrap_local_dev_accounts
from app.services.inference import InferenceService
from app.services.usage import UsageWriter


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.redis = create_redis_client(str(settings.redis_url))
    app.state.db_session_factory = create_session_factory(settings)
    app.state.provider_registry = build_provider_registry(settings)
    await bootstrap_local_dev_accounts(settings, app.state.db_session_factory)
    app.state.provider_scorer = ProviderScorer(
        registry=app.state.provider_registry,
        session_factory=app.state.db_session_factory,
        interval_seconds=settings.provider_score_interval_seconds,
        window_seconds=settings.provider_score_window_seconds,
    )
    if settings.provider_score_interval_seconds > 0:
        await app.state.provider_scorer.start()

    router = InferenceRouter(app.state.provider_registry, settings, app.state.provider_scorer)
    app.state.inference_router = router
    cache = SemanticCache(app.state.redis, settings)
    app.state.usage_writer = UsageWriter(
        session_factory=app.state.db_session_factory,
        queue_size=settings.usage_writer_queue_size,
        worker_count=settings.usage_writer_workers,
    )
    await app.state.usage_writer.start()
    inference_service = InferenceService(cache, router, app.state.usage_writer)
    app.state.request_queue = PriorityRequestQueue(
        max_size=settings.request_queue_max_size,
        worker_count=settings.request_queue_workers,
        handler=inference_service.generate,
    )
    await app.state.request_queue.start()
    app.state.provider_health_task = None
    if settings.provider_health_check_interval_seconds > 0:
        import asyncio

        app.state.provider_health_task = asyncio.create_task(
            provider_health_check_loop(
                app.state.provider_registry,
                settings.provider_health_check_interval_seconds,
            )
        )
    try:
        yield
    finally:
        if app.state.provider_health_task is not None:
            app.state.provider_health_task.cancel()
        await app.state.provider_scorer.stop()
        await app.state.request_queue.stop()
        await app.state.usage_writer.stop()
        await app.state.redis.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    configure_telemetry(app)
    instrument_http_metrics(app)
    mount_prometheus_metrics(app)
    register_exception_handlers(app)
    app.include_router(dashboard_router)
    app.include_router(analytics_router)
    app.include_router(demo_router)
    app.include_router(health_router)
    app.include_router(inference_router)
    return app


app = create_app()
