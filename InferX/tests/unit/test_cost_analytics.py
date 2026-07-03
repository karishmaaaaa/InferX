from datetime import UTC, datetime

from app.services.cost_analytics import UsagePricingRow, build_cost_savings_report


def test_cost_savings_report_uses_logged_provider_tokens_and_counterfactual() -> None:
    report = build_cost_savings_report(
        [
            UsagePricingRow(
                provider="groq",
                model="llama-3.3-70b-versatile",
                cache_tier="miss",
                request_count=2,
                prompt_tokens=1_000_000,
                completion_tokens=1_000_000,
                total_tokens=2_000_000,
            )
        ],
        scope="api_key:test",
        generated_at=datetime(2026, 7, 2, tzinfo=UTC),
    )

    assert report.request_count == 2
    assert report.actual_spend_usd == "1.380000000"
    assert report.counterfactual_provider == "openai"
    assert report.counterfactual_model == "chat-latest"
    assert report.counterfactual_spend_usd == "35.000000000"
    assert report.savings_usd == "33.620000000"
    assert report.savings_percent == 96.06
    assert report.by_provider[0].provider == "groq"
    assert report.by_provider[0].spend_usd == "1.380000000"


def test_cache_hits_are_counted_as_zero_upstream_spend() -> None:
    report = build_cost_savings_report(
        [
            UsagePricingRow(
                provider="groq",
                model="llama-3.3-70b-versatile",
                cache_tier="semantic",
                request_count=1,
                prompt_tokens=1_000_000,
                completion_tokens=1_000_000,
                total_tokens=2_000_000,
            )
        ],
        scope="api_key:test",
        generated_at=datetime(2026, 7, 2, tzinfo=UTC),
    )

    assert report.actual_spend_usd == "0.000000000"
    assert report.counterfactual_spend_usd == "35.000000000"
    assert report.savings_percent == 100.0
    assert report.cache_hit_count == 1
    assert report.upstream_request_count == 0


def test_unpriced_upstream_rows_do_not_fabricate_savings_percent() -> None:
    report = build_cost_savings_report(
        [
            UsagePricingRow(
                provider="sarvam",
                model="unknown-public-pricing",
                cache_tier="miss",
                request_count=1,
                prompt_tokens=100,
                completion_tokens=100,
                total_tokens=200,
            )
        ],
        scope="api_key:test",
        generated_at=datetime(2026, 7, 2, tzinfo=UTC),
    )

    assert report.actual_spend_complete is False
    assert report.unpriced_request_count == 1
    assert report.savings_usd is None
    assert report.savings_percent is None
    assert report.model_breakdown[0].spend_usd is None


def test_empty_report_is_explicitly_zero_and_notes_no_usage() -> None:
    report = build_cost_savings_report(
        [],
        scope="api_key:test",
        generated_at=datetime(2026, 7, 2, tzinfo=UTC),
    )

    assert report.request_count == 0
    assert report.actual_spend_usd == "0.000000000"
    assert report.counterfactual_spend_usd == "0.000000000"
    assert report.savings_percent == 0.0
    assert "No usage records found" in report.notes[-1]
