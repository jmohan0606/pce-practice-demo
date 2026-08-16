# Round 1 — Schema Freeze and Client Environment Runbook

**The purpose of this round is to make the TigerGraph schema final**, so the operator can install it
in the client environment and begin loading millions of rows while later rounds continue here
without forcing another migration.

Everything in this round is schema, migration, and written instructions. **Behaviour changes come in
Round 2, UI in Round 3** — neither touches the schema.

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_F2_COMPLETE.md`, then this document, then
`docs/spec/REVIEW_COMMENTS_BATCH1_DASHBOARD.md` and `docs/spec/REVIEW_COMMENTS_BATCH2.md` — those
two record what Rounds 2 and 3 will need, and this round must not foreclose any of it.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Ports:** 8002 backend, 3002 frontend. **Session cost ceiling: $6**, stop and report at $4.
Project total ≈ $10.50 plus F2.

**No subagents this round.** It is one coherent change across a small number of files, and parallel
agents would each rebuild the same context for no gain. Run sequentially in the main thread.

---

## Task 1 — Rule vertex: exception configuration

The exceptions model agreed in design. All of it lands on the rule as attributes so no later round
needs a schema change.

```sql
ALTER VERTEX phx_dm_pce_rule ADD ATTRIBUTE (
  driver_enabled BOOL,           -- default true
  exception_enabled BOOL,        -- default false
  exception_denominator STRING,  -- what the rate is measured against
  exception_floor DOUBLE,        -- below this an advisor is suppressed as noise
  exception_floor_unit STRING,   -- accounts | revenue
  exception_sensitivity DOUBLE,  -- multiple of the cohort median, e.g. 2.0
  product_scope STRING,          -- comma-separated group_ids, or "" for all
  product_scope_source STRING    -- the citation, or "NOT STATED"
);
```

### Why each exists — do not simplify these away

**`driver_enabled` and `exception_enabled` are independent.** A rule can explain a movement and yet
be a poor exception. `NEW_BILLING` accounts for $8,383 of a change — useful as a driver — but
accounts beginning to bill is normal business, not a problem. One toggle would force losing the
explanation to remove the noise.

**`exception_denominator` makes the exception a rate, not a count.** An advisor with 500 accounts and
12 above the discount threshold is at 2.4%; one with 30 accounts and 8 above is at 26.7%. Ranking by
count puts the first one top and sends someone to a conversation that is not warranted. The
denominator differs per rule — discount sharing is per managed account, lost accounts is better
measured against prior-month revenue, because losing 3 accounts worth $40k matters more than 20
worth $2k.

**`exception_floor` suppresses noise.** 2 of 8 accounts is 25% and would top every rate ranking while
meaning nothing.

**`exception_sensitivity` replaces an invented threshold.** Instead of picking "$1,000" or "5
accounts", an advisor surfaces when their rate sits materially above the cohort distribution. The
number comes from the data rather than from us — which is what makes it defensible to a comp team.

**`product_scope` is in the documents already.** The plan states discount sharing applies *only to
products on the Standard Managed 145bps Fee Schedule*. So scope is extracted, not configured. It
also narrows the denominator: 8 of 30 *managed* accounts is 26.7%, not 8 of 500 total at 1.6%. Using
the wrong denominator would make every advisor look fine.

### Defaults

Three rules ship with `exception_enabled = true`: fee reduction above threshold, discount sharing not
applied, lost accounts. Everything else defaults to `driver_enabled = true, exception_enabled = false`.

### The extractor proposes, never invents

Extend the Rule Extractor's output schema so it proposes `exception_denominator`, `exception_floor`,
`product_scope` and their citations from the rule's own language. Where the document states nothing,
emit `null` with `product_scope_source = "NOT STATED"` — **a null is honest, a guessed number is not.**

**This round only adds the fields and the extractor's proposal.** The UI to edit them is Round 3; the
evaluation that uses them is Round 2.

---

## Task 2 — Job vertex: resumable long-running work

```sql
CREATE VERTEX phx_dm_pce_job (
  PRIMARY_ID job_id STRING,
  kind STRING,              -- document_ingest | insight_generation | data_load
  scope_key STRING,         -- which document, advisor, or entity
  stage STRING,             -- the current stage name
  stage_index INT,
  stage_total INT,
  items_done INT,
  items_total INT,
  status STRING,            -- RUNNING | INTERRUPTED | COMPLETE | FAILED
  resume_token STRING,      -- opaque: enough to restart the current stage
  error STRING,
  started_at DATETIME,
  updated_at DATETIME,
  completed_at DATETIME
) WITH primary_id_as_attribute="true";

CREATE DIRECTED EDGE phx_dm_pce_job_for_document (FROM phx_dm_pce_job, TO phx_dm_pce_document)
  WITH REVERSE_EDGE="phx_dm_pce_document_has_job";
CREATE DIRECTED EDGE phx_dm_pce_job_for_run (FROM phx_dm_pce_job, TO phx_dm_pce_insight_run)
  WITH REVERSE_EDGE="phx_dm_pce_run_has_job";
```

Stages per kind:

| Kind | Stages |
|---|---|
| `document_ingest` | parse → chunk → embed → extract → compile → audit |
| `insight_generation` | evaluate_rules → investigate_residual → narrate → persist |
| `data_load` | one stage per entity |

**Each stage writes its output before the next begins.** That is the whole mechanism — interrupted
during extraction, parse/chunk/embed are already on disk and are not repeated.

**Granularity:** per-item within `extract` and `investigate_residual` (the slow stages, where losing
progress hurts); per-stage elsewhere.

**Resume is explicit.** An interrupted job shows `INTERRUPTED` with a Resume action. Automatic
resumption on page load would surprise the user and could double-spend.

This round creates the vertex and writes job rows from the existing pipelines. **The progress UI is
Round 3.**

---

## Task 3 — Migration script, not just DDL

The operator may already have installed the schema before this round lands. **A full reinstall would
drop loaded data**, so produce the delta.

`docs/tigergraph/migrations/001_exceptions_and_jobs.gsql`:
- `ALTER VERTEX phx_dm_pce_rule ADD ATTRIBUTE (...)` — the eight fields
- `CREATE VERTEX phx_dm_pce_job (...)`
- the two job edges
- **no `DROP`, no data-touching statement anywhere**

Also update `01_vertices.gsql` and `02_edges.gsql` for a clean install, and `schema_catalog.json`,
`data/manifest.json`, `scripts/generate_mock_data.py` and `docs/spec/SCHEMA_SPEC.md` per the
seven-place checklist.

`scripts/verify_schema_parity.py`: assert the migration applied to a fresh install produces exactly
the same schema as `01_vertices.gsql`. If those two ever diverge, one environment silently differs
from another.

---

## Task 4 — Source-to-vertex traceability

`docs/spec/SOURCE_TO_VERTEX_MATRIX.md`. **Three source kinds, not one** — this is why a
PostgreSQL-only extraction plan would be incomplete:

| Source | Kind | Vertex |
|---|---|---|
| `fpic_daily_trade_details_tb_prod` | PostgreSQL | `revenue_transaction`; `monthly_revenue` and `rpg` derived from it |
| `product_hierarchy` | PostgreSQL | `product` |
| `fpic_prm_rr_tb` + `fpic_employee_tb` | PostgreSQL | `advisor` |
| `fpic_acct_tb_pm` | PostgreSQL | `account` |
| `fpic_rr_changes_from_nacs_logs` | PostgreSQL | `account_transfer` |
| `fpic_monthly_acct_balance_tb_april/_may/_june` | PostgreSQL | `account_month` |
| `fpic_acct_eci_rel_tb_pm` | PostgreSQL | `account_eci_rel`; `household` derived |
| `fpic_acct_eci_map_tb` | PostgreSQL | `account_eci_map` |
| `fpic_team_agreement_tb` | PostgreSQL | `team_agreement` |
| `fpic_daily_adv_flows_tb_pm` | PostgreSQL | `advisor_flow_month` |
| **ECNNM / NBNNM / YINNM / FSNNM `.txt`** | **flat files** | `advisor_nnm` |
| **CRM opportunity export `.csv`** | **flat file** | `opportunity` |
| seeded constants | none | `product_group`, `revenue_class`, `month` |

Twelve app-written vertices are never extracted: `document`, `document_chunk`, `rule`,
`rule_set_version`, `insight_run`, `finding`, `evidence_row`, `agent_query_log`, `agent_turn_log`,
`conversation`, `chat_message`, `feature_flag`, and now `job`.

---

## Task 5 — Chunked, resumable PostgreSQL extraction

**This is the task that most affects whether the client load succeeds.**

Two hard constraints in the client environment:

1. **A 900-second statement timeout.** A single query over four months of
   `fpic_daily_trade_details_tb_prod` — potentially 15M+ rows — will exceed it. Not a maybe.
2. **A 30-minute IAM token.** Even a query that completes will lose its session on a long extract.

**So never issue one query for everything.**

`scripts/extract_chunked.py`:

- Chunk by **month × advisor batch** (default 200 advisors). Each chunk is its own query and its own
  CSV: `raw_txn_202604_b001.csv`.
- **A checkpoint file records every completed chunk.** On token expiry the script exits cleanly with
  a clear message; after the operator refreshes, rerunning resumes at the first uncompleted chunk —
  never from the start.
- `--dry-run` prints the chunk plan and estimated row counts without extracting.
- `--resume` is the default; `--restart` requires an explicit flag.
- Every chunk logs rows, wall time, and its output path.

**Extraction and ingestion are decoupled.** Extract everything to CSV, validate, *then* load. If they
interleave, a PostgreSQL failure leaves the graph half-populated with no way to tell what is missing.

`scripts/validate_raw_extracts.py` — run before any loading:
- every expected chunk present, no gaps in the sequence
- row counts per month against the manifest
- `RAW_CONTRACT` column check on every file
- account keys normalised, no leading zeros
- `reason_cd` is `__NONE__` where blank, never an empty string
- unmapped product codes listed with counts
- **the sanity anchor**: roughly $33k per advisor per month firmwide — an order of magnitude out
  means `proc_dt` was used instead of `trade_dt`, or the team-agreement join fanned out

---

## Task 6 — The client environment runbook

`docs/CLIENT_ENV_RUNBOOK.md`. **Written so the operator can follow it without re-deriving anything**,
numbered, with the exact command at each step and what a correct result looks like.

It must cover, in order:

**Phase 0 — before anything**
- Which Copilot prompt to run first (`COPILOT_SIZING_AND_RATE.md` Part A — row counts, pure SQL, no
  TigerGraph needed) and why: chunk sizing depends on whether trades are 3M or 15M
- Preflight: cdao chat with blank `api_version` / `temperature=1` / no `max_tokens`; embedding
  dimension observed **before any document is indexed**; `check_cache_support.py`
- Package availability from the client artifactory

**Phase 1 — schema**
- Install order: `01_vertices` → `02_edges` → `03_create_graph`
- Or, if already installed: `migrations/001_exceptions_and_jobs.gsql`
- GSQL V1 constraints — parameter order is `TYPE name`; traversal targets must be vertex types with
  edge aliases; multi-hop patterns split into single-hop SELECTs
- Verify with `verify_schema_parity.py`

**Phase 2 — measure before loading**
- `COPILOT_SIZING_AND_RATE.md` Part B: measure the real ingestion rate against live TigerGraph.
  **Do not estimate it.** Everything measured so far was the local store in a Codespace; the client
  writes over RESTPP across a network where per-batch latency dominates.
- Project the load window from the measured p95 plus 20% overhead

**Phase 3 — extract**
- `extract_chunked.py`, with the resume procedure on token expiry stated explicitly
- The two flat-file sources: four NNM `.txt` files, CRM `.csv` — **these are not PostgreSQL and are
  easy to forget**
- `validate_raw_extracts.py`

**Phase 4 — REVIEW GATE**
- **Stop here.** Send the validation output to the operator for review before loading.
- Loading millions of rows on top of a bad extract wastes hours and is hard to unpick.

**Phase 5 — load**
- `build_real_data.py` → `load_real_data.py` → `verify_real_data.py`
- Resume behaviour on interruption
- Reconciliation: monthly totals recomputed independently from the transaction CSVs

**Phase 6 — smoke test**
- Health, the 38 catalog queries executed against live TigerGraph and diffed against the local store,
  each screen loading, one insight generated end to end

Every phase states **what "correct" looks like** and **what to do when it is not.**

---

## Task 7 — Verify

```
1. migration applies to a schema already installed at F2 state, without touching data
2. verify_schema_parity passes — migration result == clean install
3. all eight rule fields present; extractor proposes them with citations, null where not stated
4. three rules default to exception_enabled=true; everything else driver-only
5. job vertex written by document ingest and insight generation, with stage and counts
6. an interrupted document ingest resumes at the correct stage without repeating earlier ones
7. extract_chunked --dry-run prints a chunk plan; --resume skips completed chunks
8. validate_raw_extracts catches a deliberately corrupted chunk
9. SOURCE_TO_VERTEX_MATRIX lists all three source kinds and every vertex
10. CLIENT_ENV_RUNBOOK is followable start to finish with no gaps
```

Write `docs/ROUND_1_COMPLETE.md` with actual output, commit, and leave both servers running on
public forwarded URLs.

---

## Not in this round

- **Round 2 — behaviour:** aggregate-first queries, evidence without cap, exception evaluation using
  these fields, AI Insights cross-cutting, driver descriptions
- **Round 3 — UI:** both review batches, the Documents & Rules redesign, job progress indicators
