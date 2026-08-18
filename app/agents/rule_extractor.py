"""B3.4 / Round E — the Rule Extractor agent.

Entrypoint (called by B2's POST /api/documents/{id}/extract-rules):

    extract_rules_for_document(document_id: str, chunks: list[dict]) -> list[dict]

Each chunk dict carries chunk_id, text, page_no, section_path, has_table.

Round E: the extractor emits PLAIN ENGLISH — a ``statement`` per provision plus
kind / grain / driver_tag / citations / confidence / ``missing``. There is no
expression grammar and NOTHING IS DISCARDED FOR FORM: if the extractor can
state it, it gets stored. The Rule Compiler (app/agents/rule_compiler.py)
turns statements into query plans later, at approval time.

``missing`` is a plain sentence naming anything the document references but
does not state (the referral-cap case). A rule with ``missing`` set is still
extracted and still shown; it just cannot be approved until the value is
supplied — status NEEDS_INPUT. A number is NEVER invented.

Output handling is fail-honest end to end: an unparseable LLM response becomes
ONE NEEDS_INPUT stub per window with the parse error attached; an invalid entry
is kept as NEEDS_INPUT with the validation error — never silently dropped.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from app.llm.roles import build_role_llm
from app.rules.compiler import GRAINS
from app.rules.store import SEVERITIES, get_rule_store
from app.shared.logging import get_logger

_log = get_logger("app.agents.rule_extractor")

WINDOW_SIZE = 6
WINDOW_OVERLAP = 1

KINDS = ("TRIGGER", "RECORD", "EXCLUDE", "WINDOW", "CAP", "CALCULATION")

_REQUIRED_KEYS = ("rule_code", "rule_name", "statement", "kind", "grain", "citations")


def build_windows(chunks: list[dict], size: int = WINDOW_SIZE,
                  overlap: int = WINDOW_OVERLAP) -> list[list[dict]]:
    """Chunk windows of `size` with `overlap` chunks of trailing overlap:
    [0:6], [5:11], [10:16] ... — a rule spanning a boundary is seen whole."""
    if not chunks:
        return []
    step = max(size - overlap, 1)
    windows = []
    start = 0
    while True:
        window = chunks[start:start + size]
        windows.append(window)
        if start + size >= len(chunks):
            break
        start += step
    return windows


def build_system_prompt() -> str:
    """Round E system prompt — plain-English extraction, nothing discarded for
    form, `missing` instead of invented numbers."""
    return (
        "You are the Rule Extractor for a wealth-management compensation engine. "
        "You read chunks of a compensation plan document and extract every "
        "governing rule as PLAIN ENGLISH. A separate Rule Compiler turns your "
        "statements into queries later — your job is to state each provision "
        "completely and faithfully, not to formalise it.\n\n"
        "Requirements:\n"
        "- Extract EVERY distinct provision that could define, qualify, cap, "
        "exclude or time-bound a revenue or compensation outcome. Exhaustiveness "
        "matters more than precision. If you can state it, it gets stored — "
        "nothing is discarded for form.\n"
        "- One rule per provision. Do not merge two provisions; do not split one. "
        "A rate table that encodes a single formula (a discount grid, a payout "
        "schedule) is ONE provision — state the formula, never one rule per row.\n"
        "- `statement` is the heart of the rule: a complete, self-contained "
        "plain-English statement of the provision with every threshold, rate, "
        "date and scope condition the document gives. Someone reading only the "
        "statement must be able to implement the rule.\n"
        "- `worked_example`: a short numeric example when the document implies "
        "one (compute it FROM the document's own figures, never invent inputs).\n"
        "- `kind` is one of TRIGGER (fires per entity when a condition holds), "
        "RECORD (records an event, e.g. a transfer), EXCLUDE (removes entities "
        "from another rule's scope), WINDOW (a time/period qualification), CAP "
        "(a maximum/limit), CALCULATION (a formula/schedule).\n"
        "- `grain` is the entity the rule applies to: one of "
        + "|".join(GRAINS) + ".\n"
        "- `applies_to`: which level the provision governs — PRACTICE (the "
        "firm), ADVISOR, PRODUCT, COMPENSATION_ENGINE (the provision is about "
        "how compensation itself is calculated — a grid, a payout formula, an "
        "engine-level adjustment — rather than about a practice, advisor or "
        "product), or ALL when it is not limited. Default ALL when unsure.\n"
        "- `missing`: if the document REFERENCES a threshold, rate, date or cap "
        "but does not STATE its value, extract the rule anyway and set `missing` "
        "to one plain sentence naming exactly what is absent. Never invent a "
        "number. If nothing is missing, use null.\n"
        "- Every rule must cite the chunk it came from: \"citations\": "
        "[{\"chunk_id\": ..., \"page_no\": ..., \"section_path\": ..., \"excerpt\": ...}].\n"
        "- `severity`: one of CRITICAL | HIGH | MODERATE | LOW | INFO, judged "
        "from the provision's OWN language — a mandatory adjustment or a floor "
        "being breached is higher than an informational note. Also emit "
        "`severity_reason`: ONE line explaining why you chose that level, so a "
        "human reviewing it can judge rather than guess.\n"
        "- Exception configuration — PROPOSE, NEVER INVENT. Some rules will be "
        "used to flag advisors as exceptions. From the provision's OWN language "
        "only, propose: `exception_denominator` (what an exception RATE should "
        "be measured against, e.g. \"managed accounts\" or \"prior-month "
        "revenue\" — null if the document implies nothing), `exception_floor` "
        "(a numeric materiality floor ONLY if the document states one — null "
        "otherwise) with `exception_floor_unit` (\"accounts\" or \"revenue\", "
        "null when floor is null), and `product_scope` (the product scope the "
        "document states, e.g. a provision limited to the standard managed fee "
        "schedule — null when the document states none). When you propose "
        "product_scope, set `product_scope_source` to a short citation of where "
        "the document states it (page/section + a few words); when the document "
        "states nothing, product_scope_source MUST be \"NOT STATED\". A null "
        "is honest; a guessed number is not.\n"
        "- Each rule object: rule_code (UPPER_SNAKE), rule_name, statement, "
        "worked_example (or null), kind, grain, driver_tag (short business label "
        "like \"Fee Rate\", \"Transfers\", \"Referrals\"), severity, "
        "severity_reason, confidence (0..1), missing (sentence or null), "
        "exception_denominator, exception_floor, exception_floor_unit, "
        "product_scope, product_scope_source, citations.\n"
        "- Return a JSON array only. No prose, no markdown fences. STRICT JSON: "
        "escape every newline inside strings. Keep each citation excerpt under "
        "160 characters."
    )


def build_window_prompt(document_id: str, window: list[dict]) -> str:
    parts = [f"Document: {document_id}", "Chunks:"]
    for chunk in window:
        parts.append(
            f"--- chunk_id={chunk.get('chunk_id')} page_no={chunk.get('page_no')} "
            f"section_path={chunk.get('section_path')!r} has_table={chunk.get('has_table')}\n"
            f"{chunk.get('text', '')}"
        )
    parts.append("Extract the rules from these chunks. Return a JSON array only.")
    return "\n".join(parts)


def parse_llm_response(raw: str) -> list | str:
    """Parse the LLM's response into a list of entries, or return the parse
    error string. A stray markdown fence is stripped (tolerant parsing, not
    guessing); anything else unparseable is the readable error."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return f"LLM output is not valid JSON: {exc} — raw output starts: {text[:200]!r}"
    if not isinstance(parsed, list):
        return f"LLM output is valid JSON but not an array (got {type(parsed).__name__})"
    return parsed


def validate_entry(entry, window_chunk_ids: set[str]) -> str | None:
    """Structural validation only — form is never a reason to reject a rule the
    extractor could state. Returns the readable error or None when usable."""
    if not isinstance(entry, dict):
        return f"entry is not an object (got {type(entry).__name__})"
    missing_keys = [k for k in ("rule_code", "statement", "citations") if not entry.get(k)]
    if missing_keys:
        return "entry is missing required field(s): " + ", ".join(missing_keys)
    citations = entry.get("citations")
    if not isinstance(citations, list) or not citations:
        return "entry has no citations — every rule must cite the chunk it came from"
    for citation in citations:
        if not isinstance(citation, dict) or not citation.get("chunk_id"):
            return "citation is missing its chunk_id"
        if window_chunk_ids and citation["chunk_id"] not in window_chunk_ids:
            return (f"citation chunk_id {citation['chunk_id']!r} is not one of the "
                    f"chunks the rule was extracted from")
        if citation.get("page_no") in (None, ""):
            return f"citation for chunk {citation['chunk_id']!r} is missing page_no"
    return None


def _needs_input_stub(document_id: str, reason: str, window_index: int,
                      window: list[dict]) -> dict:
    first = window[0] if window else {}
    return {
        "rule_code": f"UNPARSED_WINDOW_{window_index:02d}",
        "rule_name": f"Unparseable extractor output (window {window_index})",
        "statement": "The extractor's output for this chunk window could not be "
                     "used. It is kept for operator review — never dropped.",
        "worked_example": "",
        "kind": "CALCULATION",
        "grain": "account",
        "driver_tag": "Extraction",
        "severity": "INFO",
        "severity_reason": "unparseable extractor output — placeholder for review, "
                           "not a plan provision",
        "provenance": "DOCUMENT_DERIVED",
        "confidence": 0.0,
        "citations": [{"chunk_id": first.get("chunk_id", ""),
                       "page_no": first.get("page_no"),
                       "section_path": first.get("section_path", ""),
                       "excerpt": (first.get("text", "") or "")[:200]}],
        "status": "NEEDS_INPUT",
        "missing": reason,
        "unclear_notes": reason,
        "document_id": document_id,
    }


def _resolve_llm(document_id: str) -> Callable[[str, dict], str]:
    """The rule_extractor role's client, wrapped so every window call is
    turn-logged under the synthetic run id ``doc_extract|<document_id>``."""
    from app.llm.usage import wrap_llm

    client = build_role_llm("rule_extractor")
    if client is None:
        from app.llm.client import get_llm_client

        client = get_llm_client()
    return wrap_llm(client, f"doc_extract|{document_id}", "rule_extractor")


def extract_rules_for_document(document_id: str, chunks: list[dict],
                               llm: Callable[[str, dict], str] | None = None,
                               persist: bool = True,
                               start_window: int = 0,
                               known_codes: set[str] | None = None,
                               on_window: Callable[[int, int], None] | None = None) -> list[dict]:
    """Extract draft rules from one document's chunks. `llm` overrides the
    transport for deterministic tests; `persist=True` stores results in the
    rule store's draft pool. Rules with `missing` set land as NEEDS_INPUT;
    everything else is DRAFT awaiting the Rule Compiler.

    Round 1 (schema freeze): each window's rules persist AS THE WINDOW
    COMPLETES (not at the end), so an interruption loses at most one window.
    `start_window` resumes at that window (earlier windows' rules are already
    stored — never repeated); `known_codes` seeds the duplicate filter with
    codes persisted by a prior pass; `on_window(done, total)` is called after
    each window persists — the JobStore's per-item progress hook."""
    generate = llm or _resolve_llm(document_id)
    system_prompt = build_system_prompt()
    windows = build_windows(chunks)
    _log.info("extracting rules for %s: %d chunks in %d window(s), from window %d",
              document_id, len(chunks), len(windows), start_window)

    store = get_rule_store() if persist else None
    extracted: list[dict] = []
    seen_codes: set[str] = set(known_codes or ())
    for index, window in enumerate(windows):
        if index < start_window:
            continue
        window_ids = {c.get("chunk_id") for c in window}
        prompt = build_window_prompt(document_id, window)
        window_rules: list[dict] = []
        entries: list | None = None
        try:
            raw = generate(prompt, {"system_prompt": system_prompt})
            tag = getattr(generate, "tag_last", None)
            if callable(tag):
                tag("extract_window", f"window_{index:02d}")
            parsed = parse_llm_response(raw)
            if isinstance(parsed, str):
                window_rules.append(_needs_input_stub(document_id, parsed, index, window))
            else:
                entries = parsed
        except Exception as exc:  # noqa: BLE001 — honest failure per window
            window_rules.append(_needs_input_stub(
                document_id, f"LLM call failed: {type(exc).__name__}: {exc}", index, window))
        for entry in entries or []:
            error = validate_entry(entry, window_ids)
            if error is not None:
                stub = _needs_input_stub(document_id, f"invalid extractor entry: {error}",
                                         index, window)
                if isinstance(entry, dict) and entry.get("rule_code"):
                    stub["rule_code"] = str(entry["rule_code"])
                    stub["rule_name"] = str(entry.get("rule_name") or stub["rule_name"])
                window_rules.append(stub)
                continue
            rule = dict(entry)
            # lenient coercion — never a reason to drop a stated rule
            rule["grain"] = str(rule.get("grain") or "account").lower()
            if rule["grain"] not in GRAINS:
                rule["grain"] = "account"
            kind = str(rule.get("kind") or "").upper()
            rule["kind"] = kind if kind in KINDS else "CALCULATION"
            rule.setdefault("rule_name", rule["rule_code"].replace("_", " ").title())
            rule.setdefault("driver_tag", "Other")
            # Round 5 Part C: applies_to proposal — lenient coercion against
            # the store's closed set; absent/invalid lands at ALL, never drops
            applies = str(rule.get("applies_to") or "").upper().replace(" ", "_")
            from app.rules.store import APPLIES_TO as _APPLIES_TO
            rule["applies_to"] = applies if applies in _APPLIES_TO else "ALL"
            # Round A1 task 2: severity is extractor-assigned; an absent or
            # invalid level lands honestly at INFO with a reason saying so —
            # never silently promoted.
            severity = str(rule.get("severity") or "").upper()
            if severity in SEVERITIES:
                rule["severity"] = severity
                rule["severity_reason"] = (str(rule.get("severity_reason") or "").strip()
                                           or "extractor assigned no reason")
            else:
                rule["severity"] = "INFO"
                rule["severity_reason"] = (
                    "extractor did not assign a valid severity — defaulted to INFO"
                    + (f" (got {rule.get('severity')!r})" if rule.get("severity") else ""))
            # Round 1 (schema freeze): exception-configuration PROPOSALS from
            # the provision's own language — lenient coercion, null when not
            # stated, never a reason to drop the rule. product_scope_source is
            # the citation, or "NOT STATED" (a null is honest, a guessed
            # number is not).
            denom = rule.get("exception_denominator")
            rule["exception_denominator"] = (str(denom).strip() or None) if denom else None
            try:
                floor = rule.get("exception_floor")
                rule["exception_floor"] = float(floor) if floor not in (None, "") else None
            except (TypeError, ValueError):
                rule["exception_floor"] = None
            unit = str(rule.get("exception_floor_unit") or "").strip().lower()
            rule["exception_floor_unit"] = (
                unit if unit in ("accounts", "revenue")
                and rule["exception_floor"] is not None else None)
            scope = rule.get("product_scope")
            rule["product_scope"] = (str(scope).strip() or "") if scope else ""
            source = str(rule.get("product_scope_source") or "").strip()
            rule["product_scope_source"] = (
                source if rule["product_scope"] and source
                and source.upper() != "NOT STATED" else "NOT STATED")
            rule["provenance"] = "DOCUMENT_DERIVED"
            rule["document_id"] = document_id
            rule.setdefault("worked_example", None)
            missing = rule.get("missing")
            rule["missing"] = str(missing).strip() if missing else None
            rule["unclear_notes"] = rule["missing"]
            rule["status"] = "NEEDS_INPUT" if rule["missing"] else "DRAFT"
            if rule["rule_code"] in seen_codes:  # overlap window duplicate
                continue
            seen_codes.add(rule["rule_code"])
            window_rules.append(rule)

        # Round 1: this window's output is WRITTEN before the next window
        # begins — an interruption loses at most the in-flight window, and a
        # resume at start_window=N never repeats windows 0..N-1.
        if store is not None:
            window_rules = [store.add_rule(rule, version_id=None)
                            for rule in window_rules]
        extracted.extend(window_rules)
        if on_window is not None:
            on_window(index + 1, len(windows))

    return extracted


def extract_with_job(document_id: str, chunks: list[dict],
                     llm: Callable[[str, dict], str] | None = None,
                     resume: bool = False) -> dict:
    """Round 1 (schema freeze) task 2 — extraction under a phx_dm_pce_job.

    Reopens the document's ingest job (or creates one) at stage ``extract``
    with per-window item progress; ``resume_token = {"next_window": N}`` after
    every completed window. An interruption (the process dying, a
    KeyboardInterrupt — anything that escapes the extractor's own per-window
    error handling) marks the job INTERRUPTED; calling again with
    ``resume=True`` restarts at the recorded window WITHOUT repeating earlier
    ones (their rules are already persisted; the duplicate filter is seeded
    from the draft pool). Resume is explicit — never automatic.

    Returns {"job": job_dict, "rules": rules_from_this_pass}.
    """
    from app.rules.store import get_rule_store as _rules
    from app.shared.jobs import get_job_store

    jobs = get_job_store()
    job = jobs.latest_for("document_ingest", document_id)
    start_window = 0
    if resume:
        if job is None or job.get("status") != "INTERRUPTED":
            raise ValueError(
                f"nothing to resume for {document_id}: "
                + ("no job exists" if job is None
                   else f"latest job is {job['status']}, not INTERRUPTED"))
        token = job.get("resume_token") or {}
        if isinstance(token, str):
            token = json.loads(token or "{}")
        start_window = int(token.get("next_window") or 0)
    if job is None:
        job = jobs.begin_job("document_ingest", document_id)
    total = len(build_windows(chunks))
    job = jobs.update(job["job_id"], stage="extract",
                      items_done=start_window, items_total=total,
                      resume_token={"next_window": start_window})

    def _on_window(done: int, total_windows: int) -> None:
        jobs.update(job["job_id"], items_done=done, items_total=total_windows,
                    resume_token={"next_window": done})

    known = {r.get("rule_code") for r in _rules().drafts()
             if r.get("document_id") == document_id} if start_window else None
    try:
        rules = extract_rules_for_document(
            document_id, chunks, llm=llm, persist=True,
            start_window=start_window, known_codes=known, on_window=_on_window)
    except BaseException as exc:  # noqa: BLE001 — incl. KeyboardInterrupt/kill paths
        current = jobs.get(job["job_id"]) or job
        jobs.interrupt(job["job_id"], resume_token=current.get("resume_token"),
                       error=f"extraction interrupted: {type(exc).__name__}: {exc}")
        raise
    finished = jobs.complete(job["job_id"])
    return {"job": finished, "rules": rules}
