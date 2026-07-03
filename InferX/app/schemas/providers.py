from enum import StrEnum

from pydantic import BaseModel


class ProviderStatus(StrEnum):
    configured = "configured"
    not_configured = "not_configured"
    healthy = "healthy"
    unhealthy = "unhealthy"


class ProviderHealth(BaseModel):
    name: str
    status: ProviderStatus
    detail: str | None = None
