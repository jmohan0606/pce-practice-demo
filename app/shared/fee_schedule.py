"""Round C (docs/rules) task 1.3 — the standard managed fee schedule, pinned.

Copilot's transcription of the four real plan documents
(docs/spec/PLAN_EXPECTATIONS_FINDINGS.md, resolved in DECISIONS.md 2026-08-12)
confirmed **145 bps is THE standard managed fee schedule** — it appears three
times as the schedule itself. The 115 bps figure appears exactly once, inside a
worked example, and is NOT a schedule rate.

Anything in this codebase that references a standard managed rate imports
STANDARD_MANAGED_FEE_BPS from here. 115 may appear only inside illustrative
text clearly labelled as a worked example (never as a constant).
"""
from __future__ import annotations

# The standard managed fee schedule, in basis points.
STANDARD_MANAGED_FEE_BPS: float = 145.0

# Where the 145 bps figure is stated as the schedule in the client's documents.
STANDARD_MANAGED_FEE_CITATIONS: tuple[dict, ...] = (
    {"doc": "2026 Changes FAQ", "page": 13, "note": "states the standard managed fee schedule"},
    {"doc": "PCA plan document", "page": 3, "note": "states the standard managed fee schedule"},
    {"doc": "SAG plan document", "page": 4, "note": "states the standard managed fee schedule"},
)

# The one place a different figure legitimately appears: FAQ p.15's worked
# example uses 115 bps as an ILLUSTRATIVE rate. It is not a schedule rate and
# must never be used as one — no constant is exported for it by design.
WORKED_EXAMPLE_NOTE = (
    "115 bps appears once, in the FAQ p.15 worked example, as an illustrative "
    "rate only — labelled example text may quote it; code must not."
)
