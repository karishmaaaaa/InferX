from datetime import datetime

from pydantic import BaseModel


class ProviderScoreView(BaseModel):
    provider: str
    score: float
    previous_score: float | None
    latency_ms: float | None
    error_rate: float
    cost_per_million_tokens_usd: str | None
    request_count: int
    error_count: int
    healthy: bool
    circuit_state: str
    updated_at: datetime


class AnalyticsProviderUsage(BaseModel):
    provider: str
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cache_hit_count: int
    avg_latency_ms: float | None


class AnalyticsOverviewResponse(BaseModel):
    generated_at: datetime
    window_seconds: int
    request_count: int
    error_count: int
    cache_hit_count: int
    cache_hit_percent: float
    provider_usage: list[AnalyticsProviderUsage]
    provider_scores: list[ProviderScoreView]


class CostProviderModelBreakdown(BaseModel):
    provider: str
    model: str
    cache_tier: str
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    upstream_request_count: int
    cache_hit_count: int
    spend_usd: str | None
    input_price_per_million_tokens_usd: str | None
    output_price_per_million_tokens_usd: str | None
    pricing_known: bool
    pricing_source: str | None = None
    pricing_source_url: str | None = None
    pricing_notes: str | None = None


class CostProviderBreakdown(BaseModel):
    provider: str
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    upstream_request_count: int
    cache_hit_count: int
    spend_usd: str
    pricing_complete: bool
    unpriced_request_count: int


class CostSavingsResponse(BaseModel):
    generated_at: datetime
    scope: str
    window_start: datetime | None = None
    window_end: datetime | None = None
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    upstream_request_count: int
    cache_hit_count: int
    actual_spend_usd: str
    actual_spend_complete: bool
    unpriced_request_count: int
    counterfactual_provider: str
    counterfactual_model: str
    counterfactual_pricing_source: str
    counterfactual_pricing_source_url: str | None
    counterfactual_input_price_per_million_tokens_usd: str
    counterfactual_output_price_per_million_tokens_usd: str
    counterfactual_spend_usd: str
    savings_usd: str | None
    savings_percent: float | None
    by_provider: list[CostProviderBreakdown]
    model_breakdown: list[CostProviderModelBreakdown]
    notes: list[str]
