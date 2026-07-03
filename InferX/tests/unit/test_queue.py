from app.routing.queue import priority_for_tier


def test_premium_tier_gets_lower_priority_value_than_free_tier() -> None:
    assert priority_for_tier("premium") < priority_for_tier("free")
