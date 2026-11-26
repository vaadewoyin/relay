from relay.intelligence.contracts import Usage
from relay.intelligence.gemini import DEFAULT_MODEL


def estimate_cost(model: str, usage: Usage) -> float | None:
    # Published standard Gemini Developer API USD rates per million text tokens.
    # An estimate uses only observed usage and excludes retries without token metadata.
    if (
        model != DEFAULT_MODEL
        or usage.input_tokens is None
        or usage.output_tokens is None
    ):
        return None
    output = usage.output_tokens + (usage.thinking_tokens or 0)
    return round((usage.input_tokens * 0.25 + output * 1.50) / 1_000_000, 7)
