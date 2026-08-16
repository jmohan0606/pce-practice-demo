"""Round F2 task 3 — CRM opportunity catalog queries (Subagent A's module).

catalog.py imports this at the end of its own module load and merges
EXTRA_CATALOG into CATALOG; @mock_query implementations register on import.
Import shared helpers from catalog (its top-level names are fully defined by
the time this module loads). GSQL twins live under docs/tigergraph/queries/.

Queries this module must provide (spec Task 3):
  advisor_pipeline · household_opportunities · pipeline_by_stage ·
  stalled_opportunities

HONESTY CONSTRAINTS (spec §2): no Won/Lost status exists or is derived;
ai_read is descriptive text only — it may be RETURNED on detail rows but may
never be aggregated, filtered on, or drive any figure.
"""
from __future__ import annotations

EXTRA_CATALOG: dict[str, dict] = {}
