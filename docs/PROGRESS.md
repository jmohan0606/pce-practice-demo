# Build Progress

## Current position
Round: C — COMPLETE except ONE item blocked on Anthropic API credits
      (account hit "credit balance too low" at ~11:52 UTC mid-e2e; see
      docs/ROUND_C_COMPLETE.md "Blocked")
Task: after credits are added: (1) python3 scripts/e2e_test.py — steps 8 & 10 are the
      only unproven ones (1-7, 9 passed with real Claude, output in
      docs/ROUND_C_E2E_OUTPUT.txt); (2) POST /api/insights/generate for advisor=all on
      both transitions against the running server so the browser shows real-Claude runs;
      (3) make ports 8001/3001 Public (needs gh codespace scope or the Ports panel).
Last updated: 2026-08-11 (Round C session)

## Task checklist (Round C)
- [x] 0.1 Param validation before population fetch (evaluator + compiler attribute params;
      verify B3-18: identical error in 202604/05/06)
- [x] 0.2 LOST_ACCOUNT fixed via prior_end_balance/prior_credited_amt on account_month
      (DDL V11, loading job, mock generator, schema_catalog, SCHEMA_SPEC; compute ->
      sum(prior_credited_amt); verify B3-19: 10 matches on 202605, empty-with-reason 202604)
- [x] 1 LLM_MODE=claude (claude-sonnet-4-5-20250929) + EMBEDDING_MODE=local
      (all-MiniLM-L6-v2, EMBEDDING_DIM=384) — scripts/check_llm.py ran live: real Claude
      sentence + 384-dim embedding, output in ROUND_C_COMPLETE.md
- [x] 2 C1 query catalog — app/graph/queries/catalog.py (24 queries, typed params
      validated BEFORE execution, run_catalog_query envelope) + 24 GSQL files under
      docs/tigergraph/queries/; all 24 smoke-tested against mock data
- [x] 2 C2 Insights Miner — app/insights/{store,tools}.py + app/agents/insights_miner.py
      (JSON-action loop, 40-query budget, every tool call logged with seq_no, evidence
      rows copied from the retained producing-query result, coverage ratio internal)
- [x] 2 C3 Insights Reporter — app/agents/insights_reporter.py (findings-only by
      construction: imports json/logging/re/typing ONLY; regex numeric assertion;
      deterministic template fallback that self-verifies)
- [x] 2 C4 async runs — app/insights/service.py JobManager (daemon thread, per-advisor
      progress, failure isolation) + /api/insights router (generate/status/get/query-log/
      runs/peer-rank; coverage stripped from every response)
- [x] 2 C5 AI Insights + Advisor screens — narrative block, tinted transition cards,
      ranked findings with evidence tables + rule citations, pivot regroups without
      refetch, honest empty states; npm run build passes
- [x] scripts/verify_round_c.py — 12/12 PASS (scripted-LLM determinism; real Claude in e2e)
- [x] 3 docs/sample/comp_plan_2026_sample.pdf (6 pages; all rules as prose+tables;
      referral cap deliberately unstated; 16-row payout schedule)
- [x] 4 scripts/e2e_test.py with real Claude — steps 1-7 and 9 PASSED and pasted
      (32 rules extracted, referral cap NEEDS_INPUT with no invented number, 7 conflicts
      proposed-only, v1 published with 15 rules, 8-finding V000002 run with 25 queries
      and zero unverified figures). Steps 8 & 10 ran but every Claude call failed on
      exhausted API credits (isolation verified: 21 failures, batch never aborted) —
      RERUN e2e_test.py once credits exist.
- [x] 5 servers up (uvicorn :8001 healthy, next :3001 200; forwarded URLs + CORS wired;
      port visibility needs the Ports panel or gh codespace scope);
      docs/ROUND_C_COMPLETE.md written with actual output

## Task checklist (Round B)
- [x] B1 Dashboard — 4 API endpoints (exact B1.1 shapes, mock-tier queries in app/graph/queries/pce_dashboard.py),
      frontend restructured to B1.2 (tokens verbatim from mockups.html, format.ts everywhere,
      negatives in parentheses, filters only where they act); npm build passes, 5 pages serve.
- [x] B2 RAG — pdfplumber/docx/pptx parsing, table-preserving SectionChunker (1800/200),
      Chroma-first dual write with rollback, sha256 dedup, 0.30 floor with zero LLM calls below,
      five /api/documents endpoints, scripts/make_test_pdf.py.
- [x] B3 Rules — grammar + compiler (schema_catalog field resolution), evaluator with baseline
      guard + transfer exclusion, immutable RuleStore with graph mirroring, v0 seed (6 rules,
      exact B3.7), extractor (6-chunk windows, 1 overlap, NEEDS_INPUT never dropped),
      conflict auditor (proposals only), /api/rules endpoints.
- [x] Main thread — routers + ensure_v0_seed wired in app/api/main.py;
      normalize_account_key wired into ingestion (manifest-derived normalize_columns,
      13 entities; padded keys normalise, 0 churn on clean data).
- [x] scripts/verify_round_b.py — 17/17 PASS (output pasted in docs/ROUND_B_COMPLETE.md).
- [x] Regression: verify_round_a.py 25/25 (8b widened to >=16 vertex types — rule seed adds 2).

## Verified working
- Full app in-process: health + 4 dashboard + documents + rules endpoints all 200 (mock modes)
- Product contribution math: rows==subtotals==total, share_pct 100.01, 25/25 groups, no dupes
- Table-bearing PDF → whole table in one has_table chunk; re-upload dedups; rollback leaves no orphans
- v0→v1 publish lifecycle with SUPERSEDED-and-queryable prior version; conflicts proposed never applied
- Ingestion normalises padded account keys; clean data re-ingests as 100% SKIP

## Known broken / deferred
- Insights page empty state, Advisor page KPIs-only (Round C)
- Extractor end-to-end needs the client cdao environment (mock-verified deterministically here)
- GSQL still not executed against a live TigerGraph (none reachable)
- pdfplumber was missing from this box despite the confirmed list — now installed (0.11.10) and
  in pyproject's rag extra; re-check the other confirmed packages in the client environment

## Notes for the next session
- Read docs/ROUND_B_COMPLETE.md "Deviations / notes" + DECISIONS.md Round B entries.
- reference/v1 and reference/v2 are read-only; copy out, never import across.
- Local modes: LLM_MODE=claude + EMBEDDING_MODE=local since Round C (cdao only exists
  client-side). CORRECTION to the Round B note: EMBEDDING_MODE=mock does NOT exist —
  valid modes are cdao | cdao_openai | local | azure | azure_openai; anything else raises
  EmbeddingClientError. verify_round_b sets EMBEDDING_MODE=mock but its checks never
  construct an embedding client below the 0.30 floor path it tests.
- B2→B3 contract: extract_rules_for_document(document_id, chunks) with chunk dicts
  {chunk_id, text/chunk_text, page_no, section_path, has_table}.
- LLM spy point for no-call assertions: app.knowledge.rag_service.get_llm_client.
- Rule store is process-local, mirrored to graph; seed runs at startup AND lazily via router dep.
