# Build Progress

## Current position
Round: A — COMPLETE (verify_round_a.py 25/25, see docs/ROUND_A_COMPLETE.md)
Task: next session starts Round B (dashboard, RAG, rules — BUILD_PLAN §5)
Last updated: 2026-08-11 ~10:20 UTC

## Task checklist (Round A)
- [x] 1. Port §2 port list — app/config (main thread), app/graph (6 files), app/ingestion (12), app/shared (7) +
      app/api/middleware (2) + app/llm (3), app/knowledge (8, from v1), frontend base shell (port 3001).
      All py_compile clean; integration import test passed; zero phx_dm_v2_/iperform leftovers (grep-verified).
- [x] 2. docs/tigergraph/ — 24 vertices, 36 edges, create graph, drop-all in exact reverse order,
      16 vertex loading jobs + load_edges.gsql, QUOTE="double" on 43/43 LOADs, schema_catalog.json. Structural checks ALL PASSED.
- [x] 3. app/revenue/products.py — 24-group seed + unmapped; resolve_product with ELIS/LEND sub-code splits (sanity run observed).
- [x] 4. app/revenue/aggregation.py — build_monthly_revenue + independent verify (tamper detection observed).
- [x] 5. Mock data generator ran (seed 42): 43 files, 4,605 vertex rows, 15,367 edge rows; all demo scenarios verified present.
- [x] 6. scripts/load_mock_data.py loaded all 43 entities through the ported pipeline; manifest verification ok=True, 0 mismatches (observed).
- [x] 7. GET /api/health live-tested via uvicorn + curl: healthy=true, tier 4, 16 vertex counts, honest LLM state (observed).
- [x] 8. scripts/verify_round_a.py: 25/25 PASS, exit 0 (output pasted in docs/ROUND_A_COMPLETE.md).

## Verified working
- FastAPI starts on 8001; /api/health green (graph mock tier 4, all counts); server output observed via curl
- Ingestion end-to-end on mock data: 43/43 entities, counts == manifest, fail-loud path exercised by design
- Monthly aggregates match an independent recomputation from the transaction CSV (1,008 rows, 0 mismatches)
- verify_round_a.py 25/25

## Known broken / deferred
- frontend not npm-installed/built yet (Round B first step)
- knowledge chunker still V1 900-char window (Round B rework per plan)
- GSQL structurally verified only — no live TigerGraph reachable from this box
- LLM_MODE=cdao unreachable here (no cdao package) — expected on the build box; use LLM_MODE=mock locally

## Notes for the next session
- Read docs/ROUND_A_COMPLETE.md "For the next round" — interface contracts and gotchas.
- reference/v1 and reference/v2 are read-only; copy out, never import across.
- normalize_account_key in app/shared/ids.py is the ONE account-key normalisation.
- cdao GPT-5: blank api_version → omit argument, temperature=1, never max_tokens; LLM_MODE=cdao → cdao_openai adapter.
- docs/DECISIONS.md has all port-time decisions.
