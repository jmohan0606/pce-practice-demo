"""B3.4 / Round E / Round 7 — the Rule Extractor agent.

Entrypoint (called by B2's POST /api/documents/{id}/extract-rules):

    extract_rules_for_document(document_id: str, chunks: list[dict]) -> dict

Each chunk dict carries chunk_id, text, page_no, section_path, has_table.

Round E: the extractor emits PLAIN ENGLISH — a ``statement`` per provision plus
kind / grain / driver_tag / citations / confidence / ``missing``. There is no
expression grammar. The Rule Compiler (app/agents/rule_compiler.py) turns
statements into query plans later, at approval time.

Round 7 (tasks 2–5, 7) — the extraction is now TWO passes:

1. **Extract** candidate provisions per chunk window, as before — but nothing
   is persisted per window any more. Candidates ride the job's resume token,
   so an interruption still loses at most one window.
2. **Deduplicate and rank.** Exact restatements collapse in code; then ONE
   ranking call groups semantic duplicates (same threshold, same scope, same
   subject — regardless of generated rule_code) and orders the distinct
   provisions by significance across the WHOLE document. The top N
   (the Max Rule Extraction Limit, default 10) are persisted, each carrying
   its stated selection reason. This is ranking, not truncation — cutting the
   candidate list at N would keep whatever happened to come first.

The extractor's system prompt now carries the SAME schema listing the compiler
uses (``_schema_text()``), so ``applies_to`` is chosen from what a provision is
conditioned on, checked against the attributes that actually exist — never
"ALL because unsure". No provision-type→scope mapping is encoded anywhere:
the AI interprets, code computes.

``missing`` is a plain sentence naming anything the document references but
does not state (the referral-cap case). A rule with ``missing`` set is still
extracted and still shown; it just cannot be approved until the value is
supplied — status NEEDS_INPUT. A number is NEVER invented.

Output handling is fail-honest end to end: an unparseable LLM response becomes
ONE NEEDS_INPUT stub per window with the parse error attached (stubs bypass
ranking — they are operator-review placeholders, not provisions); an invalid
entry is kept as a stub with the validation error — never silently dropped.
A failed RANKING call falls back to keeping every deduplicated candidate with
the failure stated in the funnel — the cap is never applied blindly.
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

# Round 7 task 2 — the Max Rule Extraction Limit (UI dropdown 5/10/20).
EXTRACTION_LIMITS = (5, 10, 20)
DEFAULT_EXTRACTION_LIMIT = 10

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


def _schema_block() -> str:
    """Round 7 task 5 — the SAME schema listing the Rule Compiler builds from
    docs/tigergraph/schema_catalog.json. The extractor sees what data exists;
    it is NEVER given a mapping of provision types to scopes — that would be
    us doing the interpretation."""
    from app.agents.rule_compiler import _schema_text

    return _schema_text()


def build_system_prompt() -> str:
    """Round E system prompt, reworked in Round 7: explicit negative
    instructions (what is NOT a rule), the graph schema, and an applies_to
    instruction grounded in what the provision is conditioned on."""
    return (
        "You are the Rule Extractor for a wealth-management compensation engine. "
        "You read chunks of a compensation plan document and extract the "
        "governing rules as PLAIN ENGLISH. A separate Rule Compiler turns your "
        "statements into queries later — your job is to state each provision "
        "completely and faithfully, not to formalise it.\n\n"
        "WHAT TO EXTRACT: a provision that defines, qualifies, caps, adjusts, "
        "excludes or thresholds a revenue or compensation outcome, AND that "
        "could be checked against data.\n\n"
        "DO NOT EXTRACT — none of these are rules:\n"
        "- definitions: a glossary entry explaining what a term means is not a "
        "provision\n"
        "- appendix and administrative content: plan effective dates, amendment "
        "clauses (\"the Plan may be changed at any time\"), ethics statements, "
        "contact details\n"
        "- table-of-contents entries, headers, page furniture\n"
        "- restatements: a provision you have already extracted from another "
        "chunk, worded differently, is the SAME provision — do not emit it again\n"
        "- narrative or explanatory text that describes a provision without "
        "stating a rule\n"
        "- worked examples: an illustration using specific numbers is not a "
        "separate provision from the rule it illustrates — attach it to that "
        "rule's `worked_example` instead\n\n"
        "Requirements:\n"
        "- One rule per provision. Do not merge two provisions; do not split one. "
        "A rate table that encodes a single formula (a discount grid, a payout "
        "schedule, an award-rate band table) is ONE provision — state the "
        "formula or schedule, never one rule per row. This generalises: any "
        "table or list that enumerates the cases of a single rule is one "
        "provision. A 7-row grid rate table is ONE rule stating the grid, "
        "not 7 rules.\n"
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
        "product), or ALL. Choose it from WHAT THE PROVISION IS CONDITIONED "
        "ON, checked against the graph schema below: if a provision is "
        "conditioned on an advisor attribute that exists in the schema (a job "
        "code, an advisor plan, an employment status), it is ADVISOR-scoped "
        "and expressible; if it is conditioned on a product or product group, "
        "it is PRODUCT-scoped. ALL is the honest answer ONLY when the "
        "provision genuinely is not limited — it is never the answer to "
        "\"unsure\". When unsure, reason from the schema about what the "
        "condition would be checked against.\n"
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
        "worked_example (or null), kind, grain, applies_to, driver_tag (short "
        "business label like \"Fee Rate\", \"Transfers\", \"Referrals\"), "
        "severity, severity_reason, confidence (0..1), missing (sentence or "
        "null), exception_denominator, exception_floor, exception_floor_unit, "
        "product_scope, product_scope_source, citations.\n"
        "- Return a JSON array only (empty array if the chunks contain no "
        "extractable provision). No prose, no markdown fences. STRICT JSON: "
        "escape every newline inside strings. Keep each citation excerpt under "
        "160 characters.\n\n"
        "GRAPH SCHEMA (every vertex and its attributes — this is what CAN be "
        "checked against data; use it to ground `applies_to` and to judge "
        "whether a provision is checkable):\n" + _schema_block()
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
        "_stub": True,
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


def _coerce_candidate(document_id: str, entry: dict) -> dict:
    """Lenient coercion of one validated extractor entry — never a reason to
    drop a stated rule."""
    rule = dict(entry)
    rule["grain"] = str(rule.get("grain") or "account").lower()
    if rule["grain"] not in GRAINS:
        rule["grain"] = "account"
    kind = str(rule.get("kind") or "").upper()
    rule["kind"] = kind if kind in KINDS else "CALCULATION"
    rule.setdefault("rule_name", rule["rule_code"].replace("_", " ").title())
    rule.setdefault("driver_tag", "Other")
    # Round 5 Part C: applies_to proposal — lenient coercion against the
    # store's closed set; absent/invalid lands at ALL, never drops.
    applies = str(rule.get("applies_to") or "").upper().replace(" ", "_")
    from app.rules.store import APPLIES_TO as _APPLIES_TO
    rule["applies_to"] = applies if applies in _APPLIES_TO else "ALL"
    # Round A1 task 2: severity is extractor-assigned; an absent or invalid
    # level lands honestly at INFO with a reason saying so.
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
    # Round 1 (schema freeze): exception-configuration PROPOSALS from the
    # provision's own language — lenient coercion, null when not stated.
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
    return rule


# --------------------------------------------------------------------- dedup + rank (Round 7)

def _normalized_statement(rule: dict) -> str:
    text = str(rule.get("statement") or "").lower()
    # a dot is content only inside a number (10.5%) — sentence punctuation is not
    text = re.sub(r"(?<!\d)\.(?!\d)", " ", text)
    return re.sub(r"[^a-z0-9%$.]+", " ", text).strip()


def _citation_fullness(rule: dict) -> tuple[int, int]:
    citations = rule.get("citations") or []
    return (len(citations),
            sum(len(str(c.get("excerpt") or "")) for c in citations
                if isinstance(c, dict)))


def _merge_citations(keeper: dict, others: list[dict]) -> None:
    """The kept instance absorbs any citation its duplicates carried that it
    does not (by chunk_id) — dedup must never lose provenance."""
    seen = {str(c.get("chunk_id")) for c in keeper.get("citations") or []
            if isinstance(c, dict)}
    for other in others:
        for citation in other.get("citations") or []:
            if isinstance(citation, dict) and str(citation.get("chunk_id")) not in seen:
                keeper.setdefault("citations", []).append(citation)
                seen.add(str(citation.get("chunk_id")))


def _exact_dedup(candidates: list[dict]) -> tuple[list[dict], int]:
    """Code-level collapse of exact restatements (case/whitespace-normalized
    statement). The keeper is the instance with the fuller citation; it absorbs
    the duplicates' citations. Returns (deduped, collapsed_count)."""
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for rule in candidates:
        key = _normalized_statement(rule) or rule.get("rule_code", "")
        if key not in groups:
            order.append(key)
        groups.setdefault(key, []).append(rule)
    deduped: list[dict] = []
    collapsed = 0
    for key in order:
        members = sorted(groups[key], key=_citation_fullness, reverse=True)
        keeper = members[0]
        if len(members) > 1:
            collapsed += len(members) - 1
            _merge_citations(keeper, members[1:])
        deduped.append(keeper)
    return deduped, collapsed


def _rank_system_prompt() -> str:
    return (
        "You are the significance ranker for provisions extracted from a "
        "compensation plan document. You receive candidate provisions gathered "
        "from overlapping chunk windows of ONE document.\n\n"
        "Do two things:\n"
        "1. GROUP DUPLICATES. The same provision extracted from two overlapping "
        "windows — same threshold, same scope, same subject — is ONE provision "
        "regardless of how its code or wording differs. A worked example of a "
        "provision belongs to that provision's group, not its own.\n"
        "2. RANK the distinct provisions by significance to compensation "
        "outcomes across the whole document: provisions that move money "
        "(formulas, thresholds, caps, exclusions, adjustments) outrank "
        "qualifications and timing details, which outrank informational notes.\n\n"
        "Return ONE JSON object only, no prose, no markdown fences:\n"
        '{"groups": [{"ids": ["<candidate id>", ...], "reason": "<one line: why '
        'this provision ranks here>"}, ...]}\n'
        "- `groups` is ordered MOST significant first.\n"
        "- Every candidate id you were given must appear in exactly one group.\n"
        "- `ids` lists every duplicate instance of the provision.\n"
        "- `reason` states why the provision matters (or does not), in plain "
        "English — it is shown to the operator as the selection reason."
    )


def _rank_and_select(generate: Callable[[str, dict], str], candidates: list[dict],
                     limit: int) -> tuple[list[dict], dict]:
    """One LLM call groups semantic duplicates and ranks distinct provisions;
    the top `limit` are selected IN CODE (so a lower limit selects a prefix of
    the same ranking). Returns (selected_rules, funnel_fields). On a ranking
    failure every code-deduplicated candidate is kept — the cap is never
    applied by truncation."""
    deduped, exact_collapsed = _exact_dedup(candidates)
    total = len(candidates)

    def _fallback(reason: str) -> tuple[list[dict], dict]:
        _log.warning("ranking unavailable (%s) — keeping all %d deduplicated "
                     "candidates rather than truncating", reason, len(deduped))
        return deduped, {
            "candidates": total, "after_dedup": len(deduped),
            "selected": len(deduped), "limit": limit,
            "duplicates_collapsed": total - len(deduped),
            "ranking": f"FAILED — {reason}; all deduplicated candidates kept "
                       f"(a cap applied by truncation would be worse than no cap)"}

    if len(deduped) <= 1:
        return deduped, {
            "candidates": total, "after_dedup": len(deduped),
            "selected": len(deduped), "limit": limit,
            "duplicates_collapsed": total - len(deduped),
            "ranking": "not needed — at most one distinct candidate"}

    by_id: dict[str, dict] = {}
    listing = []
    for i, rule in enumerate(deduped):
        cid = f"C{i:03d}"
        by_id[cid] = rule
        pages = sorted({c.get("page_no") for c in rule.get("citations") or []
                        if isinstance(c, dict) and c.get("page_no") is not None})
        listing.append({
            "id": cid, "rule_code": rule.get("rule_code"),
            "rule_name": rule.get("rule_name"),
            "statement": rule.get("statement"),
            "kind": rule.get("kind"), "applies_to": rule.get("applies_to"),
            "severity": rule.get("severity"), "pages": pages,
        })
    prompt = ("Candidate provisions (JSON):\n" + json.dumps(listing)
              + "\n\nGroup duplicates and rank by significance. "
                "Return the JSON object only.")
    try:
        raw = generate(prompt, {"system_prompt": _rank_system_prompt()})
        tag = getattr(generate, "tag_last", None)
        if callable(tag):
            tag("rank_select", "rank")
    except Exception as exc:  # noqa: BLE001 — honest fallback, never truncation
        return _fallback(f"ranking call failed: {type(exc).__name__}: {exc}")
    text = (raw or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        decoded = json.loads(text)
        groups = decoded["groups"]
        assert isinstance(groups, list)
    except Exception:  # noqa: BLE001
        return _fallback(f"ranking output unusable — starts: {text[:120]!r}")

    seen_ids: set[str] = set()
    ordered_groups: list[tuple[list[dict], str]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        ids = [str(i) for i in (group.get("ids") or []) if str(i) in by_id
               and str(i) not in seen_ids]
        if not ids:
            continue
        seen_ids.update(ids)
        ordered_groups.append(([by_id[i] for i in ids],
                               str(group.get("reason") or "").strip()))
    # a candidate the ranker never mentioned is NEVER silently lost — it joins
    # the ordering last, marked as unranked
    unranked = [cid for cid in by_id if cid not in seen_ids]
    for cid in unranked:
        ordered_groups.append(([by_id[cid]],
                               "not ranked by the model — appended last"))

    selected: list[dict] = []
    for rank, (members, reason) in enumerate(ordered_groups[:limit], start=1):
        members = sorted(members, key=_citation_fullness, reverse=True)
        keeper = members[0]
        if len(members) > 1:
            _merge_citations(keeper, members[1:])
        keeper["selection_rank"] = rank
        keeper["selection_reason"] = reason or "(no reason given)"
        selected.append(keeper)

    semantic_collapsed = len(deduped) - len(ordered_groups)
    funnel = {
        "candidates": total,
        "after_dedup": len(ordered_groups),
        "selected": len(selected),
        "limit": limit,
        "duplicates_collapsed": (total - len(deduped)) + semantic_collapsed,
        "ranking": "ranked by significance across the whole document"
                   + (f"; {len(unranked)} candidate(s) the ranker did not "
                      f"mention were appended last, never dropped" if unranked
                      else ""),
    }
    return selected, funnel


# --------------------------------------------------------------------------- extraction

def extract_rules_for_document(document_id: str, chunks: list[dict],
                               llm: Callable[[str, dict], str] | None = None,
                               persist: bool = True,
                               start_window: int = 0,
                               limit: int = DEFAULT_EXTRACTION_LIMIT,
                               candidates: list[dict] | None = None,
                               on_window: Callable[[int, int, list[dict]], None] | None = None) -> dict:
    """Extract draft rules from one document's chunks — two passes (Round 7):
    per-window candidate extraction, then dedup + significance ranking, with
    only the selected top `limit` persisted to the draft pool.

    `llm` overrides the transport for deterministic tests; `persist=True`
    stores the SELECTED rules in the rule store's draft pool. Rules with
    `missing` set land as NEEDS_INPUT; everything else is DRAFT awaiting the
    Rule Compiler.

    Resume contract: candidates are NOT persisted per window — they ride the
    job's resume token instead. `start_window` resumes at that window with
    `candidates` seeded from the token (earlier windows never repeat);
    `on_window(done, total, candidates)` is called after each window — the
    JobStore's per-item progress hook, whose caller stores the candidates in
    the resume token.

    Returns {"rules": selected_rules, "funnel": {...}}.
    """
    generate = llm or _resolve_llm(document_id)
    system_prompt = build_system_prompt()
    windows = build_windows(chunks)
    limit = max(1, int(limit or DEFAULT_EXTRACTION_LIMIT))
    _log.info("extracting rules for %s: %d chunks in %d window(s), from window "
              "%d, limit %d", document_id, len(chunks), len(windows),
              start_window, limit)

    store = get_rule_store() if persist else None
    collected: list[dict] = [dict(c) for c in (candidates or [])]
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
            window_rules.append(_coerce_candidate(document_id, entry))

        collected.extend(window_rules)
        if on_window is not None:
            on_window(index + 1, len(windows), collected)

    # ---- pass 2: dedup + rank across ALL windows, select the top `limit`.
    # Stubs (unparseable windows / invalid entries) bypass ranking — they are
    # operator-review placeholders, not provisions, and are never dropped.
    stubs = [r for r in collected if r.get("_stub")]
    provisions = [r for r in collected if not r.get("_stub")]
    selected, funnel = _rank_and_select(generate, provisions, limit)
    funnel["unparseable_stubs"] = len(stubs)
    for rule in selected:
        rule["extraction_limit"] = limit
    final = selected + stubs
    for rule in final:
        rule.pop("_stub", None)
    if store is not None:
        final = [store.add_rule(rule, version_id=None) for rule in final]
    _log.info("extraction funnel for %s: %s", document_id, funnel)
    return {"rules": final, "funnel": funnel}


def extract_with_job(document_id: str, chunks: list[dict],
                     llm: Callable[[str, dict], str] | None = None,
                     resume: bool = False,
                     limit: int = DEFAULT_EXTRACTION_LIMIT) -> dict:
    """Round 1 (schema freeze) task 2 / Round 7 — extraction under a
    phx_dm_pce_job.

    Reopens the document's ingest job (or creates one) at stage ``extract``
    with per-window item progress; ``resume_token = {"next_window": N,
    "limit": L, "candidates": [...]}`` after every completed window — the
    accumulated candidates live in the token, so an interruption loses at most
    one window and the draft pool never holds unranked candidates. Calling
    again with ``resume=True`` restarts at the recorded window with the
    recorded candidates AND the recorded limit (the original run's limit wins
    over the argument). Resume is explicit — never automatic.

    On completion the job record carries the extraction funnel and the limit
    (``funnel`` / ``extraction_limit``), so runs at different limits are
    distinguishable.

    Returns {"job": job_dict, "rules": selected_rules, "funnel": {...}}.
    """
    from app.shared.jobs import get_job_store

    jobs = get_job_store()
    job = jobs.latest_for("document_ingest", document_id)
    start_window = 0
    prior_candidates: list[dict] = []
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
        prior_candidates = list(token.get("candidates") or [])
        limit = int(token.get("limit") or limit or DEFAULT_EXTRACTION_LIMIT)
    limit = max(1, int(limit or DEFAULT_EXTRACTION_LIMIT))
    if job is None:
        job = jobs.begin_job("document_ingest", document_id)
    total = len(build_windows(chunks))
    job = jobs.update(job["job_id"], stage="extract",
                      items_done=start_window, items_total=total,
                      resume_token={"next_window": start_window, "limit": limit,
                                    "candidates": prior_candidates},
                      extra={"extraction_limit": limit, "funnel": None})

    def _on_window(done: int, total_windows: int, candidates: list[dict]) -> None:
        jobs.update(job["job_id"], items_done=done, items_total=total_windows,
                    resume_token={"next_window": done, "limit": limit,
                                  "candidates": candidates})

    try:
        result = extract_rules_for_document(
            document_id, chunks, llm=llm, persist=True,
            start_window=start_window, limit=limit,
            candidates=prior_candidates, on_window=_on_window)
    except BaseException as exc:  # noqa: BLE001 — incl. KeyboardInterrupt/kill paths
        current = jobs.get(job["job_id"]) or job
        jobs.interrupt(job["job_id"], resume_token=current.get("resume_token"),
                       error=f"extraction interrupted: {type(exc).__name__}: {exc}")
        raise
    jobs.update(job["job_id"], extra={"funnel": result["funnel"],
                                      "extraction_limit": limit})
    finished = jobs.complete(job["job_id"])
    return {"job": finished, "rules": result["rules"], "funnel": result["funnel"]}
