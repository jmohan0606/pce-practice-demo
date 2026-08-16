"""Round F2 task 4.3 — advisor NNM catalog queries (Subagent B's module).

catalog.py imports this at the end of its own module load and merges
EXTRA_CATALOG into CATALOG; @mock_query implementations register on import.
Import shared helpers from catalog (its top-level names are fully defined by
the time this module loads). GSQL twins live under docs/tigergraph/queries/.

Queries this module must provide (spec Task 4.3):
  advisor_nnm_position · advisor_nnm_all_categories · nnm_threshold_position

HONESTY CONSTRAINTS: the YTD position is the LATEST available month's
ytd_nnm, never a sum of MTD rows; nnm_threshold_position NEVER annualises or
extrapolates, and its threshold resolves from the EXTRACTED plan rule at read
time — no dollar threshold constant may live in this file (check 13).
"""
from __future__ import annotations

EXTRA_CATALOG: dict[str, dict] = {}
