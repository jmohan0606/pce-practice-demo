from __future__ import annotations

"""Per-request tier usage log for the 4-tier GraphClient adapter.

Every served graph request records WHICH tier actually handled it:
    Tier 1 — tigergraph-mcp (stdio MCP server, agent-initiated access)
    Tier 2 — pyTigerGraph direct
    Tier 3 — RESTPP direct (RealGraphClient)
    Tier 4 — local store (MockGraphClient over the CSV-backed FoundationGraphStore)

The log is process-local, thread-safe, stdlib-only (no SDK imports — safe to
import from anywhere, including the mock path). The Admin/Data Health page
reads it through AdapterStatusService -> /adapters/status -> "tier_usage".
"""

import threading
import time
from collections import Counter, deque
from typing import Any

TIER_NAMES: dict[int, str] = {
    1: "tigergraph-mcp",
    2: "pytigergraph",
    3: "restpp",
    4: "mock",
}


class TierUsageLog:
    """Thread-safe counters + ring buffer of the most recent tier decisions."""

    def __init__(self, max_recent: int = 200) -> None:
        self._lock = threading.Lock()
        self._served: Counter[str] = Counter()
        self._errors: Counter[str] = Counter()
        self._recent: deque[dict[str, Any]] = deque(maxlen=max_recent)
        self._total_served = 0
        # Guard so MockGraphClient/RealGraphClient (which also self-record when
        # used directly in mock/legacy modes) don't double-record when they are
        # being driven as tiers inside TieredGraphClient._dispatch.
        self._local = threading.local()

    # --- dispatch guard -------------------------------------------------
    def dispatch_active(self) -> bool:
        return bool(getattr(self._local, "active", False))

    def enter_dispatch(self) -> None:
        self._local.active = True

    def exit_dispatch(self) -> None:
        self._local.active = False

    # --- recording ------------------------------------------------------
    @staticmethod
    def _key(tier: int) -> str:
        return f"tier{tier}:{TIER_NAMES.get(tier, str(tier))}"

    def record(
        self,
        tier: int,
        operation: str,
        target: str,
        ok: bool,
        duration_ms: float,
        error: str | None = None,
        fallback_from: list[str] | None = None,
    ) -> None:
        with self._lock:
            key = self._key(tier)
            if ok:
                self._served[key] += 1
                self._total_served += 1
            else:
                self._errors[key] += 1
            self._recent.append(
                {
                    "ts": round(time.time(), 3),
                    "tier": tier,
                    "tier_name": TIER_NAMES.get(tier, str(tier)),
                    "operation": operation,
                    "target": target,
                    "ok": ok,
                    "duration_ms": round(duration_ms, 2),
                    "error": error,
                    # tiers that were tried and failed before this one served
                    "fallback_from": fallback_from or [],
                }
            )

    # --- reading (Admin page) --------------------------------------------
    def summary(self, recent: int = 25) -> dict[str, Any]:
        with self._lock:
            return {
                "total_served": self._total_served,
                "served_by_tier": dict(self._served),
                "errors_by_tier": dict(self._errors),
                "recent_requests": list(self._recent)[-recent:],
            }


_log = TierUsageLog()


def get_tier_log() -> TierUsageLog:
    return _log
