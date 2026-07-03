from dataclasses import dataclass
from decimal import Decimal

TOKEN_MILLION = Decimal("1000000")
USD_QUANT = Decimal("0.000000001")

OPENAI_PRICING_URL = "https://developers.openai.com/api/docs/pricing"
GEMINI_PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing"
GROQ_PRICING_URL = "https://groq.com/pricing"


@dataclass(frozen=True)
class PriceEntry:
    provider: str
    model: str
    input_per_million_tokens_usd: Decimal
    output_per_million_tokens_usd: Decimal
    source_label: str
    source_url: str | None
    notes: str
    include_in_counterfactual: bool = True
    aliases: tuple[str, ...] = ()

    @property
    def blended_per_million_tokens_usd(self) -> Decimal:
        return self.input_per_million_tokens_usd + self.output_per_million_tokens_usd


DEFAULT_PRICE_CATALOG: tuple[PriceEntry, ...] = (
    PriceEntry(
        provider="dev_echo",
        model="*",
        input_per_million_tokens_usd=Decimal("0"),
        output_per_million_tokens_usd=Decimal("0"),
        source_label="InferX local demo provider",
        source_url=None,
        notes="No external API token bill; host infrastructure cost is not modeled.",
        include_in_counterfactual=False,
    ),
    PriceEntry(
        provider="dev_backup",
        model="*",
        input_per_million_tokens_usd=Decimal("0"),
        output_per_million_tokens_usd=Decimal("0"),
        source_label="InferX local demo provider",
        source_url=None,
        notes="No external API token bill; host infrastructure cost is not modeled.",
        include_in_counterfactual=False,
    ),
    PriceEntry(
        provider="ollama",
        model="*",
        input_per_million_tokens_usd=Decimal("0"),
        output_per_million_tokens_usd=Decimal("0"),
        source_label="Local Ollama runtime",
        source_url=None,
        notes="No hosted API token bill; local CPU/GPU infrastructure cost is not modeled.",
        include_in_counterfactual=False,
    ),
    PriceEntry(
        provider="openai",
        model="chat-latest",
        input_per_million_tokens_usd=Decimal("5.00"),
        output_per_million_tokens_usd=Decimal("30.00"),
        source_label="OpenAI API pricing: ChatGPT chat-latest",
        source_url=OPENAI_PRICING_URL,
        notes="Specialized model pricing, standard tier, per 1M tokens.",
    ),
    PriceEntry(
        provider="openai",
        model="gpt-5.3-codex",
        input_per_million_tokens_usd=Decimal("1.75"),
        output_per_million_tokens_usd=Decimal("14.00"),
        source_label="OpenAI API pricing: gpt-5.3-codex",
        source_url=OPENAI_PRICING_URL,
        notes="Specialized model pricing, standard tier, per 1M tokens.",
    ),
    PriceEntry(
        provider="openai",
        model="gpt-5.3-codex-priority",
        input_per_million_tokens_usd=Decimal("3.50"),
        output_per_million_tokens_usd=Decimal("28.00"),
        source_label="OpenAI API pricing: gpt-5.3-codex priority",
        source_url=OPENAI_PRICING_URL,
        notes="Specialized model pricing, priority tier, per 1M tokens.",
        aliases=("gpt-5.3-codex:priority", "priority/gpt-5.3-codex"),
    ),
    PriceEntry(
        provider="gemini",
        model="gemini-2.5-pro",
        input_per_million_tokens_usd=Decimal("1.25"),
        output_per_million_tokens_usd=Decimal("10.00"),
        source_label="Gemini API pricing: Gemini 2.5 Pro",
        source_url=GEMINI_PRICING_URL,
        notes="Standard tier text pricing for prompts <= 200k tokens, per 1M tokens.",
    ),
    PriceEntry(
        provider="gemini",
        model="gemini-2.5-pro-priority",
        input_per_million_tokens_usd=Decimal("2.25"),
        output_per_million_tokens_usd=Decimal("18.00"),
        source_label="Gemini API pricing: Gemini 2.5 Pro priority",
        source_url=GEMINI_PRICING_URL,
        notes="Priority tier text pricing for prompts <= 200k tokens, per 1M tokens.",
        aliases=("gemini-2.5-pro:priority", "priority/gemini-2.5-pro"),
    ),
    PriceEntry(
        provider="gemini",
        model="gemini-3-pro-image-priority",
        input_per_million_tokens_usd=Decimal("3.60"),
        output_per_million_tokens_usd=Decimal("21.60"),
        source_label="Gemini API pricing: Gemini 3 Pro Image priority text",
        source_url=GEMINI_PRICING_URL,
        notes="Priority text input/output pricing; image output pricing is excluded.",
        aliases=("gemini-3-pro-image:priority",),
    ),
    PriceEntry(
        provider="groq",
        model="llama-3.3-70b-versatile",
        input_per_million_tokens_usd=Decimal("0.59"),
        output_per_million_tokens_usd=Decimal("0.79"),
        source_label="Groq pricing: Llama 3.3 70B Versatile",
        source_url=GROQ_PRICING_URL,
        notes="On-demand LLM pricing, per 1M tokens.",
        aliases=("llama-3.3-70b-versatile-128k",),
    ),
    PriceEntry(
        provider="groq",
        model="qwen-3.6-27b",
        input_per_million_tokens_usd=Decimal("0.60"),
        output_per_million_tokens_usd=Decimal("3.00"),
        source_label="Groq pricing: Qwen 3.6 27B",
        source_url=GROQ_PRICING_URL,
        notes="On-demand LLM pricing, per 1M tokens.",
        aliases=("qwen-3.6-27b-131k",),
    ),
)


def normalize_pricing_key(value: str) -> str:
    return value.strip().lower()


def calculate_token_cost(
    price: PriceEntry,
    prompt_tokens: int,
    completion_tokens: int,
) -> Decimal:
    input_cost = Decimal(prompt_tokens) * price.input_per_million_tokens_usd
    output_cost = Decimal(completion_tokens) * price.output_per_million_tokens_usd
    return ((input_cost + output_cost) / TOKEN_MILLION).quantize(USD_QUANT)


def find_price_entry(
    provider: str,
    model: str,
    catalog: tuple[PriceEntry, ...] = DEFAULT_PRICE_CATALOG,
) -> PriceEntry | None:
    normalized_provider = normalize_pricing_key(provider)
    normalized_model = normalize_pricing_key(model)

    for entry in catalog:
        if normalize_pricing_key(entry.provider) != normalized_provider:
            continue
        candidate_models = {
            normalize_pricing_key(entry.model),
            *map(normalize_pricing_key, entry.aliases),
        }
        if normalized_model in candidate_models:
            return entry

    for entry in catalog:
        if normalize_pricing_key(entry.provider) == normalized_provider and entry.model == "*":
            return entry

    return None


def most_expensive_counterfactual_entry(
    prompt_tokens: int,
    completion_tokens: int,
    catalog: tuple[PriceEntry, ...] = DEFAULT_PRICE_CATALOG,
) -> PriceEntry:
    candidates = [entry for entry in catalog if entry.include_in_counterfactual]
    if not candidates:
        raise ValueError("pricing catalog has no counterfactual candidates")

    return max(
        candidates,
        key=lambda entry: calculate_token_cost(
            entry,
            max(prompt_tokens, 1),
            max(completion_tokens, 1),
        ),
    )


def decimal_usd(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value.quantize(USD_QUANT):f}"
