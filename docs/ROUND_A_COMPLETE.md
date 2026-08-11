# Round A Complete

## Delivered
- app/config/settings.py — pruned PCE settings (env contract matches BUILD_PLAN §2; LLM_MODE=cdao aliases the cdao_openai adapter)
- app/graph/ — 4-tier client ported from V2 (MCP → pyTigerGraph → RESTPP → local store), tier log, CSV-backed local store loading data/manifest.json with fail-loud count mismatches
- app/ingestion/ — manifest-driven loader ported from V2: checkpoints, delta detection, header/record validation, upsert honesty checks (tier-4 write in a real mode fails the batch), plus manifest_check.verify_counts_against_manifest
- app/llm/ — 5 adapters incl. cdao (blank api_version omitted, temperature=1, no max_tokens), per-role config for the four PCE agents, embedding client with the _fit_dim loud-failure guard
- app/shared/ + app/api/middleware/ — logging, correlation ids, error handlers, ids incl. THE shared normalize_account_key
- app/knowledge/ — V1 RAG port (Chroma cosine, similarity = 1 − distance, sha256 idempotency, honest not-found path); chunker flagged for the Round B rework
- app/revenue/ — 24-group product seed + resolve_product (ELIS/LEND sub-code splits, unmapped never dropped) and monthly aggregation (mr_id = advisor_sid|month_id|product_id)
- docs/tigergraph/ — 01_vertices (24), 02_edges (36), 03_create_graph, 90_drop_all (exact reverse order), 16 vertex loading jobs + load_edges.gsql (27 edges), all LOADs QUOTE="double", schema_catalog.json parsed from the DDL
- scripts/generate_mock_data.py — deterministic (seed 42): 20 cohort + 2 counterparty advisors × 3 months, 43 files, 4,605 vertex rows, 15,367 edge rows, every demo scenario present
- scripts/load_mock_data.py — loads all 43 entities through the ported pipeline; manifest verification ok=True, 0 mismatches
- GET /api/health — graph tier, per-vertex row counts, honest LLM reachability
- frontend/ — ported base shell (port 3001, mockup palette tokens, health pill); not yet npm-installed (Round B)

## Verification output
Actual output of `python3 scripts/verify_round_a.py`:

```
PASS  1. ported modules import — 21 modules
PASS  2a. 24 vertices in 01_vertices.gsql — found 24
PASS  2b. 36 edges in 02_edges.gsql — found 36
PASS  2c. drop order is exact reverse of create order
PASS  2d. QUOTE="double" on every LOAD — 43/43 LOADs
PASS  2e. schema_catalog.json covers all 24 vertices
PASS  3a. resolve_product per spec (sub-code splits + unmapped) — 7 cases
PASS  3b. 24 display groups + unmapped seeded — 25 rows
PASS  3c. UMA displays as its own row AND classes Recurring (parallel dimensions)
PASS  4. every CSV row count matches manifest.json — 43 files
PASS  5. graph counts match manifest (fail-loud check ran) — 43 targets, 0 mismatches
PASS  6a. monthly credited totals match independent recomputation — 1008 aggregate rows
PASS  6b. reason-coded rows carry zero credited_amt (loaded as non_credited) — credited rule holds
PASS  6c. mr_id = advisor_sid|month_id|product_id (advisor-scoped key)
PASS  7a. fee reductions >10% with recorded AND unrecorded grid_reduction — 13 above threshold, 2 recorded
PASS  7b. inbound and outbound transfers — 13 transfers
PASS  7c. accounts opened in scope (Q2)
PASS  7d. accounts zeroed between months
PASS  7e. team agreements with fractional shares — 3 agreements
PASS  7f. unmapped product visible, never dropped
PASS  7g. flows Apr+May only, one advisor above $4MM NNM — max NNM $6,700,730
PASS  7h. blank advisor name stays blank; non-cohort counterparties loaded
PASS  8a. GET /api/health returns 200 and healthy=true — status 200
PASS  8b. health reports graph tier + per-vertex counts — tier=4, 16 vertex types
PASS  8c. health reports LLM reachability honestly — mode=cdao reachable=False

25/25 checks passed
```

Live server check (actual): `python3 -m uvicorn app.api.main:app --port 8001` then
`curl http://127.0.0.1:8001/api/health` returned `healthy: true`, graph mode `mock` tier 4,
load_report `{16 vertex types, 27 edge types, 4605 vertex rows, 15367 edge rows, no mismatches}`,
all 16 per-vertex counts, and LLM `reachable: false` with the cdao-package-absent error (the
correct honest state on the build box — cdao exists only in the client artifactory).

## Files created
See docs/ROUND_A_CHANGED_FILES.md (full list). Summary: app/ (7 packages, 42 python files),
docs/tigergraph/ (22 files), data/ (43 CSVs + manifest), scripts/ (3), frontend/ (base shell),
.env, pyproject.toml, docs/{PROGRESS,DECISIONS,ROUND_A_*}.md, docs/data/cohort_advisors.csv.

## Files modified
- .gitignore (logs, chroma, checkpoints, frontend build artifacts)

## Not done / carried forward
- Frontend npm install/build not run — Round A's done-when is API-side; first Round B step.
- Knowledge chunker is still V1's 900-char window — Round B replaces it (section boundaries, tables whole, page_no/section_path).
- GSQL not executed against a live TigerGraph (none reachable here); structural checks only. Loading jobs + DDL install verify on a real instance.
- LLM reachability shows false on this box (no cdao package) — expected; mock/claude modes work for local testing.

## For the next round
- Graph access: app.graph.client.get_graph_client(); mock tier serves from FoundationGraphStore (data/manifest.json). Row-count mismatch raises at first load.
- Query registration for the mock tier: @mock_query("name") in app/graph/queries/ (registry ported, empty).
- Aggregation contract: build_monthly_revenue ignores any input group_id and re-resolves via products.resolve_product — one source of truth.
- resolve_product("ELIS","") (no sub-code) deliberately → unmapped (never guess a split product without its sub-code).
- The four agent roles resolve LLM config via app.llm.roles.resolve_role_config("insights_miner" | ...).
- Reason-coded transaction rows are loaded with credited_amt=0 / non_credited_amt=amount and reason_cd literal "__NONE__" for credited rows.
- Health payload shape is what frontend/lib/api/client.ts getHealth() expects.
