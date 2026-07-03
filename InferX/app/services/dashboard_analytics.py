from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UsageRecord
from app.routing.provider_scoring import ProviderScorer, ProviderScoreSnapshot
from app.schemas.analytics import (
    AnalyticsOverviewResponse,
    AnalyticsProviderUsage,
    ProviderScoreView,
)
from app.services.pricing import decimal_usd


async def build_analytics_overview(
    session: AsyncSession,
    scorer: ProviderScorer | None,
    window_seconds: int,
) -> AnalyticsOverviewResponse:
    generated_at = datetime.now(UTC)
    cutoff = generated_at - timedelta(seconds=window_seconds)
    statement = (
        select(
            UsageRecord.provider,
            func.count(UsageRecord.id),
            func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
            func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
            func.coalesce(func.sum(UsageRecord.total_tokens), 0),
            func.coalesce(
                func.sum(case((UsageRecord.cache_tier != "miss", 1), else_=0)),
                0,
            ),
            func.avg(UsageRecord.latency_ms),
            func.coalesce(
                func.sum(case((UsageRecord.status != "success", 1), else_=0)),
                0,
            ),
        )
        .where(UsageRecord.created_at >= cutoff)
        .group_by(UsageRecord.provider)
        .order_by(func.count(UsageRecord.id).desc(), UsageRecord.provider)
    )

    result = await session.execute(statement)
    provider_usage: list[AnalyticsProviderUsage] = []
    error_count = 0
    for row in result.all():
        provider_error_count = int(row[7])
        error_count += provider_error_count
        provider_usage.append(
            AnalyticsProviderUsage(
                provider=row[0],
                request_count=int(row[1]),
                prompt_tokens=int(row[2]),
                completion_tokens=int(row[3]),
                total_tokens=int(row[4]),
                cache_hit_count=int(row[5]),
                avg_latency_ms=float(row[6]) if row[6] is not None else None,
            )
        )

    request_count = sum(provider.request_count for provider in provider_usage)
    cache_hit_count = sum(provider.cache_hit_count for provider in provider_usage)
    cache_hit_percent = (
        round((cache_hit_count / request_count) * 100, 2)
        if request_count
        else 0.0
    )

    return AnalyticsOverviewResponse(
        generated_at=generated_at,
        window_seconds=window_seconds,
        request_count=request_count,
        error_count=error_count,
        cache_hit_count=cache_hit_count,
        cache_hit_percent=cache_hit_percent,
        provider_usage=provider_usage,
        provider_scores=[
            provider_score_to_view(snapshot)
            for snapshot in (scorer.snapshots() if scorer else [])
        ],
    )


def provider_score_to_view(snapshot: ProviderScoreSnapshot) -> ProviderScoreView:
    return ProviderScoreView(
        provider=snapshot.provider,
        score=snapshot.score,
        previous_score=snapshot.previous_score,
        latency_ms=snapshot.latency_ms,
        error_rate=round(snapshot.error_rate, 4),
        cost_per_million_tokens_usd=decimal_usd(snapshot.cost_per_million_tokens_usd),
        request_count=snapshot.request_count,
        error_count=snapshot.error_count,
        healthy=snapshot.healthy,
        circuit_state=snapshot.circuit_state,
        updated_at=snapshot.updated_at,
    )
