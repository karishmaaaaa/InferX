import pytest

from app.providers.adapters.dev import DevEchoProvider
from app.providers.registry import ProviderRegistry
from app.routing.provider_scoring import ProviderScorer


@pytest.mark.asyncio
async def test_provider_scorer_prefers_lower_latency_and_error_rate() -> None:
    registry = ProviderRegistry(
        [DevEchoProvider(name="slow"), DevEchoProvider(name="fast")],
    )
    scorer = ProviderScorer(
        registry=registry,
        session_factory=None,
        interval_seconds=60,
        window_seconds=300,
    )
    scorer.record_attempt("slow", "demo", "success", latency_ms=900)
    scorer.record_attempt("slow", "demo", "error", latency_ms=1000)
    scorer.record_attempt("fast", "demo", "success", latency_ms=10)

    await scorer.score_once()

    assert scorer.score_for("fast") > scorer.score_for("slow")
    assert scorer.ranked_provider_names(["slow", "fast"]) == ["fast", "slow"]


@pytest.mark.asyncio
async def test_provider_scorer_zeroes_unhealthy_provider() -> None:
    primary = DevEchoProvider(name="primary")
    backup = DevEchoProvider(name="backup")
    primary.set_forced_down(True)
    registry = ProviderRegistry([primary, backup])
    scorer = ProviderScorer(
        registry=registry,
        session_factory=None,
        interval_seconds=60,
        window_seconds=300,
    )

    snapshots = await scorer.score_once()

    scores = {snapshot.provider: snapshot for snapshot in snapshots}
    assert scores["primary"].healthy is False
    assert scores["primary"].score == 0.0
    assert scores["backup"].score > scores["primary"].score
