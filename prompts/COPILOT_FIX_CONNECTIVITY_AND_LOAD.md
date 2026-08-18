# Copilot — Fix TigerGraph Connectivity, Then Load

**Phase 1 failed completely. Nothing was written to the graph.** Do not retry the load until the
connectivity cause is found and fixed.

Working directory:

```powershell
cd C:\Users\R757680\ds\workspace\pce-practice-demo-main
```

---

## What the failure actually says

```
vertex upsert for phx_dm_pce_month was served by the LOCAL FALLBACK tier,
not TigerGraph (GRAPH_CLIENT_MODE=real) — the write did NOT land in the real graph.
```

Every entity failed the same way. **`GRAPH_CLIENT_MODE=real` is set, but writes are being served by
the local fallback store instead of TigerGraph.**

The loader refusing rather than silently writing to the wrong place is **correct behaviour** — a
silent local write would have produced a "successful" load with an empty graph.

This also explains the 24.6 GB memory: rows were buffering for a destination that never accepted
them. **Memory was a symptom, not the cause. Do not tune memory.**

### A second, separate bug

```
advisor: failed at row 1: Required column advisor_sid is empty
```

`data/real/vertices/phx_dm_pce_advisor.csv` has a blank `advisor_sid` on row 1. Most likely the
`__UNATTRIBUTED__` synthetic advisor was written with an empty SID instead of the literal
`__UNATTRIBUTED__`. **This must be fixed too — it is independent of connectivity.**

---

# PART A · The root cause — already identified

**The wrong environment variable family is set.** No diagnosis needed; verify and fix.

`app/graph/tiered_client.py` line 228:

```python
self.host = (settings.tg_host or settings.tigergraph_host or "http://127.0.0.1").rstrip("/")
```

The real client uses the **`TG_*`** family. `TIGERGRAPH_*` is only a partial fallback — it covers the
host but **not the ports, username or password at all**. With `TG_HOST` unset the client defaults to
`http://127.0.0.1`, cannot connect, and falls through to the local store. That is exactly what
phase 1 reported for all 18 entities.

## A1 · Confirm it

```powershell
uv run python -c "
from app.config.settings import get_settings
s = get_settings()
for k in ('graph_client_mode','tg_host','tg_graphname','tg_username',
          'tg_restpp_port','tg_gs_port','tg_ssl_port','tg_use_ssl','tigergraph_host'):
    v = getattr(s, k, 'MISSING')
    print(f'{k} = {v!r}')
"
```

**If `tg_host` reads `http://127.0.0.1`, the diagnosis is confirmed.**

## A2 · Set the correct variables in `.env`

```
GRAPH_CLIENT_MODE=real
TG_HOST=<hostname — NO PORT>
TG_GRAPHNAME=phx_dm_pce_practice_demo
TG_USERNAME=<user>
TG_PASSWORD=<password>
TG_RESTPP_PORT=9000
TG_GS_PORT=14240
TG_SSL_PORT=443
TG_USE_SSL=<true or false, matching the server>
```

**`TG_HOST` must not include a port.** The ports are separate variables, and a host carrying one
produces a doubled port — a known failure in this project.

Use the **same host, username and password that `gsql` already uses successfully from this machine**,
since the schema was installed from here. If `.env` currently sets `TIGERGRAPH_HOST`,
`TIGERGRAPH_USER` and `TIGERGRAPH_PASS`, those values are the ones to copy across; leave them in
place as well.

## A3 · Prove the client is real — before loading anything

```powershell
uv run python -c "
from app.graph.client import get_graph_client
g = get_graph_client()
print('client class:', g.__class__.__name__)
"
```

**The class must be the TigerGraph client, not a foundation or local store.** If it is still local,
**stop and report** — do not start the load.

## A4 · Prove a real write lands

Load only `month` — 3 rows — then check with GSQL:

```powershell
gsql -g phx_dm_pce_practice_demo "SELECT count(*) FROM phx_dm_pce_month"
```

**Must return 3.** If it returns 0, the fix did not work — **stop and report.** Do not start a
144M-row load on an unproven connection; that is what the last failed attempt cost.

---

# PART C · Fix the blank advisor_sid

```powershell
uv run python -c "
import csv
rows = list(csv.DictReader(open('data/real/vertices/phx_dm_pce_advisor.csv', newline='', encoding='utf-8-sig')))
blank = [i for i, r in enumerate(rows) if not (r['advisor_sid'] or '').strip()]
print('rows:', len(rows), 'blank advisor_sid at indices:', blank[:10])
for i in blank[:3]:
    print({k: rows[i][k] for k in list(rows[i])[:6]})
"
```

If the blank row is the synthetic advisor, its `advisor_sid` must be the literal `__UNATTRIBUTED__`.

**Fix the row in the CSV. Do not delete it** — firm-wide figures depend on it, and its absence would
drop 4,136,967 transactions from every firm total.

If the blank row is something else, **report what it is before changing anything.**

---

# PART D · Run the load

Only after Part B proves a real write lands and Part C is fixed.

```powershell
uv run python -u scripts\load_real_data.py --data-dir data\real --max-parallel 3
```

**Run this from a standalone PowerShell window, not the IntelliJ terminal.** The IDE terminal hung on
this load's output volume once already.

### Entity-by-entity within a phase, in parallel — this is what the flag does

`--max-parallel 3` loads **three entities concurrently within a phase**, exactly as V2 did. Phase 1
is all 18 vertex entities; phase 2 is all 31 edge entities.

**Do not raise it above 3.** A partial failure at higher concurrency leaves the graph inconsistent in
ways that are hard to unpick, and the gain is perhaps 30 minutes on a 3-hour job.

A phase-2 entity refusing to start while phase 1 is incomplete is **correct behaviour**, not an
error — edges loaded before their vertices become dangling and vanish silently.

### While it runs

Watch memory. It should now stay **low** — the 24.6 GB happened only because rows buffered for a
destination that never accepted them. **If it climbs past 10 GB again, stop and report**: that would
mean writes are still not landing.

Confirm rows are arriving:

```powershell
gsql -g phx_dm_pce_practice_demo "SELECT count(*) FROM phx_dm_pce_revenue_transaction"
```

### Report

At the end of phase 1: elapsed time and rows loaded. At the end of phase 2: the same. Nothing in
between.

If interrupted, rerun the identical command — checkpoints skip completed entities.
**Never pass `--fresh`**; it discards all completed work.

---

# PART E · Reconcile

```powershell
uv run python scripts\reconcile_load.py --raw data\real\_raw --data-dir data\real
```

Paste the complete output.

---

## Rules

1. **Do not start the full load until Part B proves a real write lands.**
2. **Two identical failures = stop and report.** Never a third attempt.
3. **Do not tune memory.** The 24.6 GB was a symptom of failed writes.
4. **Never estimate a number** — every figure comes from a command that ran.
5. **Never delete a row to make a check pass.**
6. All paths repo-relative; never search the C: drive.
