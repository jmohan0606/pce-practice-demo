"""B3.4 — the Rule Extractor agent.

Entrypoint (called by B2's POST /api/documents/{id}/extract-rules):

    extract_rules_for_document(document_id: str, chunks: list[dict]) -> list[dict]

Each chunk dict carries chunk_id, text, page_no, section_path, has_table.

Runs per document, in batch — never per request. Chunks are processed in
windows of 6 with 1 chunk of overlap so a rule spanning a boundary is still
seen whole. The system prompt inlines the narrow grammar and the schema field
list; a threshold/rate/date that is referenced but not stated becomes
status=NEEDS_INPUT with unclear_notes — a number is NEVER invented.

Output handling is fail-honest end to end:
- an unparseable LLM response (not a JSON array) becomes ONE NEEDS_INPUT rule
  per window with the parse error attached — never silently dropped;
- an invalid entry (bad shape, missing citation, unknown grain) is kept as
  NEEDS_INPUT with the validation error;
- a syntactically valid entry that fails to COMPILE is kept as NEEDS_INPUT
  carrying the compile error (B3.8: every draft either compiles or carries a
  readable reason).

Extracted drafts are stored in the rule store's draft pool (mirrored to the
graph) and returned as dicts.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from app.llm.roles import build_role_llm
from app.rules.compiler import GRAINS, compile_status, fields_for_grain
from app.rules.grammar import GRAMMAR_TEXT
from app.rules.store import get_rule_store
from app.shared.logging import get_logger

_log = get_logger("app.agents.rule_extractor")

WINDOW_SIZE = 6
WINDOW_OVERLAP = 1

_REQUIRED_KEYS = ("rule_code", "rule_name", "plain_description", "grain",
                  "population", "compute", "trigger", "citations")


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


def _field_list_text() -> str:
    lines = []
    for grain in GRAINS:
        per_vertex = fields_for_grain(grain)
        if not per_vertex:
            continue
        names = sorted({f for attrs in per_vertex.values() for f in attrs})
        lines.append(f"grain '{grain}': " + ", ".join(names))
    return "\n".join(lines)


def build_system_prompt() -> str:
    """The B3.4 system prompt — every requirement stated, grammar and field
    list inlined."""
    return (
        "You are the Rule Extractor for a wealth-management compensation engine. "
        "You read chunks of a compensation plan document and extract governing rules.\n\n"
        "Requirements:\n"
        "- Extract EVERY distinct provision that could define, qualify, cap, exclude "
        "or time-bound a revenue or compensation outcome. Exhaustiveness matters more "
        "than precision.\n"
        "- One rule per provision. Do not merge two provisions; do not split one. A "
        "rate table that encodes a single formula (e.g. a discount grid, a payout "
        "schedule) is ONE provision — extract the formula, never one rule per row.\n"
        "- population, compute and trigger are REQUIRED on every rule and must use "
        "the narrow grammar with fields from the list below. Express qualitative "
        "provisions the same way (e.g. compute count(*), trigger value > 0 over the "
        "defined population). Example, a fee-discount sharing provision:\n"
        '  {"rule_code": "FEE_REDUCTION_SHARING", "grain": "account",\n'
        '   "population": "is_managed = true AND month_id = :month",\n'
        '   "compute": "round((standard_rate_bps - client_rate_bps) / standard_rate_bps * 100)",\n'
        '   "trigger": "value > 10", "attribute": "grid_points = min(value - 10, 10)", ...}\n'
        "- Use only these expression forms:\n"
        + GRAMMAR_TEXT + "\n\n"
        "- Field names must come from this list (per grain):\n"
        + _field_list_text() + "\n\n"
        "- If a threshold, rate or date is referenced but not stated, set "
        "\"status\": \"NEEDS_INPUT\" and put what is missing in \"unclear_notes\". "
        "Never invent a number.\n"
        "- Every rule must cite the chunk it came from: \"citations\": "
        "[{\"chunk_id\": ..., \"page_no\": ..., \"section_path\": ..., \"excerpt\": ...}].\n"
        "- Each rule object needs: rule_code (UPPER_SNAKE), rule_name, "
        "plain_description, worked_example, grain (one of "
        + "|".join(GRAINS) + "), population, compute, trigger, attribute (or null), "
        "driver_tag, confidence (0..1), status (DRAFT or NEEDS_INPUT), unclear_notes "
        "(or null), citations.\n"
        "- If a provision needs data the field list does not carry (a date, rate or "
        "flag that does not exist), still fill population/compute/trigger as far as "
        "the fields allow, set status NEEDS_INPUT and name the missing piece in "
        "unclear_notes.\n"
        "- Return a JSON array only. No prose, no markdown fences. STRICT JSON: "
        "escape every newline inside strings. Keep each citation excerpt under 160 "
        "characters."
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
    # strip markdown fences even when the CLOSING fence is missing (a truncated
    # response must fail on its truncated JSON, with that readable error — not
    # on the cosmetic fence)
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
    """Structural validation of one extracted entry. Returns the readable error
    or None when valid."""
    if not isinstance(entry, dict):
        return f"entry is not an object (got {type(entry).__name__})"
    missing = [k for k in _REQUIRED_KEYS if not entry.get(k)]
    if missing:
        return "entry is missing required field(s): " + ", ".join(missing)
    if str(entry.get("grain", "")).lower() not in GRAINS:
        return f"unknown grain {entry.get('grain')!r} — expected one of {', '.join(GRAINS)}"
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
    status = entry.get("status", "DRAFT")
    if status not in ("DRAFT", "NEEDS_INPUT"):
        return f"extracted rule status must be DRAFT or NEEDS_INPUT, got {status!r}"
    return None


def _needs_input_stub(document_id: str, reason: str, window_index: int,
                      window: list[dict]) -> dict:
    first = window[0] if window else {}
    return {
        "rule_code": f"UNPARSED_WINDOW_{window_index:02d}",
        "rule_name": f"Unparseable extractor output (window {window_index})",
        "plain_description": "The extractor's output for this chunk window could not be "
                             "used. It is kept for operator review — never dropped.",
        "worked_example": "",
        "grain": "account",
        "population": "", "compute": "", "trigger": "", "attribute": None,
        "driver_tag": "Extraction",
        "provenance": "DOCUMENT_DERIVED",
        "confidence": 0.0,
        "citations": [{"chunk_id": first.get("chunk_id", ""),
                       "page_no": first.get("page_no"),
                       "section_path": first.get("section_path", ""),
                       "excerpt": (first.get("text", "") or "")[:200]}],
        "status": "NEEDS_INPUT",
        "unclear_notes": reason,
        "document_id": document_id,
    }


def _resolve_llm(document_id: str) -> Callable[[str, dict], str]:
    """The rule_extractor role's client, wrapped so every window call is
    turn-logged (document extraction is a large cost — it is measured) under
    the synthetic run id ``doc_extract|<document_id>``."""
    from app.llm.usage import wrap_llm

    client = build_role_llm("rule_extractor")
    if client is None:
        from app.llm.client import get_llm_client

        client = get_llm_client()
    return wrap_llm(client, f"doc_extract|{document_id}", "rule_extractor")


def extract_rules_for_document(document_id: str, chunks: list[dict],
                               llm: Callable[[str, dict], str] | None = None,
                               persist: bool = True) -> list[dict]:
    """Extract draft rules from one document's chunks (B2 calls this from
    POST /api/documents/{id}/extract-rules).

    `llm` overrides the transport for deterministic tests; default resolves the
    rule_extractor role config (app.llm.roles) falling back to the shared client.
    `persist=True` stores results in the rule store's draft pool."""
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
            rule["grain"] = str(rule["grain"]).lower()
            rule["provenance"] = "DOCUMENT_DERIVED"
            rule["document_id"] = document_id
            rule.setdefault("unclear_notes", None)
            rule.setdefault("attribute", None)
            if rule["rule_code"] in seen_codes:  # overlap window duplicate
                continue
            if rule.get("status") == "DRAFT":
                compiled = compile_status(rule)
                if not compiled["compiled"]:
                    rule["status"] = "NEEDS_INPUT"
                    rule["unclear_notes"] = (
                        f"does not compile: {compiled['compile_error']}"
                        + (f" | {rule['unclear_notes']}" if rule.get("unclear_notes") else "")
                    )
            seen_codes.add(rule["rule_code"])
            extracted.append(rule)

    if persist:
        store = get_rule_store()
        extracted = [store.add_rule(rule, version_id=None) for rule in extracted]
    return extracted
