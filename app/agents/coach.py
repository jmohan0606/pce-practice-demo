"""Round A2B 6.7 — the Coach agent.

Level 2 ONLY: a coaching point is a retrieved GUIDANCE fact plus its
implication for THIS advisor's deterministic numbers — never invented advice.

Flow (one generation):
1. Deterministic Chroma searches over GUIDANCE-category documents (the
   reporter_sources pattern), excerpts labelled D1..Dn with full citations.
2. ONE LLM call (role "coach" — Haiku by default, its own COACH_* config and
   COACH_MAX_INPUT_TOKENS budget) asked for strict JSON points, each naming
   the excerpt it rests on.
3. The in-code gate (the verify_recommendations precedent): a point whose
   excerpt reference does not resolve to a fetched citation is DROPPED and the
   drop logged; an ``assert`` backs the gate — nothing citation-less leaves.

Every LLM call is logged to phx_dm_pce_agent_turn_log via TurnLoggingLLM with
the synthetic run id ``coach|<advisor_sid>|<from>|<to>`` (precedent:
doc_extract|<id>). Results persist durably (CoachStore, SQLite under
data/runtime/) and GET serves the stored result without regeneration.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone

from app.shared.logging import get_logger
from app.shared.sqlite_persistence import SqliteJsonDb, runtime_db_path

_log = get_logger("app.agents.coach")

AGENT_NAME = "coach"

# The four guidance topics the sample document (and real practice-management
# guidance) covers — fixed, deterministic searches, never model-chosen.
SEARCH_TOPICS = (
    "discount discipline fee reduction below standard schedule",
    "household consolidation accounts below threshold",
    "book diversification product concentration",
    "referral follow-up opportunity pipeline",
)


def coach_run_id(advisor_sid: str, from_month: str, to_month: str) -> str:
    return f"coach|{advisor_sid}|{from_month}|{to_month}"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------- search

def build_guidance_search(run_id: str):
    """``search_guidance(query, top_k)`` over GUIDANCE documents only —
    the reporter_sources.build_reporter_search idiom, logged as the coach."""
    from app.insights.store import get_insight_store

    store = get_insight_store()

    def search_guidance(query: str, top_k: int = 3) -> list[dict]:
        from app.knowledge.knowledge_service import KnowledgeManagementService
        from app.knowledge.rag_service import RagGenerationService

        start = time.perf_counter()
        doc_types = {d["document_id"]: str(d.get("document_type") or "").upper()
                     for d in KnowledgeManagementService().list_documents()}
        hits = RagGenerationService().retrieve(str(query or ""),
                                               top_k=max(int(top_k) * 3, 6))
        rows = []
        for s in hits:
            if doc_types.get(s.get("document_id"), "PLAN") != "GUIDANCE":
                continue
            rows.append({
                "document_id": s.get("document_id"),
                "document_name": s.get("document_name"),
                "document_type": "GUIDANCE",
                "chunk_id": s.get("chunk_id"),
                "page_no": s.get("page_no"),
                "section_path": s.get("section_path"),
                "excerpt": (s.get("excerpt") or "")[:600],
                "similarity": s.get("similarity"),
            })
            if len(rows) >= int(top_k):
                break
        store.log_query(run_id, AGENT_NAME, "search_documents",
                        {"query": str(query or ""), "source": "GUIDANCE",
                         "top_k": int(top_k)},
                        len(rows), (time.perf_counter() - start) * 1000)
        return rows

    return search_guidance


# ----------------------------------------------------------------------- gate

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _fact_text(facts: dict) -> str:
    return json.dumps(facts, default=str)


def verify_coaching_points(raw_points: list, excerpts: dict[str, dict],
                           facts: dict) -> tuple[list[dict], list[dict]]:
    """The in-code gate. A point is KEPT only when:
    - its excerpt_ref resolves to a fetched GUIDANCE citation, and
    - every number in its text appears in the deterministic facts or the
      cited excerpt (nothing computed by the model survives).
    Everything else is DROPPED with the reason logged."""
    corpus_numbers_base = _fact_text(facts)
    kept: list[dict] = []
    dropped: list[dict] = []
    for point in raw_points or []:
        if not isinstance(point, dict):
            dropped.append({"point": str(point), "reason": "not an object"})
            continue
        ref = str(point.get("excerpt_ref") or "").strip()
        citation = excerpts.get(ref)
        text = " ".join(str(point.get(k) or "") for k in ("fact", "implication"))
        if citation is None:
            dropped.append({"point": text,
                            "reason": f"no resolvable document citation "
                                      f"(excerpt_ref={ref!r})"})
            continue
        corpus = corpus_numbers_base + " " + str(citation.get("excerpt") or "")
        bad = [n for n in _NUM.findall(text)
               if n not in corpus and n.replace(",", "") not in corpus]
        if bad:
            dropped.append({"point": text,
                            "reason": f"figures {bad} not present in the "
                                      f"facts or the cited excerpt"})
            continue
        kept.append({
            "text": text.strip(),
            "fact": str(point.get("fact") or "").strip(),
            "implication": str(point.get("implication") or "").strip(),
            "citation": {k: citation.get(k) for k in
                         ("document_id", "document_name", "chunk_id",
                          "page_no", "section_path", "excerpt")},
            "facts": facts,
        })
    # the gate's backing assertion — nothing citation-less leaves this function
    assert all(p.get("citation", {}).get("document_name") for p in kept), \
        "coaching gate breach: a kept point has no resolvable citation"
    return kept, dropped


# ------------------------------------------------------------------ generation

_PROMPT = """You are a practice-management coach. You may ONLY restate facts and draw their implications — never invent advice, thresholds or numbers.

Deterministic facts about advisor {advisor_sid} (transition {from_month} -> {to_month}):
{facts_json}

Guidance excerpts from the practice's GUIDANCE documents (the ONLY allowed sources):
{excerpts_block}

Write up to {max_points} coaching points as a STRICT JSON array, nothing else. Each element:
{{"excerpt_ref": "D1", "fact": "<one sentence restating a fact above AND what the cited excerpt says>", "implication": "<one sentence: what that means for this advisor>"}}

Rules:
- excerpt_ref MUST be one of the D-labels above; a point without one is discarded.
- Use ONLY numbers that appear verbatim in the facts or the cited excerpt.
- If no excerpt is relevant to the facts, return [].
"""


def generate_coaching(advisor_sid: str, from_month: str, to_month: str,
                      facts: dict) -> dict:
    """One coach generation. Deterministic searches, one budgeted LLM call,
    gated output, durable store write. Returns the stored result dict."""
    from app.config.settings import get_settings
    from app.llm.usage import wrap_llm

    settings = get_settings()
    run_id = coach_run_id(advisor_sid, from_month, to_month)
    search = build_guidance_search(run_id)

    excerpts: dict[str, dict] = {}
    for topic in SEARCH_TOPICS[:max(int(settings.coach_max_searches), 1)]:
        for row in search(topic, top_k=2):
            if any(row.get("chunk_id") == e.get("chunk_id") for e in excerpts.values()):
                continue
            excerpts[f"D{len(excerpts) + 1}"] = row

    limits: list[dict] = []
    result: dict = {
        "advisor_sid": advisor_sid, "from_month": from_month,
        "to_month": to_month, "run_id": run_id, "generated_at": _now(),
        "points": [], "dropped": [], "searches": len(SEARCH_TOPICS),
        "excerpt_count": len(excerpts), "limits": limits,
        "opportunities_guidance": None, "note": None,
    }

    # deterministic retrieval for the opportunities section — no LLM involved
    opp = excerpts and next(
        (e for e in excerpts.values()
         if "referral" in str(e.get("excerpt") or "").lower()
         or "referral" in str(e.get("section_path") or "").lower()), None)
    if opp:
        result["opportunities_guidance"] = opp

    if not excerpts:
        # honest empty state: no GUIDANCE material -> no coaching points, ever
        result["note"] = ("No GUIDANCE documents matched — coaching points "
                          "require a citable guidance source and none exists.")
        get_coach_store().save(result)
        return result

    excerpts_block = "\n".join(
        f'[{label}] {e["document_name"]} p.{e.get("page_no")} '
        f'{e.get("section_path") or ""}: "{e["excerpt"]}"'
        for label, e in excerpts.items())
    prompt = _PROMPT.format(
        advisor_sid=advisor_sid, from_month=from_month, to_month=to_month,
        facts_json=json.dumps(facts, indent=1, default=str),
        excerpts_block=excerpts_block, max_points=4)

    # the Coach's own token budget: enforced BEFORE the call on a chars≈4/token
    # basis (the only pre-call estimator we have), recorded when it binds
    char_cap = settings.coach_max_input_tokens * 4
    if len(prompt) > char_cap:
        prompt = prompt[:char_cap]
        limits.append({"limit_name": "COACH_MAX_INPUT_TOKENS",
                       "limit_value": settings.coach_max_input_tokens,
                       "limit_effect": "The coaching prompt was truncated to fit "
                                       "the coach's input-token budget."})

    from app.insights.service import _resolve_llm_client

    llm = wrap_llm(_resolve_llm_client("coach"), run_id, AGENT_NAME)
    try:
        text = llm(prompt, None)
        llm.tag_last("coach_points", "generate_coaching")
    except Exception as exc:  # noqa: BLE001 — honest failure, nothing invented
        result["note"] = f"coach LLM unavailable: {exc}"
        get_coach_store().save(result)
        return result

    match = re.search(r"\[.*\]", text, re.DOTALL)
    try:
        raw_points = json.loads(match.group(0)) if match else []
    except ValueError:
        raw_points = []
        result["note"] = "coach output was not parseable JSON — no points kept"

    kept, dropped = verify_coaching_points(raw_points, excerpts, facts)
    for d in dropped:
        _log.info("coach point DROPPED for %s: %s", run_id, d["reason"])
    result["points"] = kept
    result["dropped"] = dropped
    if llm.prompt_tokens_total > settings.coach_max_input_tokens:
        limits.append({"limit_name": "COACH_MAX_INPUT_TOKENS",
                       "limit_value": settings.coach_max_input_tokens,
                       "limit_effect": "The generation consumed more prompt "
                                       "tokens than the coach budget."})
    get_coach_store().save(result)
    return result


# -------------------------------------------------------------------- storage

_DDL = (
    """CREATE TABLE IF NOT EXISTS coaching (
        run_key TEXT PRIMARY KEY,
        result_json TEXT NOT NULL,
        persisted_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
)


class CoachStore:
    """Durable coaching results — stored results are served on GET without
    regeneration; regeneration overwrites the row (latest wins)."""

    def __init__(self, db_path=None) -> None:
        self.db = SqliteJsonDb(
            db_path or runtime_db_path("PCE_COACH_DB_PATH", "coaching.db"), _DDL)

    def save(self, result: dict) -> None:
        key = coach_run_id(result["advisor_sid"], result["from_month"],
                           result["to_month"])
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO coaching (run_key, result_json) VALUES (?, ?) "
                "ON CONFLICT(run_key) DO UPDATE SET result_json = excluded.result_json, "
                "persisted_at = datetime('now')",
                (key, json.dumps(result, default=str)))

    def get(self, advisor_sid: str, from_month: str, to_month: str) -> dict | None:
        key = coach_run_id(advisor_sid, from_month, to_month)
        rows = self.db.query("SELECT result_json FROM coaching WHERE run_key = ?",
                             (key,))
        return json.loads(rows[0]["result_json"]) if rows else None


_store: CoachStore | None = None
_store_lock = threading.Lock()


def get_coach_store() -> CoachStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = CoachStore()
        return _store
