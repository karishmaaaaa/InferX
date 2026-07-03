from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UsageRecord
from app.schemas.analytics import (
    CostProviderBreakdown,
    CostProviderModelBreakdown,
    CostSavingsResponse,
)
from app.services.auth import AuthenticatedAccount
from app.services.pricing import (
    DEFAULT_PRICE_CATALOG,
    PriceEntry,
    calculate_token_cost,
    decimal_usd,
    find_price_entry,
    most_expensive_counterfactual_entry,
)

CACHE_MISS_TIER = "miss"


@dataclass(frozen=True)
class UsagePricingRow:
    provider: str
    model: str
    cache_tier: str
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class ProviderCostAccumulator:
    provider: str
    request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    upstream_request_count: int = 0
    cache_hit_count: int = 0
    spend_usd: Decimal = Decimal("0")
    pricing_complete: bool = True
    unpriced_request_count: int = 0

    def to_schema(self) -> CostProviderBreakdown:
        return CostProviderBreakdown(
            provider=self.provider,
            request_count=self.request_count,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
            upstream_request_count=self.upstream_request_count,
            cache_hit_count=self.cache_hit_count,
            spend_usd=decimal_usd(self.spend_usd) or "0.000000000",
            pricing_complete=self.pricing_complete,
            unpriced_request_count=self.unpriced_request_count,
        )


class CostAnalyticsService:
    def __init__(
        self,
        session: AsyncSession,
        catalog: tuple[PriceEntry, ...] = DEFAULT_PRICE_CATALOG,
    ) -> None:
        self.session = session
        self.catalog = catalog

    async def report_for_account(
        self,
        account: AuthenticatedAccount,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> CostSavingsResponse:
        since, until = normalize_report_window(since, until)
        rows = await fetch_usage_pricing_rows(self.session, account, since=since, until=until)
        return build_cost_savings_report(
            rows,
            scope=f"api_key:{account.key_prefix}",
            catalog=self.catalog,
            window_start=since,
            window_end=until,
        )


async def fetch_usage_pricing_rows(
    session: AsyncSession,
    account: AuthenticatedAccount,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[UsagePricingRow]:
    filters = [
        UsageRecord.user_id == account.user_id,
        UsageRecord.api_key_id == account.api_key_id,
        UsageRecord.status == "success",
    ]
    if since is not None:
        filters.append(UsageRecord.created_at >= since)
    if until is not None:
        filters.append(UsageRecord.created_at <= until)

    statement = (
        select(
            UsageRecord.provider,
            UsageRecord.model,
            UsageRecord.cache_tier,
            func.count(UsageRecord.id),
            func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
            func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
            func.coalesce(func.sum(UsageRecord.total_tokens), 0),
        )
        .where(*filters)
        .group_by(UsageRecord.provider, UsageRecord.model, UsageRecord.cache_tier)
        .order_by(UsageRecord.provider, UsageRecord.model, UsageRecord.cache_tier)
    )
    result = await session.execute(statement)
    return [
        UsagePricingRow(
            provider=row[0],
            model=row[1],
            cache_tier=row[2],
            request_count=int(row[3]),
            prompt_tokens=int(row[4]),
            completion_tokens=int(row[5]),
            total_tokens=int(row[6]),
        )
        for row in result.all()
    ]


def build_cost_savings_report(
    rows: list[UsagePricingRow],
    scope: str,
    catalog: tuple[PriceEntry, ...] = DEFAULT_PRICE_CATALOG,
    generated_at: datetime | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> CostSavingsResponse:
    generated_at = generated_at or datetime.now(UTC)
    window_start, window_end = normalize_report_window(window_start, window_end)
    total_prompt_tokens = sum(row.prompt_tokens for row in rows)
    total_completion_tokens = sum(row.completion_tokens for row in rows)
    total_tokens = sum(row.total_tokens for row in rows)
    request_count = sum(row.request_count for row in rows)
    cache_hit_count = sum(row.request_count for row in rows if row.cache_tier != CACHE_MISS_TIER)
    upstream_request_count = request_count - cache_hit_count

    counterfactual = most_expensive_counterfactual_entry(
        total_prompt_tokens,
        total_completion_tokens,
        catalog,
    )
    counterfactual_spend = calculate_token_cost(
        counterfactual,
        total_prompt_tokens,
        total_completion_tokens,
    )

    provider_accumulators: dict[str, ProviderCostAccumulator] = {}
    model_breakdown: list[CostProviderModelBreakdown] = []
    actual_spend = Decimal("0")
    unpriced_request_count = 0

    for row in rows:
        provider = provider_accumulators.setdefault(
            row.provider,
            ProviderCostAccumulator(provider=row.provider),
        )
        provider.request_count += row.request_count
        provider.prompt_tokens += row.prompt_tokens
        provider.completion_tokens += row.completion_tokens
        provider.total_tokens += row.total_tokens

        row_is_cache_hit = row.cache_tier != CACHE_MISS_TIER
        if row_is_cache_hit:
            row_spend = Decimal("0")
            row_pricing_known = True
            row_pricing_source = "InferX cache"
            row_source_url = None
            row_notes = "Served locally from cache; no upstream provider call was made."
            row_input_price = Decimal("0")
            row_output_price = Decimal("0")
            provider.cache_hit_count += row.request_count
        else:
            provider.upstream_request_count += row.request_count
            price = find_price_entry(row.provider, row.model, catalog)
            if price is None:
                row_spend = None
                row_pricing_known = False
                row_pricing_source = None
                row_source_url = None
                row_notes = "No verified pricing catalog entry for this provider/model."
                row_input_price = None
                row_output_price = None
                provider.pricing_complete = False
                provider.unpriced_request_count += row.request_count
                unpriced_request_count += row.request_count
            else:
                row_spend = calculate_token_cost(price, row.prompt_tokens, row.completion_tokens)
                row_pricing_known = True
                row_pricing_source = price.source_label
                row_source_url = price.source_url
                row_notes = price.notes
                row_input_price = price.input_per_million_tokens_usd
                row_output_price = price.output_per_million_tokens_usd
                provider.spend_usd += row_spend
                actual_spend += row_spend

        model_breakdown.append(
            CostProviderModelBreakdown(
                provider=row.provider,
                model=row.model,
                cache_tier=row.cache_tier,
                request_count=row.request_count,
                prompt_tokens=row.prompt_tokens,
                completion_tokens=row.completion_tokens,
                total_tokens=row.total_tokens,
                upstream_request_count=0 if row_is_cache_hit else row.request_count,
                cache_hit_count=row.request_count if row_is_cache_hit else 0,
                spend_usd=decimal_usd(row_spend),
                input_price_per_million_tokens_usd=decimal_usd(row_input_price),
                output_price_per_million_tokens_usd=decimal_usd(row_output_price),
                pricing_known=row_pricing_known,
                pricing_source=row_pricing_source,
                pricing_source_url=row_source_url,
                pricing_notes=row_notes,
            )
        )

    actual_spend_complete = unpriced_request_count == 0
    savings = counterfactual_spend - actual_spend if actual_spend_complete else None
    savings_percent = calculate_savings_percent(savings, counterfactual_spend)

    notes = [
        "Reads successful usage_records for the authenticated API key only.",
        (
            "Counterfactual assumes every logged request was sent to the highest-cost "
            "priced catalog model."
        ),
        "Cache-hit rows count as $0 upstream API spend because InferX served them locally.",
    ]
    if window_start is not None or window_end is not None:
        notes.append(
            "Session window filter applied to usage_records.created_at: "
            f"{window_start.isoformat() if window_start else 'beginning'} to "
            f"{window_end.isoformat() if window_end else 'now'}."
        )
    if request_count == 0:
        notes.append("No usage records found; run authenticated /v1/generate requests first.")
    if unpriced_request_count:
        notes.append(
            "Savings percent is omitted because at least one upstream row has unknown pricing."
        )

    by_provider = sorted(
        (accumulator.to_schema() for accumulator in provider_accumulators.values()),
        key=lambda item: item.provider,
    )

    return CostSavingsResponse(
        generated_at=generated_at,
        scope=scope,
        window_start=window_start,
        window_end=window_end,
        request_count=request_count,
        prompt_tokens=total_prompt_tokens,
        completion_tokens=total_completion_tokens,
        total_tokens=total_tokens,
        upstream_request_count=upstream_request_count,
        cache_hit_count=cache_hit_count,
        actual_spend_usd=decimal_usd(actual_spend) or "0.000000000",
        actual_spend_complete=actual_spend_complete,
        unpriced_request_count=unpriced_request_count,
        counterfactual_provider=counterfactual.provider,
        counterfactual_model=counterfactual.model,
        counterfactual_pricing_source=counterfactual.source_label,
        counterfactual_pricing_source_url=counterfactual.source_url,
        counterfactual_input_price_per_million_tokens_usd=decimal_usd(
            counterfactual.input_per_million_tokens_usd
        )
        or "0.000000000",
        counterfactual_output_price_per_million_tokens_usd=decimal_usd(
            counterfactual.output_per_million_tokens_usd
        )
        or "0.000000000",
        counterfactual_spend_usd=decimal_usd(counterfactual_spend) or "0.000000000",
        savings_usd=decimal_usd(savings),
        savings_percent=savings_percent,
        by_provider=by_provider,
        model_breakdown=model_breakdown,
        notes=notes,
    )


def calculate_savings_percent(
    savings: Decimal | None,
    counterfactual_spend: Decimal,
) -> float | None:
    if savings is None:
        return None
    if counterfactual_spend <= 0:
        return 0.0
    percent = (savings / counterfactual_spend) * Decimal("100")
    return float(percent.quantize(Decimal("0.01")))


def normalize_report_window(
    since: datetime | None,
    until: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    normalized_since = normalize_utc_datetime(since)
    normalized_until = normalize_utc_datetime(until)
    if normalized_since is not None and normalized_until is not None:
        if normalized_since > normalized_until:
            raise ValueError("since must be before or equal to until")
    return normalized_since, normalized_until


def normalize_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
