import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app

HTTP_REQUESTS_TOTAL = Counter(
    "inferx_http_requests_total",
    "Total HTTP requests received by InferX.",
    ["method", "path", "status_code"],
)

HTTP_REQUEST_LATENCY_SECONDS = Histogram(
    "inferx_http_request_latency_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

INFERENCE_REQUESTS_TOTAL = Counter(
    "inferx_inference_requests_total",
    "Inference requests by account tier and status.",
    ["tier", "status"],
)

INFERENCE_LATENCY_SECONDS = Histogram(
    "inferx_inference_latency_seconds",
    "End-to-end inference latency after authentication in seconds.",
    ["tier", "cache_tier"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

ERRORS_TOTAL = Counter(
    "inferx_errors_total",
    "Gateway errors by type.",
    ["error_type"],
)

CACHE_EVENTS_TOTAL = Counter(
    "inferx_cache_events_total",
    "Cache lookup events by tier and result.",
    ["tier", "result"],
)

PROVIDER_REQUESTS_TOTAL = Counter(
    "inferx_provider_requests_total",
    "Provider request attempts by provider and status.",
    ["provider", "status"],
)

PROVIDER_REQUEST_LATENCY_SECONDS = Histogram(
    "inferx_provider_request_latency_seconds",
    "Provider request attempt latency in seconds.",
    ["provider", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

FAILOVERS_TOTAL = Counter(
    "inferx_failovers_total",
    "Automatic provider failovers by failed provider and next provider.",
    ["failed_provider", "next_provider", "reason"],
)

QUEUE_DEPTH = Gauge(
    "inferx_queue_depth",
    "Current inference priority queue depth.",
)

ACTIVE_STREAMING_SESSIONS = Gauge(
    "inferx_active_streaming_sessions",
    "Currently open streaming inference responses.",
)

CIRCUIT_STATE = Gauge(
    "inferx_provider_circuit_state",
    "Circuit breaker state per provider: 0=closed, 1=open, 2=half_open.",
    ["provider"],
)

PROVIDER_SCORE = Gauge(
    "inferx_provider_score",
    "Current adaptive router score per provider.",
    ["provider"],
)

PROVIDER_RECENT_LATENCY_MS = Gauge(
    "inferx_provider_recent_latency_ms",
    "Recent average provider attempt latency used by adaptive routing.",
    ["provider"],
)

PROVIDER_RECENT_ERROR_RATE = Gauge(
    "inferx_provider_recent_error_rate",
    "Recent provider attempt error rate used by adaptive routing.",
    ["provider"],
)

PROVIDER_RECENT_COST_PER_MILLION_TOKENS_USD = Gauge(
    "inferx_provider_recent_cost_per_million_tokens_usd",
    "Recent provider cost per million tokens used by adaptive routing when pricing is known.",
    ["provider"],
)


def mount_prometheus_metrics(app: FastAPI) -> None:
    app.mount("/metrics", make_asgi_app())


def instrument_http_metrics(app: FastAPI) -> None:
    @app.middleware("http")
    async def metrics_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        latency = time.perf_counter() - start
        path = request.scope.get("route").path if request.scope.get("route") else request.url.path
        status_code = str(response.status_code)
        HTTP_REQUESTS_TOTAL.labels(request.method, path, status_code).inc()
        HTTP_REQUEST_LATENCY_SECONDS.labels(request.method, path).observe(latency)
        return response
