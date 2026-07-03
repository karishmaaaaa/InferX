from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import get_settings

_TRACER_PROVIDER_CONFIGURED = False


def configure_telemetry(app: FastAPI) -> None:
    global _TRACER_PROVIDER_CONFIGURED

    settings = get_settings()
    tracer_provider = None
    if not _TRACER_PROVIDER_CONFIGURED:
        resource = Resource.create({"service.name": settings.otel_service_name})
        tracer_provider = TracerProvider(resource=resource)
        if settings.otel_exporter_otlp_endpoint:
            exporter = OTLPSpanExporter(
                endpoint=settings.otel_exporter_otlp_endpoint,
                insecure=True,
            )
            tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(tracer_provider)
        _TRACER_PROVIDER_CONFIGURED = True
    else:
        active_provider = trace.get_tracer_provider()
        if isinstance(active_provider, TracerProvider):
            tracer_provider = active_provider

    FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)
    app.state.telemetry_enabled = True
