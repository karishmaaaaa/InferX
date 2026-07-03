import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.metrics.prometheus import ACTIVE_STREAMING_SESSIONS
from app.providers.registry import ProviderRegistry, get_provider_registry
from app.routing.provider_scoring import ProviderScorer
from app.routing.router import InferenceRouter
from app.schemas.inference import InferenceRequest
from app.services.auth import AuthenticatedAccount, require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/demo", tags=["demo"])


class DemoProviderRequest(BaseModel):
    provider: str | None = None


class DemoProviderResponse(BaseModel):
    provider: str
    forced_down: bool
    providers: dict[str, dict[str, bool | str]]
    circuits: dict[str, str]


def get_inference_router(request: Request) -> InferenceRouter:
    return request.app.state.inference_router


def get_provider_scorer(request: Request) -> ProviderScorer | None:
    return getattr(request.app.state, "provider_scorer", None)


def require_demo_enabled(settings: Settings) -> None:
    if not settings.enable_demo_controls:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo controls are disabled",
        )


def require_premium_demo_account(account: AuthenticatedAccount) -> None:
    if account.tier != "premium":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo controls require a premium local API key",
        )


@router.post("/kill-provider", response_model=DemoProviderResponse)
async def kill_provider(
    body: DemoProviderRequest,
    account: Annotated[AuthenticatedAccount, Depends(require_api_key)],
    registry: Annotated[ProviderRegistry, Depends(get_provider_registry)],
    settings: Annotated[Settings, Depends(get_settings)],
    scorer: Annotated[ProviderScorer | None, Depends(get_provider_scorer)],
) -> DemoProviderResponse:
    require_demo_enabled(settings)
    require_premium_demo_account(account)
    provider = body.provider or _first_routable_provider(registry, settings)
    registry.set_provider_forced_down(provider, forced_down=True)
    if scorer is not None:
        await scorer.score_once()
    logger.warning("demo provider killed provider=%s key_prefix=%s", provider, account.key_prefix)
    return _demo_response(provider, forced_down=True, registry=registry)


@router.post("/restore-provider", response_model=DemoProviderResponse)
async def restore_provider(
    body: DemoProviderRequest,
    account: Annotated[AuthenticatedAccount, Depends(require_api_key)],
    registry: Annotated[ProviderRegistry, Depends(get_provider_registry)],
    settings: Annotated[Settings, Depends(get_settings)],
    scorer: Annotated[ProviderScorer | None, Depends(get_provider_scorer)],
) -> DemoProviderResponse:
    require_demo_enabled(settings)
    require_premium_demo_account(account)
    provider = body.provider or _first_routable_provider(registry, settings)
    registry.set_provider_forced_down(provider, forced_down=False)
    if scorer is not None:
        await scorer.score_once()
    logger.warning("demo provider restored provider=%s key_prefix=%s", provider, account.key_prefix)
    return _demo_response(provider, forced_down=False, registry=registry)


@router.post("/stream")
async def stream_demo(
    inference_request: InferenceRequest,
    account: Annotated[AuthenticatedAccount, Depends(require_api_key)],
    inference_router: Annotated[InferenceRouter, Depends(get_inference_router)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    require_demo_enabled(settings)
    require_premium_demo_account(account)
    routed = await inference_router.stream(inference_request)
    logger.info(
        "demo stream opened provider=%s attempted_chain=%s key_prefix=%s",
        routed.provider,
        routed.attempted_chain,
        account.key_prefix,
    )

    async def events() -> AsyncIterator[str]:
        ACTIVE_STREAMING_SESSIONS.inc()
        try:
            yield _sse(
                "route",
                {"provider": routed.provider, "attempted_chain": routed.attempted_chain},
            )
            async for chunk in routed.stream:
                yield _sse("token", chunk.model_dump(mode="json"))
            yield _sse("done", {"provider": routed.provider})
        finally:
            ACTIVE_STREAMING_SESSIONS.dec()

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/providers")
async def demo_providers(
    account: Annotated[AuthenticatedAccount, Depends(require_api_key)],
    registry: Annotated[ProviderRegistry, Depends(get_provider_registry)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, dict[str, dict[str, bool | str]] | dict[str, str]]:
    require_demo_enabled(settings)
    require_premium_demo_account(account)
    return {
        "providers": registry.demo_provider_states(),
        "circuits": registry.circuit_snapshots(),
    }


def _first_routable_provider(registry: ProviderRegistry, settings: Settings) -> str:
    order = registry.priority_order(settings.provider_priority)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No providers are registered",
        )
    return order[0]


def _demo_response(
    provider: str,
    forced_down: bool,
    registry: ProviderRegistry,
) -> DemoProviderResponse:
    return DemoProviderResponse(
        provider=provider,
        forced_down=forced_down,
        providers=registry.demo_provider_states(),
        circuits=registry.circuit_snapshots(),
    )


def _sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"
