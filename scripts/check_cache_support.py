"""Round H task 3.2 — does the CONFIGURED provider actually cache prompts?

Sends the SAME >=5,000-token stable prefix twice through whichever adapter
LLM_MODE selects and reports whatever the provider returns for cached tokens —
straight from response.usage (Anthropic: cache_creation/cache_read counts;
OpenAI shape: prompt_tokens_details.cached_tokens). Nothing is estimated; if
the provider reports no cache metrics, the script says so honestly.

Three possible outcomes on the client's cdao path, all worth knowing:
  - automatic prefix caching engages  → ~50% input saving, structure correct
  - it does not                       → cost per run ~doubles vs measured;
                                        set ASSUME_PROMPT_CACHING=false so the
                                        Generate-button projection is honest
  - the SDK rejects something         → a bug found here, not at demo time

Mock mode runs free and deterministically (the mock adapter has no
conversation path and reports no usage — the script reports exactly that).
Claude / real / cdao modes make TWO small real calls and COST REAL MONEY
(Haiku: ~$0.02-0.04 total; the second call should be mostly cache reads).

Usage: python3 scripts/check_cache_support.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
os.chdir(APP_ROOT)

# The prefix must clear every provider's minimum cacheable size (Haiku: 4096
# tokens; OpenAI automatic caching: 1024). Deterministic numbered filler at
# ~3.2 chars/token (the ratio measured for this repo's prompt mix) sized to
# >=5,000 tokens with margin.
PREFIX_TOKEN_TARGET = 5_000
CHARS_PER_TOKEN = 3.2


def build_stable_prefix() -> str:
    line = ("ledger row {i:06d}: advisor V{i:06d} credited 1234.56 in 202604, "
            "fee schedule 145 bps, household H{i:06d}, product MFD. ")
    text = ("CACHE SUPPORT PROBE — static reference context, byte-identical "
            "across both calls.\n")
    i = 0
    target_chars = int(PREFIX_TOKEN_TARGET * CHARS_PER_TOKEN * 1.5)  # 1.5x margin
    while len(text) < target_chars:
        text += line.format(i=i)
        i += 1
    return text


def usage_line(label: str, usage: dict | None) -> str:
    if not usage or not any(usage.values()):
        return f"{label}: provider reports no cache metrics (no usage returned)"
    return (f"{label}: input={usage['input_tokens']:,} "
            f"output={usage['output_tokens']:,} "
            f"cache_read={usage['cache_read_tokens']:,} "
            f"cache_write={usage['cache_write_tokens']:,}")


def main() -> int:
    from app.agents.insights_miner import estimate_tokens
    from app.config.settings import get_settings
    from app.llm.client import get_llm_client

    mode = (get_settings().llm_client_mode or "mock").lower()
    client = get_llm_client()
    prefix = build_stable_prefix()
    est = estimate_tokens(prefix)
    print(f"adapter: {client.describe()}")
    print(f"stable prefix: ~{est:,} tokens ({len(prefix):,} chars), "
          f"sent twice, byte-identical")

    system_blocks = [{"type": "text", "text": prefix, "stable": True}]
    question = ("Reply with exactly the single word OK and nothing else.")
    messages = [{"role": "user",
                 "content": [{"type": "text", "text": question}]}]

    if not hasattr(client, "generate_conversation"):
        # mock (and any single-string transport): deterministic, zero cost.
        for n in (1, 2):
            start = time.perf_counter()
            text = client.generate(prefix + "\n\n" + question)
            ms = (time.perf_counter() - start) * 1000
            print(f"call {n}: {ms:.0f}ms, reply {text[:60]!r}...")
            print(usage_line(f"call {n} usage", None))
        print("VERDICT: this adapter has no conversation path and reports no "
              "usage — cache support is UNMEASURABLE here. Run with the real "
              "provider configured (LLM_MODE=cdao in the client environment) "
              "for a definitive answer.")
        return 0

    results = []
    for n in (1, 2):
        start = time.perf_counter()
        result = client.generate_conversation(system_blocks, messages)
        ms = (time.perf_counter() - start) * 1000
        results.append(result)
        print(f"call {n}: {ms:.0f}ms, model={result.get('model')}, "
              f"reply {str(result.get('text', ''))[:40]!r}")
        print(usage_line(f"call {n} usage", result.get("usage")))

    u1, u2 = (r.get("usage") or {} for r in results)
    if not any(u2.values()):
        print("VERDICT: provider reports no cache metrics — cannot confirm or "
              "deny caching from this response shape. Assume NO caching for "
              "budgeting (ASSUME_PROMPT_CACHING=false) until proven otherwise.")
        return 0
    read2 = int(u2.get("cache_read_tokens") or 0)
    if read2 > 0:
        pct = round(100 * read2 / max(1, (u2["input_tokens"] + read2
                                          + u2["cache_write_tokens"])), 1)
        print(f"VERDICT: prompt caching ENGAGES — call 2 read {read2:,} cached "
              f"tokens ({pct}% of its prompt). Keep ASSUME_PROMPT_CACHING=true.")
    else:
        print("VERDICT: prompt caching DID NOT ENGAGE — call 2 re-billed the "
              "full prefix (0 cached tokens). Set ASSUME_PROMPT_CACHING=false; "
              "expect roughly double the measured input cost per run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
