"""Round A1 task 5 — top/bottom advisor ranking API. Owned by Subagent B.

Lives in its own router (not dashboard.py) so Subagents A and B never edit the
same file; the route path still sits under /api/dashboard per the spec.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/dashboard", tags=["ranking"])
