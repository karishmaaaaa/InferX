from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.routing.provider_scoring import ProviderScorer
from app.schemas.analytics import AnalyticsOverviewResponse, CostSavingsResponse
from app.services.auth import AuthenticatedAccount, require_api_key
from app.services.cost_analytics import CostAnalyticsService, normalize_report_window
from app.services.dashboard_analytics import build_analytics_overview

router = APIRouter(prefix="/v1/analytics", tags=["analytics"])


def get_cost_analytics_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CostAnalyticsService:
    return CostAnalyticsService(session)


def get_provider_scorer(request: Request) -> ProviderScorer | None:
    return getattr(request.app.state, "provider_scorer", None)


@router.get("", response_model=AnalyticsOverviewResponse)
async def analytics_overview(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    scorer: Annotated[ProviderScorer | None, Depends(get_provider_scorer)],
    window_seconds: Annotated[
        int,
        Query(ge=30, le=3600, description="Recent usage window in seconds."),
    ] = 300,
) -> AnalyticsOverviewResponse:
    return await build_analytics_overview(
        session=session,
        scorer=scorer,
        window_seconds=window_seconds,
    )


@router.get("/cost-savings", response_model=CostSavingsResponse)
async def cost_savings(
    account: Annotated[AuthenticatedAccount, Depends(require_api_key)],
    service: Annotated[CostAnalyticsService, Depends(get_cost_analytics_service)],
    since: Annotated[
        datetime | None,
        Query(description="Only include usage records created at or after this timestamp."),
    ] = None,
    until: Annotated[
        datetime | None,
        Query(description="Only include usage records created at or before this timestamp."),
    ] = None,
) -> CostSavingsResponse:
    try:
        since, until = normalize_report_window(since, until)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return await service.report_for_account(account, since=since, until=until)
