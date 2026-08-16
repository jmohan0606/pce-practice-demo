# Round 1 — COMPLETE (docs/spec/ROUND_1_SCHEMA_FREEZE_SPEC.md)

**The schema is final: 31 vertices / 44 edges**, identical whether installed
fresh (`01_vertices` → `02_edges` → `03_create_graph`) or migrated from the
Round-F2 state (`migrations/001_exceptions_and_jobs.gsql`) — proven by
`verify_schema_parity.py`. Rounds 2 (behaviour) and 3 (UI) were re-read
against every addition (REVIEW_COMMENTS_BATCH1/2): the exception model
(batch2 §E) lands entirely on the eight rule attributes, the querying change
(§F) and pagination/evidence changes need no schema, and job progress UI
(Round 3) reads the job vertex built here. Nothing in those rounds needs
another migration.

All checks below ran here; **no live TigerGraph is reachable from this
Codespace** (the carried limitation since Round A), so "applies to an
installed graph" is proven the only honest way available: the migration
applied to the committed F2 baseline in memory must equal the clean install
exactly, and the migration file must carry no data-touching statement.

`scripts/verify_round_1.py` — **12/12 PASS** (run twice, repeatable). Actual
output per check:

## Check 1 + 2 — migration applies to the F2 state without touching data; parity

```
PASS  SP-1 migration is data-safe (no DROP/DELETE/UPDATE/CLEAR/LOAD)
PASS  SP-2 migration creates phx_dm_pce_job as a NEW vertex
PASS  SP-2 migration creates phx_dm_pce_job_for_document as a NEW edge
PASS  SP-2 migration creates phx_dm_pce_job_for_run as a NEW edge
PASS  SP-2 migration alters an EXISTING vertex phx_dm_pce_rule
PASS  SP-2 phx_dm_pce_rule ALTER adds only new attributes
PASS  SP-3 vertex type sets identical — 31 vertex types
PASS  SP-4 every vertex's attributes identical (names AND types)
PASS  SP-5 edge type sets + from/to/reverse identical — 44 edge types
PASS  SP-6 03_create_graph lists every vertex+edge type exactly once — 75 types
PASS  SP-7 schema_catalog vertices == DDL vertices (names, attrs, types) — 31 vertices
PASS  SP-8 schema_catalog edges == DDL edges — 44 edges
PASS  SP-9 90_drop_all drops edges then vertices in exact reverse create order

all checks passed — migration == clean install (31 vertices / 44 edges)
```

The check is not vacuous: a deliberately corrupted migration (one attribute
removed) fails `SP-4 … phx_dm_pce_rule: clean-not-migrated=
[('exception_sensitivity', 'DOUBLE')]` (proven during the round). The
migration is one GLOBAL SCHEMA_CHANGE JOB — valid on an installed 4.2.2
graph, additive only.

## Check 3 — eight fields present; the extractor proposes with citations, null where not stated

```
PASS  R1-2 all eight exception fields in DDL + schema_catalog + store mirror — 8/8 in all three
PASS  R1-4 extractor proposals: stated -> kept with citation; unstated -> null + NOT STATED
```

And LIVE, real Sonnet over the actual plan document's discount-sharing window
(`cwm_pca_plan_2026.pdf`, persist=False, ≈$0.08) — proposals verbatim:

```
- DISCOUNT_SHARING_THRESHOLD_TRIGGER: denom='managed accounts' floor=None unit=None
    scope='products billed on the Standard Managed 145 bps Fee Schedule'
    src="Page 3, Section 3: 'applies to products billed on the Standard Managed 145 bps Fee Schedule'"
- EQUITY_TRADE_MINIMUM_REVENUE: denom='equity trades' floor=25.0 unit='revenue'
    src="Page 2, Section 2: 'Equity trades generating less than $25.00'"
- MONTHLY_INCENTIVE_GRID: denom='monthly credited revenue' floor=None unit=None
    scope='' src='NOT STATED'
- NNM_ANNUAL_AWARD_CALCULATION: denom='Total Annual NNM' floor=None unit=None
    scope='' src='NOT STATED'
```

The document's own scope language becomes `product_scope` with its page
citation; a provision stating nothing gets null + `NOT STATED` — no number
was invented anywhere in the run.

## Check 4 — three rules default exception_enabled=true; everything else driver-only

Against the LIVE served store (RSV_v8, rehydrated in place — no reseed):

```
PASS  R1-3 LIVE store: exactly the three spec rules exception_enabled=true,
      everything driver-enabled — RSV_v8: exception_enabled=
      ['DISCOUNT_SHARING_MINIMUM_GRID_RATE', 'DISCOUNT_SHARING_THRESHOLD_TRIGGER',
       'LOST_ACCOUNT'], driver_enabled on all 12 rules
```

Mapping of the spec's three names to rule_codes is recorded in DECISIONS.md
(2026-08-16): "discount sharing not applied" stands on
DISCOUNT_SHARING_MINIMUM_GRID_RATE until a dedicated rule exists.

## Check 5 — job rows from document ingest and insight generation

```
PASS  R1-5 document ingest writes phx_dm_pce_job with stage and counts —
      status=COMPLETE stage=embed (3/6) items 1/1
PASS  R1-7 insight generation job: four stages, run_id recorded, COMPLETE —
      status=COMPLETE stage=persist (4/4) run_id=V000002|202604|202605|RSV_v0
```

Ingest completes at stage embed (3/6) honestly — extract/compile/audit are
demand-driven and REOPEN the same job (extraction per-window; compile/audit
per-stage touches). Insight generation runs evaluate_rules →
investigate_residual (per-item = miner turns) → narrate → persist, carries
the `job_for_run` edge via the recorded run_id, and a failing run marks the
job FAILED with the error verbatim. `data_load` jobs (one stage per entity)
are written by load_mock_data/load_real_data. Served: `GET /api/jobs`,
`GET /api/jobs/{id}`, `POST /api/jobs/{id}/resume` (explicit — never
automatic).

## Check 6 — interrupted ingest resumes at the correct stage, repeating nothing

```
PASS  R1-6 interrupted extract: INTERRUPTED with resume_token, resume repeats
      no earlier window — interrupt: INTERRUPTED token={'next_window': 2};
      resume made 1 LLM call(s) (windows 0-1 skipped), job COMPLETE 3/3
```

The mechanism: each extraction window's rules PERSIST before the next window
begins, so a kill at window 2 of 3 loses only the in-flight window; resume
(explicit, `?resume=1` / POST /api/jobs/{id}/resume) restarts at
`resume_token.next_window` with the duplicate filter seeded from the draft
pool — exactly one LLM call for the one remaining window.

## Check 7 — extract_chunked: --dry-run plan; --resume skips completed chunks

```
PASS  R1-8a extract_chunked --dry-run prints the chunk plan, extracts nothing —
      chunk plan: 11 single-table chunks + 6 transaction chunks
      (2 months x 3 advisor batches of <= 200) = 17 chunks
PASS  R1-8b token expiry -> clean exit; rerun resumes, skips completed chunks —
      first rc=3 (14/17 checkpointed), resume rc=0 ran 3 remaining queries,
      17/17 complete
```

Observed live with a stub connection (no PostgreSQL reachable here): a
simulated token expiry at chunk 15 exits cleanly with
`CHUNK FAILED … Checkpoint saved (14 of 17 chunks complete) … RERUN THE SAME
COMMAND — it resumes at this chunk, never from the start.`; the rerun prints
`resume: 14 chunk(s) already complete — skipped; 3 to go` and issues exactly
3 queries. Chunk files write atomically (`.csv.part` rename) so a chunk is
either complete or absent; the checkpoint carries a plan fingerprint so
changed arguments refuse to mix with an old checkpoint.

## Check 8 — validate_raw_extracts catches a deliberately corrupted chunk

Clean fabricated drop (all three source kinds): **V-1..V-10 all PASS**,
ending `0 failure(s) — safe to proceed to the Phase 4 review gate`, with the
sanity anchor at **$33,200/advisor/month** (the ~$33k target). Corruptions,
each verbatim:

```
FAIL  V-2 transaction chunk sequence has no gaps — missing batches: {'202605': [1]}
FAIL  V-2 chunk files match extract_checkpoint.json — raw_txn_202606_b002:
      file has 282 rows, checkpoint recorded 319
FAIL  V-3 RAW_CONTRACT columns on every PostgreSQL file —
      raw_monthly_balance.csv: missing columns ['acct_bal']
```

(the third is R1-9's in-suite probe). And the source-kind gate in the build:

```
BUILD FAILED — ColumnMismatchError: NNM category file(s) missing from …:
['YINNM'] — all four of ['ECNNM', 'FSNNM', 'NBNNM', 'YINNM'] are required
(original filenames, e.g. ECNNM_20260630.txt); three of four would load
silently incomplete, so the build refuses to start
```

The chunked layout builds identically: 6 transaction chunks +
`crm_opportunities.csv` + the four NNM files → `ALL 12 VALIDATIONS PASSED`,
totals byte-equal to the single-file build.

## Check 9 — SOURCE_TO_VERTEX_MATRIX lists all three source kinds and every vertex

```
PASS  R1-10 SOURCE_TO_VERTEX_MATRIX: all three source kinds + every vertex —
      31 vertices, three kinds named
```

## Check 10 — the runbook is followable start to finish

`docs/CLIENT_ENV_RUNBOOK.md`: Phases 0–6 numbered, every step with the exact
command, what a correct result looks like, and what to do when it is not.
**Phase 4 is the hard review gate** — "STOP HERE … wait for an explicit
go-ahead"; Phase 3.1 states the exact file placement of all three source
kinds in `data/real/_raw/` (NNM files under their ORIGINAL names). Both
embedded code snippets were EXECUTED here as written:

```
46/46 catalog queries executed
raw  : {'202604': 640455.61, '202605': 663183.98, '202606': 688335.74}
built: {'202604': 640455.61, '202605': 663183.98, '202606': 688335.74}
```

(the Phase-5.3 reconciliation matches to the cent). The referenced
`prompts/COPILOT_SIZING_AND_RATE.md` was authored this round (Part A sizing
SQL incl. the cohort.txt query extraction requires; Part B
measure-don't-estimate ingestion rate with the p95×1.2 projection).

## Regression + servers

```
verify_round_a 25/25 · b 19/19 · c 13/13 · e 8/8 · h 9/9 · a1 17/17 ·
check_flags 8/8 · check_manual_rules 17/17 · check_nnm_parse 19/19 ·
verify_schema_parity all-pass · verify_round_1 12/12 · npm build 8 routes
```

Servers running on this round's code: uvicorn :8002 (healthy, /api/jobs
serving) · next :3002 (200). Forwarded URLs:
`https://effective-goldfish-9jv9xpx9jx4cp969-8002.app.github.dev` /
`…-3002.app.github.dev` — public visibility still needs the Ports panel
(the gh token lacks the codespace scope; carried limitation).

## Deviations / notes (honest)

- **No live TigerGraph / PostgreSQL here** — check 1 is proven by in-memory
  application against the committed F2 baseline plus the data-safety scan;
  extract_chunked's resume by stub connection; the data path on the
  fabricated `data/real_test/_raw` drop (Round D/F precedent).
- Per the seven-place checklist's own rule, `data/manifest.json` and
  `generate_mock_data.py` are untouched: both additions are app-written (no
  CSV load); the JobStore's runtime upsert is the loading job.
- The ingest job completes at stage embed (3/6) because extract/compile/audit
  are demand-driven; they reopen the job when run. Insight-generation resume
  is honestly not supported (`POST /resume` explains: regenerate) — an LLM
  loop has no safe mid-flight resume point; the run-level idempotency
  (supersede-on-regenerate) is the recovery path.
- Round-2/3 non-foreclosure check: batch2 §E exception model = these eight
  fields; §F querying change is query/agent behaviour (no schema); batch1
  A1–A7 + D/F/G/H and batch2 B/C/D are UI/behaviour on existing vertices;
  job progress UI reads phx_dm_pce_job. The one schema-adjacent open item —
  `job_code` on the advisor vertex — stays deliberately OUT pending the
  operator's discovery_job_code.sql run (manufacturing schema for an
  unobserved column is the failure mode this app avoids); if discovery
  confirms it, that is ONE additive ALTER in a future migration file, which
  the migration mechanism built this round handles without a reinstall.
- Session LLM spend ≈ **$0.08** (one real Sonnet extraction window; all other
  checks deterministic) — far under the $4 checkpoint.
