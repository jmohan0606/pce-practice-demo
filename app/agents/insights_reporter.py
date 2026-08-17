"""C3 — the Insights Reporter agent (+ Round E task 5 recommendations).

RECEIVES FINDINGS ONLY. This module deliberately imports NOTHING from
``app.graph``, ``app.insights.tools`` or ``app.knowledge`` — the Reporter has
no graph client, no tools object, no retrieval imports. verify_round_c asserts
this by scanning this module's imports.

Round E task 5 relaxes that ONE notch, by injection rather than import: the
service may pass a ``search_documents(query, source, top_k)`` callable (built
in ``app/insights/reporter_sources.py``) so the Reporter can FETCH a plan
threshold or a guidance passage with its citation instead of recalling it.
PLAN documents -> thresholds/rules/qualifications; GUIDANCE documents ->
recommended practice, quoted with citation. The module's import surface is
unchanged — the capability exists only when the caller hands it in.

Output: {"narrative": "<two short paragraphs, key clauses in **bold**>",
         "bullets": ["<four bullets, each opening with a bolded claim>"],
         "recommendations": [{"text", "source_query", "citations"}]}

HARD ASSERTIONS, in code not prompt:
1. every numeric token in the narrative and bullets must appear in the findings
   (impact_amt, an evidence cell, a count — plus the transition totals, which
   are themselves stored query results on the run). On failure the output falls
   back to a TEMPLATE built directly from the top findings, and the failure is
   logged. An unverified figure is never published.
2. every RECOMMENDATION is facts and their implications, nothing invented: it
   must carry a ``source_query`` (a query that produced a finding) or at least
   one resolved document ``citation``, its numbers must all appear in the
   findings/transition/cited excerpts, and NNM-based recommendations are
   dropped outright (DECISIONS.md, Round E — three months of flows must not
   proxy an annual measure). A recommendation failing any of these is NOT
   emitted; an ``assert`` guards the returned list.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable

_log = logging.getLogger("app.agents.insights_reporter")

MONTH_WORDS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
               "oct", "nov", "dec")

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def build_system_prompt(search_available: bool = False,
                        cross_cutting: bool = False) -> str:
    prompt = (
        "You are the Insights Reporter for a wealth-management practice dashboard. "
        "You receive FINDINGS (already investigated, with figures) and write the "
        "client-facing summary. You have no data access — every figure you use "
        "must be copied verbatim from the findings provided.\n\n"
        "Style (strict):\n"
        "- Two SHORT paragraphs of narrative, then exactly four bullets.\n"
        "- Lead with what is INTERESTING, not what is largest. 'Revenue rose "
        "$227,230, but almost none of it came from new business' beats 'Revenue "
        "rose 3.6%.'\n"
        "- Key clauses in **bold**; each bullet OPENS with a bolded claim.\n"
        "- Plain business English. No driver codes, no field names, no rule "
        "identifiers, no query names.\n"
        "- Negatives in parentheses: ($18,400). Dollar figures with commas. "
        "Percentages like 3.6%.\n"
        "- Use ONLY numbers that appear in the findings or transition totals — "
        "plus, when connecting drivers, the SUM or DIFFERENCE of two headline "
        "figures or a percentage of one headline figure over another (the "
        "system re-computes and verifies these; any other derived figure is "
        "rejected). Never estimate.\n\n"
        + ("CROSS-CUTTING (Round 3 task 4 — this is the practice-level "
           "narrative): say what the whole picture means, never restate a "
           "single driver — the per-driver story already renders as Revenue "
           "Drivers beside this text. Lead with connections across findings, "
           "concentration, what did NOT happen, and what is about to matter, "
           "using only figures present in the findings.\n\n"
           if cross_cutting else "")
        + "RECOMMENDATIONS (optional, at most 3): facts and their implications, "
        "NOTHING invented. Every clause must trace to a query result or a "
        "document citation. Allowed shape: a figure from a finding set against "
        "a cited plan threshold, plus a traceable fact ('...three pending "
        "opportunities total $1.4M'). NOT allowed: advice or opinion "
        "('Prioritise this advisor for support'), extrapolation, annualisation, "
        "or ANY net-new-money (NNM) figure — only three months of flows exist. "
        "Each recommendation object needs:\n"
        '- "text": the recommendation sentence(s)\n'
        '- "source_query": the query_name of the finding it restates (or null)\n'
        '- "citations": list of excerpt ids like ["D1"] you were given (or [])\n'
        "A recommendation with neither a source_query nor a citation is "
        "discarded in code, as is one containing any number not present in the "
        "findings or the cited excerpts.\n"
    )
    if search_available:
        prompt += (
            "\nDOCUMENT SEARCH: before your final answer you may look up plan "
            "thresholds and recommended practice — never recall them from memory. "
            "Respond with ONLY this JSON to search (max 4 searches):\n"
            '{"action":"search_documents","source":"PLAN","query":"<what to find>"}\n'
            "source is PLAN (thresholds, rules, qualifications) or GUIDANCE "
            "(recommended practice — quote it with its citation). Results come "
            "back as excerpts with ids [D1], [D2], ... which you cite in "
            "recommendations via \"citations\".\n"
        )
    prompt += (
        "\nWhen (and only when) you are done, respond with ONE JSON object only "
        "(no markdown fences):\n"
        '{"narrative":"<paragraph one>\\n\\n<paragraph two>",'
        '"bullets":["...","...","...","..."],'
        '"recommendations":[{"text":"...","source_query":"<query_name or null>",'
        '"citations":["D1"]}]}'
    )
    return prompt


def _findings_payload(findings: list[dict], transition: dict) -> str:
    slim = []
    for f in findings:
        slim.append({
            "title": f.get("title"), "summary": f.get("summary"),
            "impact_amt": f.get("impact_amt"), "driver_tag": f.get("driver_tag"),
            "provenance": f.get("provenance"), "rule_key": f.get("rule_key"),
            # traceability handle for recommendations (task 5)
            "source_query": (f.get("source_query") or {}).get("query_name"),
            "evidence_row_count": len(f.get("evidence_rows") or []),
            "evidence_rows": (f.get("evidence_rows") or [])[:6],
        })
    return (f"TRANSITION TOTALS: {json.dumps(transition, default=str)}\n\n"
            f"FINDINGS (ranked by |impact|):\n{json.dumps(slim, default=str)}\n\n"
            "Write the narrative, four bullets and any traceable recommendations. "
            "JSON only.")


# --------------------------------------------------------------------------- numeric verification

def _collect_numbers(value, out: set[float]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.add(round(float(value), 2))
        out.add(round(abs(float(value)), 2))
        return
    if isinstance(value, str):
        for token in _NUMBER_RE.findall(value):
            try:
                num = float(token.replace(",", ""))
            except ValueError:
                continue
            out.add(round(num, 2))
        return
    if isinstance(value, dict):
        for v in value.values():
            _collect_numbers(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _collect_numbers(v, out)


def allowed_numbers(findings: list[dict], transition: dict) -> set[float]:
    """Every number a narrative may legitimately contain: finding impacts,
    evidence cells, evidence-row counts, and the transition totals."""
    allowed: set[float] = set()
    for f in findings:
        _collect_numbers(f.get("impact_amt"), allowed)
        _collect_numbers(f.get("evidence_rows"), allowed)
        _collect_numbers(f.get("summary"), allowed)   # counts stated by the miner
        _collect_numbers(f.get("title"), allowed)
        allowed.add(float(len(f.get("evidence_rows") or [])))
    _collect_numbers(transition, allowed)
    allowed.add(float(len(findings)))
    return allowed


def _is_date_token(text: str, start: int, end: int, token: str) -> bool:
    """Skip month-adjacent numbers ('Apr 2026', '17 Jun', 'May') and month ids."""
    if re.fullmatch(r"20\d{4}", token):       # 202605-style month id
        return True
    window = text[max(0, start - 12):min(len(text), end + 12)].lower()
    if re.fullmatch(r"20\d{2}", token) and any(m in window for m in MONTH_WORDS):
        return True
    if len(token) <= 2 and any(m in window for m in MONTH_WORDS):
        return True
    return False


def extract_numbers(text: str) -> list[float]:
    """The numeric tokens of a narrative, excluding date phrasing."""
    numbers = []
    for match in _NUMBER_RE.finditer(text or ""):
        token = match.group(0)
        if _is_date_token(text, match.start(), match.end(), token):
            continue
        try:
            numbers.append(round(float(token.replace(",", "")), 2))
        except ValueError:
            continue
    return numbers


def _is_rounding_of_allowed(n: float, allowed: set[float]) -> bool:
    """Round 4 task 2 (found by observation): Sonnet writes "$34,166" for the
    transition's 34165.52 — standard whole-dollar rounding, not an invented
    figure — and the exact-match gate killed real narratives for it (two
    consecutive template fallbacks on the same transition). An INTEGER token
    is accepted when some non-integer allowed figure rounds or truncates to
    it. Non-integer tokens keep exact matching; derived arithmetic (sums and
    differences the model computed itself) still has no allowed source and
    still falls."""
    if n != int(n):
        return False
    target = abs(n)
    return any(not float(f).is_integer()
               and (round(abs(f)) == target or int(abs(f)) == target)
               for f in allowed)


def _headline_figures(findings: list[dict], transition: dict) -> list[float]:
    """The small set two-figure combinations are verified against: finding
    impact_amts plus the transition totals — never evidence cells (a
    combinatorial base of hundreds of rows would accept almost anything)."""
    values: list[float] = []
    for f in findings:
        if isinstance(f.get("impact_amt"), (int, float)):
            values.append(abs(float(f["impact_amt"])))
    for key in ("from_amt", "to_amt", "change_amt"):
        v = transition.get(key)
        if isinstance(v, (int, float)):
            values.append(abs(float(v)))
    return values


def _is_verified_sum_or_diff(n: float, headline: list[float]) -> bool:
    """Round 4 task 2 (found by observation): the Round 3 cross-cutting
    mandate ASKS for connection statements ("together these added $85,341")
    while the gate banned every computed figure — the same transition fell
    back to the template three times on correct arithmetic. Resolution: the
    gate VERIFIES the arithmetic instead of banning it — a token is accepted
    when it provably equals a sum or difference of TWO headline figures (to
    the dollar). Anything unreproducible still falls."""
    target = abs(n)
    for i, a in enumerate(headline):
        for b in headline[i:]:
            if abs((a + b) - target) < 0.51 or abs(abs(a - b) - target) < 0.51:
                return True
    return False


def _is_named_ratio(n: float, unit_tokens: list[float],
                    headline: list[float]) -> bool:
    """Round 4 operator fix — the old percentage branch accepted a token
    matching ANY ratio of ANY two headline figures: with 6 figures that is 36
    ratios, so ~1.6% of all possible percentage values were auto-accepted and
    an invented 87.3% slipped through because it coincidentally equals
    48,007 / 54,978. A percentage that matches a ratio nobody stated is a
    coincidence, not a verified figure. A percent-shaped token is now
    accepted ONLY when both the numerator and the denominator of its ratio
    are headline figures AND both appear as tokens in the SAME sentence or
    bullet (exact, or their whole-dollar rounding)."""
    target = abs(n)
    if not (0 < target <= 100):
        return False

    def _named(figure: float) -> bool:
        return any(t == round(figure, 2) or t == round(figure)
                   or (float(t).is_integer() and int(t) == int(figure))
                   for t in unit_tokens)

    for a in headline:
        for b in headline:
            if b and abs(round(a / b * 100, 1) - target) < 0.051 \
                    and _named(a) and _named(b):
                return True
    return False


def _verification_units(narrative: str, bullets: list[str]) -> list[str]:
    """The contexts a named ratio is scoped to: each SENTENCE of the
    narrative, and each bullet whole."""
    units: list[str] = []
    for paragraph in (narrative or "").split("\n"):
        units.extend(s for s in re.split(r"(?<=[.!?])\s+", paragraph) if s.strip())
    units.extend(b for b in bullets or [] if (b or "").strip())
    return units


def verify_numbers(narrative: str, bullets: list[str],
                   findings: list[dict], transition: dict) -> list[float]:
    """The numbers in the output that do NOT appear in the findings (empty =
    verified). Membership is exact-after-normalisation on value or |value|,
    plus whole-dollar roundings of allowed figures, plus VERIFIED two-figure
    sums/differences of headline figures, plus percentages whose numerator
    AND denominator are both named in the same sentence or bullet — the gate
    reproduces every piece of arithmetic; nothing unreproducible passes."""
    allowed = allowed_numbers(findings, transition)
    headline = _headline_figures(findings, transition)
    bad: list[float] = []
    for unit in _verification_units(narrative, bullets):
        unit_tokens = extract_numbers(unit)
        for n in unit_tokens:
            if n in allowed or abs(n) in allowed:
                continue
            if _is_rounding_of_allowed(n, allowed):
                continue
            if _is_verified_sum_or_diff(n, headline):
                continue
            if _is_named_ratio(n, unit_tokens, headline):
                continue
            bad.append(n)
    return bad


# --------------------------------------------------------------------------- recommendations (task 5)

# NNM is measured annually and we hold three months of flows — an NNM figure
# would be a proxy shipped as a fact (DECISIONS.md, Round E). Dropped outright.
_NNM_RE = re.compile(r"\bNNM\b|net[\s-]?new[\s-]?money", re.IGNORECASE)


def _citation_view(excerpt: dict) -> dict:
    """The citation a recommendation carries — provenance fields only."""
    return {"document_id": excerpt.get("document_id"),
            "document_name": excerpt.get("document_name"),
            "document_type": excerpt.get("document_type"),
            "chunk_id": excerpt.get("chunk_id"),
            "page_no": excerpt.get("page_no"),
            "section_path": excerpt.get("section_path"),
            "excerpt": excerpt.get("excerpt")}


def verify_recommendations(recs, findings: list[dict], transition: dict,
                           excerpts: dict[str, dict]) -> tuple[list[dict], list[str]]:
    """The task-5 gate, in code not prompt. Keeps only recommendations that
    (a) carry a source_query naming a query that produced a finding, OR at
    least one citation resolving to a fetched excerpt; (b) contain no number
    absent from the findings/transition/cited excerpts; (c) are not NNM-based.
    Returns (kept, drop_reasons) — a dropped recommendation is never emitted."""
    finding_queries = {}
    for f in findings:
        name = (f.get("source_query") or {}).get("query_name")
        if name:
            finding_queries[name] = f.get("source_query")
    base_allowed = allowed_numbers(findings, transition)
    kept: list[dict] = []
    dropped: list[str] = []
    for rec in recs if isinstance(recs, list) else []:
        if not isinstance(rec, dict):
            dropped.append(f"not an object: {rec!r}")
            continue
        text = str(rec.get("text") or "").strip()
        if not text:
            dropped.append("empty text")
            continue
        if _NNM_RE.search(text):
            dropped.append(f"NNM-based (dropped per Round E decision): {text[:80]!r}")
            continue
        cited = [excerpts[c] for c in (rec.get("citations") or [])
                 if isinstance(c, str) and c in excerpts]
        sq_name = rec.get("source_query")
        source_query = finding_queries.get(str(sq_name)) if sq_name else None
        if source_query is None and not cited:
            dropped.append(f"no source_query or citation: {text[:80]!r}")
            continue
        allowed = set(base_allowed)
        for excerpt in cited:
            _collect_numbers(excerpt.get("excerpt"), allowed)
            # "[Plan p.6]"-style pointers are part of a citation, not a figure
            _collect_numbers(excerpt.get("page_no"), allowed)
            _collect_numbers(excerpt.get("section_path"), allowed)
        bad = [n for n in extract_numbers(text)
               if n not in allowed and abs(n) not in allowed]
        if bad:
            dropped.append(f"unverified number(s) {bad}: {text[:80]!r}")
            continue
        kept.append({"text": text,
                     "source_query": source_query,
                     "citations": [_citation_view(e) for e in cited]})
    # the task-5 assertion: nothing untraceable leaves this function
    assert all(r.get("source_query") or r.get("citations") for r in kept), \
        "recommendation without a source_query or citation survived verification"
    return kept, dropped


# --------------------------------------------------------------------------- template fallback

def _fmt_money(value: float) -> str:
    """Exact rendering — never round away cents, or the template would fail its
    own numeric verification."""
    body = f"{abs(value):,.2f}"
    if body.endswith(".00"):
        body = body[:-3]
    return f"(${body})" if value < 0 else f"${body}"


def template_report(findings: list[dict], transition: dict) -> dict:
    """Deterministic fallback built DIRECTLY from the top findings — used when
    the LLM output contains an unverifiable figure (logged) or no LLM is
    available. Every number is a finding/transition figure by construction.

    Round F 5.2: emits ONLY the bullets that exist — one finding, one bullet
    (capped at four). No padding: the old version repeated "No further
    findings" up to three times to hit a bullet minimum."""
    change = float(transition.get("change_amt") or 0.0)
    direction = "rose" if change >= 0 else "fell"
    top = [f for f in findings if f.get("impact_amt") is not None][:4] or findings[:4]
    lead = top[0] if top else None
    narrative = (f"**Credited revenue {direction} {_fmt_money(abs(change))}** between the "
                 f"two months.")
    if lead:
        narrative += (f"\n\nThe largest identified driver was **{lead['title']}** "
                      f"({_fmt_money(lead['impact_amt'])})." if lead.get("impact_amt")
                      is not None else f"\n\nMost notable: **{lead['title']}**.")
    bullets = []
    for f in top:
        impact = (f" — {_fmt_money(f['impact_amt'])}" if f.get("impact_amt") is not None
                  else "")
        bullets.append(f"**{f['title']}**{impact}. {f.get('summary', '')}".strip())
    return {"narrative": narrative, "bullets": bullets, "fallback_used": True}


# --------------------------------------------------------------------------- entrypoint

def _max_searches() -> int:
    """Round H task 2: settings-resolved (REPORTER_MAX_SEARCHES), not a
    module constant."""
    from app.config.settings import get_settings

    return get_settings().reporter_max_searches


def _decode_reply(raw: str) -> dict:
    text = (raw or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    brace = text.find("{")
    if brace > 0:
        text = text[brace:]
    decoded, _ = json.JSONDecoder().raw_decode(text)
    if not isinstance(decoded, dict):
        raise ValueError("reporter reply is not a JSON object")
    return decoded


def report(findings: list[dict], transition: dict,
           llm: Callable[[str, dict], str],
           search_documents: Callable[..., list[dict]] | None = None,
           cross_cutting: bool = False) -> dict:
    """Findings in, verified narrative + traceable recommendations out. `llm`
    is a TEXT callable; `search_documents` (optional, INJECTED — this module
    imports no retrieval) lets the model fetch plan thresholds / guidance with
    citations before answering. Without it, no searches happen and only
    query-sourced recommendations can survive verification.

    Returns {"narrative", "bullets", "recommendations", "fallback_used",
    "unverified_numbers", "recommendations_dropped", "search_count"}."""
    if not findings:
        return {"narrative": "**No findings were produced** for this transition — "
                             "there is nothing to explain beyond the totals.",
                "bullets": [], "recommendations": [], "fallback_used": False,
                "unverified_numbers": [], "recommendations_dropped": [],
                "search_count": 0}
    excerpts: dict[str, dict] = {}  # "D1" -> fetched excerpt
    prompt = _findings_payload(findings, transition)
    searches = 0
    raw = ""
    try:
        while True:
            raw = llm(prompt, {"system_prompt":
                               build_system_prompt(search_documents is not None,
                                                   cross_cutting=cross_cutting)})
            decoded = _decode_reply(raw)
            if decoded.get("action") != "search_documents":
                break
            if search_documents is None:
                raise ValueError("search_documents requested but unavailable")
            if searches >= _max_searches():
                if prompt.endswith("final JSON now."):
                    raise ValueError("search budget exhausted twice")
                prompt += ("\n\nSEARCH BUDGET EXHAUSTED — give the "
                           "final JSON now.")
                continue
            searches += 1
            try:
                rows = search_documents(str(decoded.get("query") or ""),
                                        str(decoded.get("source") or "PLAN"),
                                        int(decoded.get("top_k") or 5))
            except Exception as exc:  # noqa: BLE001 — a failed search is a result
                rows = []
                _log.warning("reporter search failed: %s", exc)
            labeled = []
            for row in rows:
                sid = f"D{len(excerpts) + 1}"
                excerpts[sid] = dict(row)
                labeled.append({"id": sid, **{k: row.get(k) for k in
                                              ("document_name", "document_type",
                                               "page_no", "section_path", "excerpt")}})
            prompt += (f"\n\nSEARCH {searches} (source="
                       f"{str(decoded.get('source') or 'PLAN').upper()}, query="
                       f"{json.dumps(str(decoded.get('query') or ''))}) RESULTS:\n"
                       f"{json.dumps(labeled, default=str)}\n"
                       f"Cite these by id in recommendations. Search again or "
                       f"give the final JSON.")
        narrative = str(decoded.get("narrative") or "").strip()
        bullets = [str(b).strip() for b in decoded.get("bullets") or [] if str(b).strip()]
        if not narrative or not bullets:
            raise ValueError("reporter output missing narrative or bullets")
    except Exception as exc:  # noqa: BLE001 — template fallback, loudly
        _log.warning("reporter output unusable (%s) — template fallback; raw starts %r",
                     exc, (raw or "")[:120])
        result = template_report(findings, transition)
        result.update(unverified_numbers=[], recommendations=[],
                      recommendations_dropped=[], search_count=searches)
        return result

    # task-5 gate: only traceable, number-verified, non-NNM recommendations
    recommendations, dropped = verify_recommendations(
        decoded.get("recommendations"), findings, transition, excerpts)
    if dropped:
        _log.warning("reporter dropped %d untraceable recommendation(s): %s",
                     len(dropped), dropped)

    bad = verify_numbers(narrative, bullets, findings, transition)
    repaired = False
    if bad:
        # Round G task 2: ONE repair round before the template — the diagnosis
        # showed rejected narratives whose other sentences were fully verified;
        # naming the rejected figures usually salvages a real narrative. The
        # gate itself is unchanged and re-runs on the rewrite.
        _log.warning("reporter figures not present in the findings (%s) — "
                     "one repair round", bad)
        try:
            repair_prompt = (
                prompt + "\n\nYOUR PREVIOUS ANSWER:\n"
                + json.dumps({"narrative": narrative, "bullets": bullets})
                + f"\n\nREJECTED — these figures are neither in the findings/"
                  f"transition totals nor a verifiable sum/difference/percentage "
                  f"of TWO headline figures: {bad}. For each, either replace it "
                  f"with an exact figure from the findings or DROP the claim "
                  f"entirely. Keep your recommendations. JSON only.")
            redecoded = _decode_reply(llm(repair_prompt, {
                "system_prompt": build_system_prompt(search_documents is not None,
                                                     cross_cutting=cross_cutting)}))
            new_narrative = str(redecoded.get("narrative") or "").strip()
            new_bullets = [str(b).strip() for b in redecoded.get("bullets") or []
                           if str(b).strip()]
            if not (new_narrative and new_bullets):
                _log.warning("reporter repair returned no usable rewrite — "
                             "original rejection list stands")
            if new_narrative and new_bullets:
                bad2 = verify_numbers(new_narrative, new_bullets, findings, transition)
                if not bad2:
                    narrative, bullets, bad, repaired = new_narrative, new_bullets, [], True
                    if redecoded.get("recommendations") is not None:
                        recommendations, dropped = verify_recommendations(
                            redecoded.get("recommendations"), findings, transition,
                            excerpts)
                else:
                    bad = bad2
        except Exception as exc:  # noqa: BLE001 — a failed repair falls through
            _log.warning("reporter repair round failed (%s)", exc)
    if bad:
        _log.warning("reporter published %d figure(s) not present in the findings "
                     "(%s) after repair — falling back to the template. NEVER "
                     "publish an unverified figure.", len(bad), bad)
        result = template_report(findings, transition)
        # verified independently against their own sources — they survive
        result.update(unverified_numbers=bad, recommendations=recommendations,
                      recommendations_dropped=dropped, search_count=searches)
        return result
    return {"narrative": narrative, "bullets": bullets,
            "recommendations": recommendations, "fallback_used": False,
            "repaired": repaired,
            "unverified_numbers": [], "recommendations_dropped": dropped,
            "search_count": searches}
