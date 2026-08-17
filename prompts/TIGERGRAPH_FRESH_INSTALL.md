# TigerGraph — Fresh Install

Nothing exists yet. This creates the schema only — no data. Roughly 10 minutes.

---

## Before you start

You need the TigerGraph host, a GSQL user with schema-creation rights, and the repo checked out in
the client environment.

The graph is called **`phx_dm_pce_practice_demo`**. All vertex and edge types are prefixed
`phx_dm_pce_`.

---

## Step 1 — Confirm nothing is already installed

```bash
gsql -g phx_dm_pce_practice_demo "ls"
```

**Expected:** an error saying the graph does not exist. That is what you want.

**If the graph already exists** with vertices in it, stop — this is not a fresh install. Use the
migration path in `CLIENT_ENV_RUNBOOK.md` Phase 1.2 instead, or the graph will be dropped.

---

## Step 2 — Install the schema, in this order

Three files, run one at a time so a failure is obvious:

```bash
cd <repo>

gsql docs/tigergraph/01_vertices.gsql
gsql docs/tigergraph/02_edges.gsql
gsql docs/tigergraph/03_create_graph.gsql
```

**What each does:**

| File | Creates |
|---|---|
| `01_vertices.gsql` | 31 vertex types |
| `02_edges.gsql` | 44 edge types |
| `03_create_graph.gsql` | The graph, listing every type |

**Run no migration afterwards.** These files already include everything from migrations 001 and 002
— the migrations exist only for environments installed at an earlier state.

---

## Step 3 — Verify

```bash
gsql -g phx_dm_pce_practice_demo "ls"
```

**Expected:**

```
Vertex Types: 31
Edge Types: 44
```

Then spot-check three that were added most recently:

```bash
gsql -g phx_dm_pce_practice_demo "ls vertex phx_dm_pce_job"
gsql -g phx_dm_pce_practice_demo "ls vertex phx_dm_pce_advisor"
gsql -g phx_dm_pce_practice_demo "ls vertex phx_dm_pce_product"
```

**Expected:**
- `phx_dm_pce_job` exists with `job_id`, `kind`, `stage`, `status`, `resume_token`
- `phx_dm_pce_advisor` includes **`job_code`**
- `phx_dm_pce_product` includes **`l1_pay_type_cd`** and **`l2_pay_type_cd`**

If any of those three is missing, the install used stale files — re-pull the repo and start again.

---

## Step 4 — Parity check

```bash
python3 scripts/verify_schema_parity.py
```

**Expected:** ends with

```
all checks passed — migrations (001, 002) == clean install (31 vertices / 44 edges)
```

This proves a freshly installed graph is identical to one built by migration, so environments cannot
silently differ.

**If it fails:** the failing line names the exact vertex, attribute or edge that differs. Fix the
named file and rerun. Never continue past a parity failure.

---

## Step 5 — Point the app at it

In `.env`:

```
GRAPH_CLIENT_MODE=real
TIGERGRAPH_HOST=<host, no port>
TIGERGRAPH_RESTPP_PORT=9000
TIGERGRAPH_GSQL_PORT=14240
TIGERGRAPH_GRAPH=phx_dm_pce_practice_demo
TIGERGRAPH_USERNAME=<user>
TIGERGRAPH_PASSWORD=<password>
DATA_DIR=data/real
```

Note `TIGERGRAPH_HOST` takes the host **without** a port — the ports are separate variables.

Then:

```bash
uvicorn app.api.main:app --host 0.0.0.0 --port 8002 &
curl -s localhost:8002/api/health
```

**Expected:** healthy JSON reporting **zero rows** for every vertex. Zero is correct — the schema
exists, no data is loaded yet.

**If health reports mock or tier-4 mode**, `GRAPH_CLIENT_MODE` did not take effect. A real-mode read
must fail loudly rather than silently serving local data.

---

## Done

Schema installed and the app connected to an empty graph.

**Next:** the data load, `CLIENT_ENV_RUNBOOK.md` Phase 3 onward — extract, validate, review gate,
load. Do not skip the Phase 4 review gate; loading millions of rows onto a bad extract is expensive
to unpick.

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `graph already exists` at step 2 | Not a fresh environment | Use the migration path, or `90_drop_all.gsql` first if the graph is genuinely disposable — **that destroys all data** |
| Vertex count is not 31 | One file failed silently | Rerun each file individually and read its output |
| `job_code` missing | Stale checkout | Re-pull; it was added in Round 1b |
| Parity check fails | DDL and migrations diverged | The failing line names the difference — fix that file |
| Health shows zero rows | **Correct at this stage** | Nothing to fix — data loads next |
| Health shows mock mode | `GRAPH_CLIENT_MODE` not applied | Check `.env` is being read; restart the server |
