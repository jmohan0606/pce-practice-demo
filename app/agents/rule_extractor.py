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
from app.rules.store import get_rule_store
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
        "- `missing`: if the document REFERENCES a threshold, rate, date or cap "
        "but does not STATE its value, extract the rule anyway and set `missing` "
        "to one plain sentence naming exactly what is absent. Never invent a "
        "number. If nothing is missing, use null.\n"
        "- Every rule must cite the chunk it came from: \"citations\": "
        "[{\"chunk_id\": ..., \"page_no\": ..., \"section_path\": ..., \"excerpt\": ...}].\n"
        "- Each rule object: rule_code (UPPER_SNAKE), rule_name, statement, "
        "worked_example (or null), kind, grain, driver_tag (short business label "
        "like \"Fee Rate\", \"Transfers\", \"Referrals\"), confidence (0..1), "
        "missing (sentence or null), citations.\n"
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
                               persist: bool = True) -> list[dict]:
    """Extract draft rules from one document's chunks. `llm` overrides the
    transport for deterministic tests; `persist=True` stores results in the
    rule store's draft pool. Rules with `missing` set land as NEEDS_INPUT;
    everything else is DRAFT awaiting the Rule Compiler."""
    generate = llm or _resolve_llm(document_id)
    system_prompt = build_system_prompt()
    windows = build_windows(chunks)
    _log.info("extracting rules for %s: %d chunks in %d window(s)",
              document_id, len(chunks), len(windows))

    extracted: list[dict] = []
    seen_codes: set[str] = set()
    for index, window in enumerate(windows):
        window_ids = {c.get("chunk_id") for c in window}
        prompt = build_window_prompt(document_id, window)
        try:
            raw = generate(prompt, {"system_prompt": system_prompt})
            tag = getattr(generate, "tag_last", None)
            if callable(tag):
                tag("extract_window", f"window_{index:02d}")
        except Exception as exc:  # noqa: BLE001 — honest failure per window
            extracted.append(_needs_input_stub(
                document_id, f"LLM call failed: {type(exc).__name__}: {exc}", index, window))
            continue
        entries = parse_llm_response(raw)
        if isinstance(entries, str):
            extracted.append(_needs_input_stub(document_id, entries, index, window))
            continue
        for entry in entries:
            error = validate_entry(entry, window_ids)
            if error is not None:
                stub = _needs_input_stub(document_id, f"invalid extractor entry: {error}",
                                         index, window)
                if isinstance(entry, dict) and entry.get("rule_code"):
                    stub["rule_code"] = str(entry["rule_code"])
                    stub["rule_name"] = str(entry.get("rule_name") or stub["rule_name"])
                extracted.append(stub)
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
            extracted.append(rule)

    if persist:
        store = get_rule_store()
        extracted = [store.add_rule(rule, version_id=None) for rule in extracted]
    return extracted
