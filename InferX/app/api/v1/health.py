from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.providers.registry import ProviderRegistry, get_provider_registry

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str


class ProviderHealthResponse(BaseModel):
    providers: dict[str, str]
    circuits: dict[str, str]
    configured_count: int


@router.get("/health", response_model=HealthResponse)
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        environment=settings.environment,
    )


@router.get("/v1/providers/health", response_model=ProviderHealthResponse)
async def provider_health(
    registry: Annotated[ProviderRegistry, Depends(get_provider_registry)],
) -> ProviderHealthResponse:
    results = await registry.health_check_all()
    return ProviderHealthResponse(
        providers=results,
        circuits=registry.circuit_snapshots(),
        configured_count=len(results),
    )
