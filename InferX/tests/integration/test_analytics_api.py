from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.v1.analytics import get_cost_analytics_service
from app.main import create_app
from app.schemas.analytics import CostSavingsResponse
from app.services.auth import AuthenticatedAccount, require_api_key


class FakeCostAnalyticsService:
    def __init__(self) -> None:
        self.since: datetime | None = None
        self.until: datetime | None = None

    async def report_for_account(
        self,
        account: AuthenticatedAccount,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> CostSavingsResponse:
        assert account.key_prefix == "test"
        self.since = since
        self.until = until
        return CostSavingsResponse(
            generated_at=datetime(2026, 7, 2, tzinfo=UTC),
            scope="api_key:test",
            window_start=since,
            window_end=until,
            request_count=1,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            upstream_request_count=1,
            cache_hit_count=0,
            actual_spend_usd="0.000001000",
            actual_spend_complete=True,
            unpriced_request_count=0,
            counterfactual_provider="openai",
            counterfactual_model="chat-latest",
            counterfactual_pricing_source="OpenAI API pricing: ChatGPT chat-latest",
            counterfactual_pricing_source_url="https://developers.openai.com/api/docs/pricing",
            counterfactual_input_price_per_million_tokens_usd="5.000000000",
            counterfactual_output_price_per_million_tokens_usd="30.000000000",
            counterfactual_spend_usd="0.000650000",
            savings_usd="0.000649000",
            savings_percent=99.85,
            by_provider=[],
            model_breakdown=[],
            notes=["test response"],
        )


def test_cost_savings_endpoint_requires_auth_and_returns_report() -> None:
    app = create_app()
    service = FakeCostAnalyticsService()
    app.dependency_overrides[require_api_key] = lambda: AuthenticatedAccount(
        user_id="user-id",
        api_key_id="key-id",
        tier="premium",
        key_prefix="test",
    )
    app.dependency_overrides[get_cost_analytics_service] = lambda: service

    with TestClient(app) as client:
        response = client.get(
            "/v1/analytics/cost-savings"
            "?since=2026-07-02T10:00:00Z&until=2026-07-02T10:05:00Z",
            headers={"X-API-Key": "unused-by-override"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "api_key:test"
    assert body["counterfactual_provider"] == "openai"
    assert body["savings_percent"] == 99.85
    assert body["window_start"] == "2026-07-02T10:00:00Z"
    assert body["window_end"] == "2026-07-02T10:05:00Z"
    assert service.since == datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
    assert service.until == datetime(2026, 7, 2, 10, 5, tzinfo=UTC)


def test_cost_savings_endpoint_rejects_invalid_window() -> None:
    app = create_app()
    app.dependency_overrides[require_api_key] = lambda: AuthenticatedAccount(
        user_id="user-id",
        api_key_id="key-id",
        tier="premium",
        key_prefix="test",
    )
    app.dependency_overrides[get_cost_analytics_service] = lambda: FakeCostAnalyticsService()

    with TestClient(app) as client:
        response = client.get(
            "/v1/analytics/cost-savings"
            "?since=2026-07-02T10:05:00Z&until=2026-07-02T10:00:00Z",
            headers={"X-API-Key": "unused-by-override"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "since must be before or equal to until"
