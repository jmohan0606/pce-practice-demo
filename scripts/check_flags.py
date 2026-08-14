"""Round A2B task 7 — feature-flag verification.

Checks (each prints PASS/FAIL, exits non-zero on any failure):
 1. 26 flags served, ceiling 30, all on by default
 2. turning a flag off without a reason -> 400
 3. the numeric guardrail cannot be turned off -> 400
 4. flag off -> gated endpoint 409 AND zero graph queries ran for it
 5. parent off -> child effective_enabled false, gated child endpoint 409
 6. preset application: one history entry naming the preset; states set
 7. restart persistence: a flag set off in one process reads back off in a NEW
    process (fresh interpreter over the same SQLite file)
 8. history records flag, on/off, who, when, reason

Uses an isolated flags DB (scratch) so the app's real state is untouched.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def main() -> int:
    db = os.environ.setdefault(
        "PCE_FLAGS_DB_PATH",
        os.path.join(tempfile.mkdtemp(prefix="pce_flags_check_"), "flags.db"))
    from fastapi.testclient import TestClient

    from app.api.main import app

    client = TestClient(app)

    r = client.get("/api/flags")
    body = r.json()
    check("1. flag inventory", r.status_code == 200 and body["total"] == 26
          and body["ceiling"] == 30 and body["on_count"] == 26,
          f"total={body.get('total')} on={body.get('on_count')}")

    r = client.patch("/api/flags/dashboard.noncredited", json={"enabled": False})
    check("2. reason required to turn off", r.status_code == 400,
          f"status={r.status_code}")

    r = client.patch("/api/flags/global.numeric_guardrail",
                     json={"enabled": False, "reason": "attempt"})
    check("3. guardrail immutable", r.status_code == 400, f"status={r.status_code}")

    # 4. off => 409 and ZERO queries ran: count the graph client's query log
    # via a wrapped run_query — the dependency must fire before any query.
    from app.graph.client import get_graph_client

    graph = get_graph_client()
    counted = {"n": 0}
    original = graph.run_query

    def counting(name, params):  # noqa: ANN001
        counted["n"] += 1
        return original(name, params)

    graph.run_query = counting
    try:
        r = client.patch("/api/flags/dashboard.noncredited",
                         json={"enabled": False, "reason": "check 4", "by": "check"})
        assert r.status_code == 200, r.text
        counted["n"] = 0
        r = client.get("/api/noncredited/summary?month=202605")
        gated = r.status_code == 409 and r.json()["detail"]["feature_disabled"] == "dashboard.noncredited"
        check("4. off => 409 before any query", gated and counted["n"] == 0,
              f"status={r.status_code} queries_ran={counted['n']}")
    finally:
        graph.run_query = original

    # 5. parent off => child effectively off; child endpoint 409
    r = client.patch("/api/flags/dashboard.table",
                     json={"enabled": False, "reason": "check 5", "by": "check"})
    assert r.status_code == 200
    flags = {f["key"]: f for f in client.get("/api/flags").json()["flags"]}
    child = flags["dashboard.table.top_bottom"]
    r2 = client.get("/api/dashboard/product/managed_fees/ranking?from=202604&to=202605")
    check("5. child inherits parent state",
          child["enabled"] and not child["effective_enabled"] and r2.status_code == 409,
          f"child enabled={child['enabled']} effective={child['effective_enabled']} "
          f"endpoint={r2.status_code}")

    # 6. preset: one history entry naming the preset
    before = len(client.get("/api/flags/history").json()["history"])
    r = client.post("/api/flags/preset/client_demo", json={"by": "check"})
    hist = client.get("/api/flags/history").json()["history"]
    flags = {f["key"]: f for f in r.json()["flags"]}
    check("6. preset applies with ONE history entry",
          r.status_code == 200 and len(hist) == before + 1
          and "Client Demo" in hist[0]["reason"]
          and not flags["global.trace"]["enabled"]
          and not flags["advisor.crm_opportunities"]["enabled"]
          and not flags["global.chat"]["enabled"]
          and flags["dashboard.noncredited"]["enabled"],
          f"entries={len(hist) - before} top={hist[0]['reason'][:40]!r}")

    # 7. restart persistence — set off here, read back in a NEW process
    r = client.patch("/api/flags/global.export",
                     json={"enabled": False, "reason": "check 7 persistence",
                           "by": "check"})
    assert r.status_code == 200
    code = (
        "import os,sys\n"
        f"os.environ['PCE_FLAGS_DB_PATH']={db!r}\n"
        "from app.flags.store import get_flag_store\n"
        "s=get_flag_store()\n"
        "sys.exit(0 if (not s.enabled('global.export') and "
        "s.flag_note('global.export')['reason']=='check 7 persistence') else 1)\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=os.getcwd(),
                          capture_output=True, text=True)
    check("7. state survives a process restart", proc.returncode == 0,
          proc.stderr.strip()[-120:] if proc.returncode else "")

    # 8. history shape
    hist = client.get("/api/flags/history").json()["history"]
    row = hist[0]
    check("8. history records flag/on-off/who/when/reason",
          all(k in row for k in ("when", "flag", "enabled", "by", "reason"))
          and row["by"] == "check",
          str({k: row[k] for k in ("flag", "enabled", "by")}))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("check_flags: 8/8 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
