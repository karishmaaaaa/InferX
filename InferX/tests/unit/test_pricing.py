from decimal import Decimal

from app.services.pricing import (
    calculate_token_cost,
    find_price_entry,
    most_expensive_counterfactual_entry,
)


def test_local_provider_has_zero_external_api_cost() -> None:
    price = find_price_entry("dev_echo", "any-local-model")

    assert price is not None
    assert calculate_token_cost(price, prompt_tokens=1000, completion_tokens=1000) == Decimal(
        "0.000000000"
    )


def test_known_hosted_provider_cost_uses_input_and_output_prices() -> None:
    price = find_price_entry("groq", "llama-3.3-70b-versatile")

    assert price is not None
    assert calculate_token_cost(price, prompt_tokens=1_000_000, completion_tokens=1_000_000) == (
        Decimal("1.380000000")
    )


def test_unknown_hosted_model_is_not_priced_by_provider_default() -> None:
    assert find_price_entry("openai", "not-in-catalog") is None


def test_counterfactual_uses_highest_cost_priced_catalog_entry() -> None:
    price = most_expensive_counterfactual_entry(prompt_tokens=1_000, completion_tokens=1_000)

    assert price.provider == "openai"
    assert price.model == "chat-latest"
