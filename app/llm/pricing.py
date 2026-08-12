"""Estimated USD cost per LLM turn, from the provider's usage counts.

Prices are USD per million tokens (Anthropic list prices). Cache reads bill at
0.1x input, 5-minute cache writes at 1.25x input. Token COUNTS always come from
``response.usage`` — only the price table lives here. An unknown model prices
at 0 so the pipeline never fabricates a cost figure for a model we have not
priced (the turn row still carries the real token counts).
"""
from __future__ import annotations

# model-id prefix -> (input, output, cache_read, cache_write_5m) USD per 1M tokens
PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00, 0.10, 1.25),
    "claude-sonnet-4-5": (3.00, 15.00, 0.30, 3.75),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30, 3.75),
    "claude-opus-4": (5.00, 25.00, 0.50, 6.25),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int,
                      cache_read_tokens: int, cache_write_tokens: int) -> float:
    model = (model or "").lower()
    for prefix, (p_in, p_out, p_read, p_write) in PRICING.items():
        if model.startswith(prefix):
            return round(
                (input_tokens * p_in + output_tokens * p_out
                 + cache_read_tokens * p_read + cache_write_tokens * p_write) / 1_000_000,
                6)
    return 0.0


def estimate_cost_no_cache_usd(model: str, input_tokens: int, output_tokens: int,
                               cache_read_tokens: int, cache_write_tokens: int) -> float:
    """What the SAME turn would cost with NO prompt caching: every prompt token
    (uncached + cache-read + cache-write) priced at the full input rate.
    Round H task 3.3 — used for the Generate-button projection when
    ASSUME_PROMPT_CACHING=false (the operator measured, via
    scripts/check_cache_support.py, that the provider caches nothing)."""
    return estimate_cost_usd(
        model, input_tokens + cache_read_tokens + cache_write_tokens,
        output_tokens, 0, 0)
