"""Round A1 task 4 — non-credited (9X) analysis API. Owned by Subagent B.

GET /api/noncredited/summary?month=          — causes table (the 9X card)
GET /api/noncredited/detail/{cause}?month=   — per-cause detail modal

``cause`` keys come from app/shared/reason_codes.py (household | inheritance |
discount | eligibility) — the ONE code→cause mapping. Each cause has its own
detail shape (a generic table would be useless); the router only maps cause →
query and never computes figures itself.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.graph.queries.catalog import CatalogError
from app.graph.queries.noncredited import run_noncredited_query
from app.shared.reason_codes import REASON_CODES

router = APIRouter(prefix="/api/noncredited", tags=["noncredited"])

# cause key -> its detail query (each cause has a DIFFERENT shape by design)
DETAIL_QUERIES = {
    "household": "noncredited_household_detail",
    "inheritance": "noncredited_inheritance_detail",
    "discount": "noncredited_discount_detail",
    "eligibility": "noncredited_eligibility_detail",
}


def _cause_meta(cause: str) -> dict:
    """The cause's 9X code + label/description (9X preferred over legacy codes)."""
    matches = sorted((code, m) for code, m in REASON_CODES.items()
                     if m["cause"] == cause)
    for code, m in matches:
        if code.startswith("9"):
            return {"reason_cd": code, **m}
    if matches:
        code, m = matches[0]
        return {"reason_cd": code, **m}
    return {"reason_cd": "", "cause": cause, "cause_label": cause, "description": ""}


def _run(query: str, month: str) -> dict:
    try:
        return run_noncredited_query(query, {"month_id": month})
    except CatalogError as exc:
        raise HTTPException(404 if "unknown month" in str(exc) else 400,
                            str(exc)) from exc


@router.get("/summary")
def summary(month: str = Query(...)) -> dict:
    result = _run("non_credited_by_cause", month)
    rows = result["rows"]
    total = {
        "account_count": sum(r["account_count"] for r in rows),
        "trade_count": sum(r["trade_count"] for r in rows),
        "value": round(sum(r["value"] for r in rows), 2),
        # distinct advisors across causes cannot be summed from the rows —
        # honest max lower bound would mislead; the UI shows per-cause counts
    }
    return {"month": month, "rows": rows, "total": total,
            "note": "Non-credited transactions are loaded with their reason code "
                    "so causes can be analysed, but are excluded from every "
                    "credited revenue figure."}


@router.get("/detail/{cause}")
def detail(cause: str, month: str = Query(...)) -> dict:
    query = DETAIL_QUERIES.get(cause)
    if query is None:
        raise HTTPException(
            404, f"unknown cause '{cause}' — expected one of "
                 f"{', '.join(sorted(DETAIL_QUERIES))}")
    result = _run(query, month)
    meta = _cause_meta(cause)
    return {"month": month, "cause": cause, "reason_cd": meta["reason_cd"],
            "cause_label": meta["cause_label"], "description": meta["description"],
            "rows": result["rows"], "row_count": result["row_count"]}
