"""Turn logging for every LLM call the app makes.

``TurnLoggingLLM`` wraps an adapter (ClaudeLLMClient / RoleLLM / any object
with ``generate``) or a bare ``fn(prompt, context) -> str`` callable and logs
one ``phx_dm_pce_agent_turn_log`` row per call through the insight store —
token counts from the provider's ``response.usage`` (zeros when the transport
reports none; never estimated), latency, model, and an estimated USD cost.

The wrapper is itself callable with the ``fn(prompt, context) -> str``
signature every agent already uses, so it drops in anywhere a plain LLM
callable is expected. Callers that know what the turn was for tag it after the
fact with ``tag_last(action_kind, query_name)``.

``prompt_tokens_total`` accumulates input + cache-read + cache-write tokens —
the figure the MAX_RUN_INPUT_TOKENS hard budget is enforced against.
"""
from __future__ import annotations

import time

from app.shared.logging import get_logger

_log = get_logger("app.llm.usage")

ZERO_USAGE = {"input_tokens": 0, "output_tokens": 0,
              "cache_read_tokens": 0, "cache_write_tokens": 0}


class TurnLoggingLLM:
    def __init__(self, inner, run_id: str, agent_name: str) -> None:
        self.inner = inner
        self.run_id = run_id
        self.agent_name = agent_name
        self.prompt_tokens_total = 0
        self.output_tokens_total = 0
        self._last_turn: dict | None = None

    def _store(self):
        from app.insights.store import get_insight_store

        return get_insight_store()

    def _call_inner(self, prompt: str, context: dict | None) -> dict:
        if hasattr(self.inner, "generate_with_usage"):
            return self.inner.generate_with_usage(prompt, context)
        if hasattr(self.inner, "generate"):
            text = self.inner.generate(prompt, context)
            model = ""
            if hasattr(self.inner, "describe"):
                model = (self.inner.describe() or {}).get("model", "")
            return {"text": text, "usage": dict(ZERO_USAGE), "model": model}
        return {"text": self.inner(prompt, context), "usage": dict(ZERO_USAGE),
                "model": ""}

    def _record(self, result: dict, latency_ms: float,
                action_kind: str = "", query_name: str = "") -> None:
        usage = result.get("usage") or dict(ZERO_USAGE)
        self.prompt_tokens_total += (usage["input_tokens"] + usage["cache_read_tokens"]
                                     + usage["cache_write_tokens"])
        self.output_tokens_total += usage["output_tokens"]
        try:
            self._last_turn = self._store().log_turn(
                self.run_id, self.agent_name, result.get("model") or "", usage,
                latency_ms, action_kind=action_kind, query_name=query_name)
        except Exception as exc:  # noqa: BLE001 — logging must never break a run
            _log.error("turn log for %s failed: %s", self.run_id, exc)
            self._last_turn = None

    def __call__(self, prompt: str, context: dict | None = None) -> str:
        start = time.perf_counter()
        result = self._call_inner(prompt, context)
        self._record(result, (time.perf_counter() - start) * 1000)
        return result["text"]

    # generate() alias so the wrapper also satisfies the LLMClient duck type
    generate = __call__

    @property
    def supports_conversation(self) -> bool:
        return bool(getattr(self.inner, "supports_conversation", False)) \
            and hasattr(self.inner, "generate_conversation")

    def converse(self, system_blocks: list[dict], messages: list[dict]) -> str:
        """Messages-array path (stable-flag aware via the adapter) — logged
        like every turn."""
        start = time.perf_counter()
        result = self.inner.generate_conversation(system_blocks, messages)
        self._record(result, (time.perf_counter() - start) * 1000)
        return result["text"]

    def tag_last(self, action_kind: str, query_name: str = "") -> None:
        """Callers annotate the just-logged turn once they know what it did."""
        if self._last_turn is not None:
            try:
                self._store().tag_turn(self.run_id, self._last_turn["seq_no"],
                                       action_kind, query_name)
            except Exception as exc:  # noqa: BLE001
                _log.error("turn tag for %s failed: %s", self.run_id, exc)


def wrap_llm(inner, run_id: str, agent_name: str) -> TurnLoggingLLM:
    return TurnLoggingLLM(inner, run_id, agent_name)
