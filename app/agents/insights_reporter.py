"""C3 — the Insights Reporter agent.

RECEIVES FINDINGS ONLY. This module deliberately imports NOTHING from
``app.graph``, ``app.insights.tools`` or ``app.knowledge`` — the Reporter has
no graph client, no tools, no retrieval. That is the enforcement mechanism
(by construction, not prompt): ``report()`` takes plain dicts and a text-only
LLM callable, so it physically cannot query. verify_round_c asserts this by
scanning this module's imports.

Output: {"narrative": "<two short paragraphs, key clauses in **bold**>",
         "bullets": ["<four bullets, each opening with a bolded claim>"]}

HARD ASSERTION, in code not prompt: every numeric token in the narrative and
bullets must appear in the findings (impact_amt, an evidence cell, or a count
from a finding — plus the transition totals, which are themselves stored query
results on the run). Numbers are extracted with a regex and checked for
membership; on failure the output falls back to a TEMPLATE built directly from
the top findings, and the failure is logged. An unverified figure is never
published.
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


def build_system_prompt() -> str:
    return (
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
        "- Use ONLY numbers that appear in the findings or transition totals. "
        "Do not compute new figures, do not round differently, do not estimate.\n\n"
        "Respond with ONE JSON object only (no markdown fences):\n"
        '{"narrative":"<paragraph one>\\n\\n<paragraph two>","bullets":["...","...","...","..."]}'
    )


def _findings_payload(findings: list[dict], transition: dict) -> str:
    slim = []
    for f in findings:
        slim.append({
            "title": f.get("title"), "summary": f.get("summary"),
            "impact_amt": f.get("impact_amt"), "driver_tag": f.get("driver_tag"),
            "provenance": f.get("provenance"), "rule_key": f.get("rule_key"),
            "evidence_row_count": len(f.get("evidence_rows") or []),
            "evidence_rows": (f.get("evidence_rows") or [])[:6],
        })
    return (f"TRANSITION TOTALS: {json.dumps(transition, default=str)}\n\n"
            f"FINDINGS (ranked by |impact|):\n{json.dumps(slim, default=str)}\n\n"
            "Write the narrative and four bullets. JSON only.")


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


def verify_numbers(narrative: str, bullets: list[str],
                   findings: list[dict], transition: dict) -> list[float]:
    """The numbers in the output that do NOT appear in the findings (empty =
    verified). Membership is exact-after-normalisation on value or |value|."""
    allowed = allowed_numbers(findings, transition)
    text = " ".join([narrative or "", *[b or "" for b in bullets or []]])
    return [n for n in extract_numbers(text)
            if n not in allowed and abs(n) not in allowed]


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
    available. Every number is a finding/transition figure by construction."""
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
    while len(bullets) < 4:
        bullets.append("**No further findings** for this transition.")
    return {"narrative": narrative, "bullets": bullets[:4], "fallback_used": True}


# --------------------------------------------------------------------------- entrypoint

def report(findings: list[dict], transition: dict,
           llm: Callable[[str, dict], str]) -> dict:
    """Findings in, verified narrative out. `llm` is a TEXT callable — this
    function has no tool, graph or retrieval access by construction.

    Returns {"narrative", "bullets", "fallback_used", "unverified_numbers"}."""
    if not findings:
        return {"narrative": "**No findings were produced** for this transition — "
                             "there is nothing to explain beyond the totals.",
                "bullets": [], "fallback_used": False, "unverified_numbers": []}
    raw = ""
    try:
        raw = llm(_findings_payload(findings, transition),
                  {"system_prompt": build_system_prompt()})
        text = raw.strip()
        fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        brace = text.find("{")
        if brace > 0:
            text = text[brace:]
        decoded, _ = json.JSONDecoder().raw_decode(text)
        narrative = str(decoded.get("narrative") or "").strip()
        bullets = [str(b).strip() for b in decoded.get("bullets") or [] if str(b).strip()]
        if not narrative or not bullets:
            raise ValueError("reporter output missing narrative or bullets")
    except Exception as exc:  # noqa: BLE001 — template fallback, loudly
        _log.warning("reporter output unusable (%s) — template fallback; raw starts %r",
                     exc, (raw or "")[:120])
        result = template_report(findings, transition)
        result["unverified_numbers"] = []
        return result

    bad = verify_numbers(narrative, bullets, findings, transition)
    if bad:
        _log.warning("reporter published %d figure(s) not present in the findings "
                     "(%s) — falling back to the template. NEVER publish an "
                     "unverified figure.", len(bad), bad)
        result = template_report(findings, transition)
        result["unverified_numbers"] = bad
        return result
    return {"narrative": narrative, "bullets": bullets,
            "fallback_used": False, "unverified_numbers": []}
