"""Round F2 task 4.3 — advisor NNM catalog queries (Subagent B's module).

catalog.py imports this at the end of its own module load and merges
EXTRA_CATALOG into CATALOG; @mock_query implementations register on import.
GSQL twins live under docs/tigergraph/queries/.

HONESTY CONSTRAINTS:
- The YTD position is the LATEST available month's ytd_nnm per
  advisor x category — never a sum of MTD rows.
- nnm_threshold_position NEVER annualises or extrapolates: it reports the YTD
  figure, the month it is as of, and the gap.
- The dollar threshold is PLAN-DOCUMENT content (check 13): no threshold
  constant lives in this file. resolve_nnm_threshold() reads it from the
  currently published, active, document-derived rule at read time; when no
  single rule states it, the position is reported without a threshold and the
  reason is named.
- category_source carries the raw NNM file prefix on every row: only EC is
  confirmed by the plan document; NB/YI/FS are inferred from filenames.
"""
from __future__ import annotations

import re
from typing import Any

from app.graph.client import mock_query
from app.graph.foundation_store import FoundationGraphStore

# NOTE: nothing is imported from catalog.py at module level — catalog.py
# imports THIS module at the end of its own load, so a top-level import back
# into catalog would blow up whenever this module is imported first (proven).
# CatalogError is fetched lazily; the param dicts below replicate catalog's
# _p() shape verbatim.


def _p(name: str, ptype: str, required: bool = True, default: Any = None) -> dict:
    return {"name": name, "type": ptype, "required": required, "default": default}


ADVISOR = _p("advisor", "advisor_sid | 'all'")


def _catalog_error(msg: str) -> Exception:
    from app.graph.queries.catalog import CatalogError

    return CatalogError(msg)


def _num(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


V_NNM = "phx_dm_pce_advisor_nnm"

NNM_CATEGORIES = ("EC", "NB", "YI", "FS")
NNM_CATEGORY_LABELS = {"EC": "Existing Client", "NB": "New Business",
                       "YI": "Year-Initiated", "FS": "Full Service"}

_NNM_TEXT = re.compile(r"\bNNM\b|net[\s-]*new[\s-]*money", re.IGNORECASE)
# dollar amounts in statements — digits with separators, "MM" or "million"
# suffixes — used only to READ a threshold out of an extracted rule's text.
_DOLLAR = re.compile(
    r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(mm|m\b|million)?", re.IGNORECASE)


def _advisor_nnm_scope(store: FoundationGraphStore, advisor: str) -> set[str]:
    """Advisor scope for NNM queries. Unlike revenue queries, NNM rows may
    exist for advisors we hold no revenue for — but an unknown sid should
    still fail loudly like everywhere else."""
    advisors = store.all_vertices("phx_dm_pce_advisor")
    if advisor in ("", "all", None):
        return {sid for sid, a in advisors.items() if a.get("in_cohort") is True}
    if advisor not in advisors:
        raise _catalog_error(f"unknown advisor '{advisor}'")
    return {str(advisor)}


def _latest_rows(store: FoundationGraphStore, scope: set[str],
                 category: str | None = None) -> list[dict]:
    """One row per advisor x category: the LATEST month's row (its ytd_nnm IS
    the position — never a sum of MTD)."""
    latest: dict[tuple[str, str], dict] = {}
    for r in store.all_vertices(V_NNM).values():
        sid = str(r.get("advisor_sid"))
        cat = str(r.get("category"))
        if sid not in scope:
            continue
        if category and cat != category:
            continue
        key = (sid, cat)
        cur = latest.get(key)
        if cur is None or str(r.get("month_id")) > str(cur.get("month_id")):
            latest[key] = r
    return [latest[k] for k in sorted(latest)]


@mock_query("advisor_nnm_position")
def advisor_nnm_position(store: FoundationGraphStore, params: dict) -> list[dict]:
    category = str(params.get("category") or "") or None
    if category and category not in NNM_CATEGORIES:
        raise _catalog_error(
            f"unknown NNM category '{category}' — expected one of {list(NNM_CATEGORIES)}")
    scope = _advisor_nnm_scope(store, params["advisor"])
    out = []
    for r in _latest_rows(store, scope, category):
        out.append({
            "advisor_sid": str(r.get("advisor_sid")),
            "category": str(r.get("category")),
            "category_source": str(r.get("category_source") or ""),
            "latest_month": str(r.get("month_id")),
            "mtd_nnm": round(_num(r.get("mtd_nnm")), 2),
            "ytd_nnm": round(_num(r.get("ytd_nnm")), 2),
            "as_of_dt": str(r.get("as_of_dt") or ""),
        })
    return out


@mock_query("advisor_nnm_all_categories")
def advisor_nnm_all_categories(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_nnm_scope(store, params["advisor"])
    rows = _latest_rows(store, scope)
    # aggregate across the scope per category (single advisor => that advisor)
    by_cat: dict[str, dict] = {}
    for r in rows:
        cat = str(r.get("category"))
        agg = by_cat.setdefault(cat, {
            "category": cat, "category_source": str(r.get("category_source") or ""),
            "label": NNM_CATEGORY_LABELS.get(cat, cat),
            "latest_month": "", "mtd_nnm": 0.0, "ytd_nnm": 0.0, "advisor_count": 0})
        agg["mtd_nnm"] = round(agg["mtd_nnm"] + _num(r.get("mtd_nnm")), 2)
        agg["ytd_nnm"] = round(agg["ytd_nnm"] + _num(r.get("ytd_nnm")), 2)
        agg["latest_month"] = max(agg["latest_month"], str(r.get("month_id")))
        agg["advisor_count"] += 1
    out = [by_cat[c] for c in NNM_CATEGORIES if c in by_cat]
    if out:
        out.append({
            "category": "TOTAL", "category_source": "",
            "label": "Total (all four categories)",
            "latest_month": max(r["latest_month"] for r in out),
            "mtd_nnm": round(sum(r["mtd_nnm"] for r in out), 2),
            "ytd_nnm": round(sum(r["ytd_nnm"] for r in out), 2),
            "advisor_count": max(r["advisor_count"] for r in out),
        })
    return out


# ------------------------------------------------------------------ threshold

def _dollar_amounts(text: str) -> list[float]:
    out = []
    for m in _DOLLAR.finditer(text or ""):
        val = float(m.group(1).replace(",", ""))
        if m.group(2):  # MM / million suffix
            val *= 1_000_000.0
        out.append(val)
    return out


def _rule_threshold(rule: dict) -> float | None:
    """The dollar threshold an extracted NNM rule states, read from its
    compiled plan first (trigger/filter values), else its statement text.
    Only 'large-dollar' values qualify — a bps award rate or a small
    minimum-award floor is
    not the annual-flows threshold."""
    candidates: list[float] = []
    plan = rule.get("plan") or {}
    trig = (plan.get("trigger") or {}).get("value")
    if isinstance(trig, (int, float)):
        candidates.append(float(trig))
    for f in plan.get("filters") or []:
        v = f.get("value")
        if isinstance(v, (int, float)):
            candidates.append(float(v))
    candidates.extend(_dollar_amounts(str(rule.get("statement") or "")))
    big = sorted({c for c in candidates if c >= 100_000.0})
    if len(big) == 1:
        return big[0]
    if len(big) > 1:
        # a threshold plus band boundaries: the SMALLEST large-dollar figure
        # in an "at or above" rule is the qualification threshold
        return big[0]
    return None


def resolve_nnm_threshold() -> dict | None:
    """Find THE published, active, NNM-award rule and read its threshold.

    Returns {"threshold_amt", "rule_key", "citation", "statement"} or None.
    Conservative: zero candidates -> None; multiple candidate rules whose
    thresholds DISAGREE -> None (the note names them). The threshold is never
    guessed and never hardcoded (check 13)."""
    from app.rules.store import get_rule_store

    store = get_rule_store()
    latest = store.latest_version()
    if not latest:
        return None
    rules = store.version_rules(latest["version_id"])
    hits = []
    for r in rules:
        if r.get("status") != "PUBLISHED" or r.get("active") is not True:
            continue
        text = " ".join(str(r.get(k) or "") for k in
                        ("statement", "rule_name", "plain_description", "driver_label"))
        if not _NNM_TEXT.search(text):
            continue
        amt = _rule_threshold(r)
        if amt is not None:
            citation = (r.get("citations") or [None])[0]
            hits.append({"threshold_amt": amt, "rule_key": str(r.get("rule_key")),
                         "citation": citation,
                         "statement": str(r.get("statement") or "")})
    if not hits:
        return None
    amounts = {h["threshold_amt"] for h in hits}
    if len(amounts) > 1:
        return {"conflict": sorted(h["rule_key"] for h in hits),
                "amounts": sorted(amounts)}
    best = hits[0]
    if len(hits) > 1:
        best = dict(best, corroborating=[h["rule_key"] for h in hits[1:]])
    return best


@mock_query("nnm_threshold_position")
def nnm_threshold_position(store: FoundationGraphStore, params: dict) -> list[dict]:
    scope = _advisor_nnm_scope(store, params["advisor"])
    resolved = resolve_nnm_threshold()
    out = []
    for r in _latest_rows(store, scope, "EC"):
        row: dict[str, Any] = {
            "advisor_sid": str(r.get("advisor_sid")),
            "category": "EC",
            "category_source": str(r.get("category_source") or ""),
            "ytd_nnm": round(_num(r.get("ytd_nnm")), 2),
            "as_of_month": str(r.get("month_id")),
            "threshold_available": False,
            "threshold_amt": None, "gap": None, "qualifies": None,
            "rule_key": None, "note": None,
        }
        if resolved is None:
            row["note"] = ("no published plan rule states the NNM threshold yet — "
                           "upload/extract the plan document")
        elif "conflict" in resolved:
            row["note"] = ("multiple published rules state different NNM thresholds "
                           f"({resolved['conflict']}: {resolved['amounts']}) — "
                           "not resolvable without a human ruling")
        else:
            ytd = row["ytd_nnm"]
            thr = float(resolved["threshold_amt"])
            row.update({
                "threshold_available": True,
                "threshold_amt": thr,
                "gap": round(thr - ytd, 2),      # >0 = still short of the threshold
                "qualifies": ytd >= thr,          # YTD as of the stated month — NEVER annualised
                "rule_key": resolved["rule_key"],
            })
        out.append(row)
    return out


EXTRA_CATALOG: dict[str, dict] = {
    "advisor_nnm_position": {
        "description": "NNM position per category for an advisor (or the cohort): the LATEST "
                       "available month's MTD and YTD per advisor x category — YTD is the "
                       "position, never a sum of MTD rows. category_source is the raw file "
                       "prefix (EC confirmed by the plan document; NB/YI/FS inferred).",
        "params": [ADVISOR, _p("category", "EC|NB|YI|FS", required=False)],
        "returns": ["advisor_sid", "category", "category_source", "latest_month",
                    "mtd_nnm", "ytd_nnm", "as_of_dt"],
    },
    "advisor_nnm_all_categories": {
        "description": "All four NNM categories (EC/NB/YI/FS) plus a TOTAL row, MTD and YTD at "
                       "the latest available month, with the raw file prefix on each.",
        "params": [ADVISOR],
        "returns": ["category", "category_source", "label", "latest_month",
                    "mtd_nnm", "ytd_nnm", "advisor_count"],
    },
    "nnm_threshold_position": {
        "description": "Existing-Client YTD NNM against the plan's annual threshold: the YTD "
                       "figure, the month it is as of, the gap and whether it qualifies. The "
                       "threshold resolves from the published document-derived rule at read "
                       "time; with no such rule the position reports honestly without one. "
                       "NEVER annualises or extrapolates a partial year.",
        "params": [ADVISOR],
        "returns": ["advisor_sid", "category", "category_source", "ytd_nnm", "as_of_month",
                    "threshold_available", "threshold_amt", "gap", "qualifies",
                    "rule_key", "note"],
    },
}
