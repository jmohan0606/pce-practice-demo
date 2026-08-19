"""Round F2 task 4 — advisor NNM position API.

GET /api/advisor/{sid}/nnm — the four real NNM categories (EC/NB/YI/FS) at
their latest available month, MTD + YTD, a total, and the Existing-Client
position against the plan's annual threshold.

Honesty rules carried from the spec:
- YTD is the latest month's running figure from the feed — never a sum of
  MTD rows, never annualised or extrapolated.
- Only EC is confirmed as a category by the plan document ("Existing Client
  Annual NNM Flows"); NB/YI/FS are inferred from filenames — confirmed=false
  with category_source (the raw file prefix) for the UI tooltip.
- The dollar threshold resolves from the published document-derived rule at
  read time (no constant in code — check 13); with no such rule the position
  is reported without one and the reason is named.
- An advisor with no NNM rows gets categories=[] and a note — never zeros
  pretending to be data.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.flags.registry import require_feature
from app.graph.queries.catalog import CatalogError, run_catalog_query
from app.graph.queries.nnm_catalog import NNM_CATEGORY_LABELS
from app.shared.logging import get_logger

_log = get_logger("app.api.nnm")

router = APIRouter(prefix="/api/advisor", tags=["nnm"])

# Only EC's meaning is stated by the plan document; the other three labels are
# working names inferred from the file prefixes.
_CONFIRMED = {"EC"}

ASSUMED_NOTE = ("the plan document's award table is titled 'Existing Client "
                "Annual NNM Flows' — EC is assumed to be the measured category "
                "until the client confirms")


def _month_label(month_id: str | None) -> str | None:
    if not month_id:
        return None
    from app.graph.queries import lookups

    row = lookups.month_row(month_id)
    if row and row.get("month_name"):
        return str(row["month_name"])
    return month_id


@router.get("/{sid}/nnm",
            dependencies=[Depends(require_feature("advisor.chart_metrics"))])
def advisor_nnm(sid: str) -> dict:
    try:
        cat_rows = run_catalog_query("advisor_nnm_all_categories", {"advisor": sid})["rows"]
        thr_rows = run_catalog_query("nnm_threshold_position", {"advisor": sid})["rows"]
    except CatalogError as exc:
        raise HTTPException(400 if "unknown advisor" not in str(exc) else 404,
                            str(exc)) from exc

    categories = []
    total = None
    for r in cat_rows:
        if r["category"] == "TOTAL":
            total = {"mtd_nnm": r["mtd_nnm"], "ytd_nnm": r["ytd_nnm"]}
            continue
        categories.append({
            "category": r["category"],
            "label": NNM_CATEGORY_LABELS.get(r["category"], r["category"]),
            "category_source": r["category_source"],
            "confirmed": r["category"] in _CONFIRMED,
            "latest_month": r["latest_month"],
            "mtd_nnm": r["mtd_nnm"],
            "ytd_nnm": r["ytd_nnm"],
        })

    as_of_month = max((c["latest_month"] for c in categories), default=None)
    # the file-level as-of date rides every stored row; surface the EC one
    as_of_dt = None
    pos_rows = run_catalog_query("advisor_nnm_position", {"advisor": sid})["rows"]
    if pos_rows:
        as_of_dt = max(r.get("as_of_dt") or "" for r in pos_rows) or None

    thr = thr_rows[0] if thr_rows else None
    threshold = {
        "available": False, "threshold_amt": None, "rule_key": None,
        "measured_category": "EC", "assumed": True, "assumed_note": ASSUMED_NOTE,
        "ytd_nnm": None, "gap": None, "qualifies": None, "as_of_month": None,
        "note": None,
    }
    if thr is None:
        threshold["note"] = ("no Existing-Client NNM rows exist for this advisor — "
                             "no position to measure")
    else:
        threshold.update({
            "available": bool(thr.get("threshold_available")),
            "threshold_amt": thr.get("threshold_amt"),
            "rule_key": thr.get("rule_key"),
            "ytd_nnm": thr.get("ytd_nnm"),
            "gap": thr.get("gap"),
            "qualifies": thr.get("qualifies"),
            "as_of_month": thr.get("as_of_month"),
            "note": thr.get("note"),
        })

    out = {
        "advisor_sid": sid,
        "as_of_month": as_of_month,
        "as_of_label": _month_label(as_of_month),
        "as_of_dt": as_of_dt,
        "categories": categories,
        "total": total,
        "threshold": threshold,
    }
    if not categories:
        out["note"] = ("no NNM rows are loaded for this advisor — the four "
                       "category files carry no rows for this SID")
    return out
