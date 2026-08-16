"""Round F2 task 2.4 — the ONE-TIME AI interpretation pass over CRM comments.

Reads data/vertices/phx_dm_pce_opportunity.csv, sends each non-empty comment
to the LLM (insights_miner role — Haiku, the cheap tagging tier) ONCE, and
writes ai_read / ai_read_confidence / ai_read_evidence / ai_read_model back
into the CSV. Rows already interpreted are skipped (re-running is a no-op
unless --force). Every call is turn-logged under the synthetic run id
``crm_ai_read|<batch>`` (doc_extract precedent) so the cost is in the trace.

THE RULES THAT KEEP IT HONEST (spec 2.4):
- ai_read is DESCRIPTIVE TEXT beside the row. It never drives a figure,
  filter, rule or status. Nothing in this script aggregates it.
- "No signal" is a valid and EXPECTED answer — most comments say nothing
  useful. The model is told to return no reading unless the comment clearly
  says something; an empty comment is never sent at all.
- IN-CODE GATE: a reading whose `evidence` is not an exact substring of the
  raw comment is DROPPED to no-signal and the drop is logged. A wrong reading
  must be visible, not just wrong.
- The raw comment stays verbatim in the CSV; the interpretation sits beside
  it in its own columns.
- Cap: this runs over the loaded cohort's rows only (the mock set is already
  cohort-sized). Row count and cost are printed at the end.

Run: python3 scripts/interpret_crm_comments.py [--force] [--csv PATH]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_CSV = ROOT / "data" / "vertices" / "phx_dm_pce_opportunity.csv"

PROMPT = """You are reading ONE free-text CRM opportunity comment from a financial advisor's pipeline.
If the comment clearly states something about the opportunity's status or outcome, summarise it in 2-5 words and quote the exact phrase you read it from.
If it does not clearly state anything useful, answer with an empty reading — that is the normal case and the correct answer for vague notes.
NEVER guess. NEVER infer beyond what the words say.

Comment (verbatim):
{comment}

Reply with ONLY a JSON object, no prose:
{{"ai_read": "<2-5 word reading, or empty string if no clear signal>",
  "confidence": <0.0-1.0>,
  "evidence": "<the EXACT substring of the comment the reading came from, or empty string>"}}"""


def interpret(comment: str, llm) -> dict:
    raw = llm(PROMPT.format(comment=comment), None)
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):text.rfind("}") + 1]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in reply: {raw[:120]!r}")
    obj = json.loads(text[start:end + 1])
    return {"ai_read": str(obj.get("ai_read") or "").strip(),
            "confidence": float(obj.get("confidence") or 0.0),
            "evidence": str(obj.get("evidence") or "").strip()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--force", action="store_true",
                    help="re-interpret rows that already carry a reading")
    args = ap.parse_args()

    from app.llm.roles import RoleLLM, resolve_role_config
    from app.llm.usage import TurnLoggingLLM

    cfg = resolve_role_config("insights_miner")  # the Haiku tagging tier
    batch = time.strftime("%Y%m%d%H%M%S")
    run_id = f"crm_ai_read|{batch}"
    llm = TurnLoggingLLM(RoleLLM(cfg), run_id, "crm_ai_read")

    with args.csv.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = list(reader.fieldnames or [])
        rows = list(reader)

    interpreted = skipped_empty = skipped_done = dropped_evidence = 0
    model_used = ""
    for r in rows:
        comment = (r.get("comments") or "").strip()
        if not comment:
            skipped_empty += 1  # nothing to read — never sent to the model
            continue
        if r.get("ai_read_model") and not args.force:
            skipped_done += 1  # already interpreted once — reproducible, cheap
            continue
        try:
            result = interpret(comment, llm)
        except Exception as exc:  # noqa: BLE001 — one bad row must not kill the pass
            print(f"  ! {r['opportunity_id']}: interpretation failed ({exc}) — left no-signal")
            r["ai_read"], r["ai_read_confidence"], r["ai_read_evidence"] = "", "", ""
            r["ai_read_model"] = llm._last_turn["model"] if llm._last_turn else ""
            continue
        model_used = (llm._last_turn or {}).get("model", "") or model_used
        reading, evidence = result["ai_read"], result["evidence"]
        # THE GATE (check 16): evidence must be an exact substring of the raw
        # comment, or the reading is dropped to no-signal — visibly, logged.
        if reading and (not evidence or evidence not in comment):
            print(f"  ! {r['opportunity_id']}: reading {reading!r} DROPPED — evidence "
                  f"{evidence!r} is not a substring of the comment")
            dropped_evidence += 1
            reading, evidence = "", ""
        r["ai_read"] = reading
        r["ai_read_confidence"] = f"{result['confidence']:.2f}" if reading else ""
        r["ai_read_evidence"] = evidence
        r["ai_read_model"] = model_used
        interpreted += 1

    with args.csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    dist = Counter((r.get("ai_read") or "(no signal)") for r in rows)
    print(f"\nrows total {len(rows)} · sent to model {interpreted} · empty-comment "
          f"{skipped_empty} · already-done {skipped_done} · evidence-gate drops {dropped_evidence}")
    print("reading distribution (check 15):")
    for reading, n in dist.most_common():
        print(f"  {n:3d}  {reading}")
    est = 0.0
    try:
        from app.insights.store import get_insight_store
        turns = get_insight_store().turn_log.get(run_id, [])
        est = sum(t.get("est_cost_usd", 0.0) for t in turns)
        print(f"turn log {run_id}: {len(turns)} turns, est cost ${est:.4f} (check 19)")
    except Exception as exc:  # noqa: BLE001
        print(f"turn-log readback failed: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
