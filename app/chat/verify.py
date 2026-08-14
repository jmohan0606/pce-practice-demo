"""Round E chat 1.3 — output verification for chat answers.

Every figure in a chat answer must trace to a tool result fetched THIS
conversation (or to the page context / the user's own message — a figure the
user typed may be echoed back). Reuses the numeric extraction and collection
machinery from ``app.agents.insights_reporter`` (verify_numbers' internals) so
chat and insights share one definition of "a number appears in the data".

Additionally: system-prompt text must never appear in output — a LITERAL
substring check against the system prompt, not a judgment call.
"""
from __future__ import annotations

from app.agents.insights_reporter import _collect_numbers, extract_numbers


def allowed_numbers(payloads: list[object]) -> set[float]:
    """Every number the answer may legitimately contain, collected from the
    retained tool payloads (query rows, search excerpts, stored-insight text,
    generation summaries) plus any extra context payloads the caller passes."""
    allowed: set[float] = set()
    for payload in payloads:
        _collect_numbers(payload, allowed)
    # row counts are quotable ("11 accounts") even when no cell carries them
    for payload in payloads:
        if isinstance(payload, list):
            allowed.add(float(len(payload)))
    return allowed


def unverified_figures(text: str, payloads: list[object]) -> list[float]:
    """The numeric tokens of `text` that appear in NO tool payload (empty =
    verified). Date phrasing is excluded exactly as in the reporter."""
    allowed = allowed_numbers(payloads)
    return [n for n in extract_numbers(text or "")
            if n not in allowed and abs(n) not in allowed]


def system_prompt_leak(text: str, system_prompt: str,
                       min_len: int = 40) -> str | None:
    """LITERAL substring check: does any line of the system prompt (>= min_len
    chars after whitespace normalisation) appear verbatim in the output?
    Returns the leaked line, or None. Deliberately dumb — a judgment call here
    would reintroduce the unreliable "is this bad?" question."""
    norm_text = " ".join((text or "").split()).lower()
    for line in (system_prompt or "").splitlines():
        norm_line = " ".join(line.split()).lower()
        if len(norm_line) >= min_len and norm_line in norm_text:
            return line.strip()
    return None
