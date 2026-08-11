# Build Progress

## Current position
Round: C — IN PROGRESS (docs/spec/ROUND_C_SPEC.md supersedes BUILD_PLAN §6)
Task: task 0 DONE (both Round B bugs fixed, verify_round_b 19/19, verify_round_a 25/25);
      IN PROGRESS -> task 1 (real Claude LLM + local embeddings)
Last updated: 2026-08-11 (Round C session)

## Task checklist (Round C)
- [x] 0.1 Param validation before population fetch (evaluator + compiler attribute params;
      verify B3-18: identical error in 202604/05/06)
- [x] 0.2 LOST_ACCOUNT fixed via prior_end_balance/prior_credited_amt on account_month
      (DDL V11, loading job, mock generator, schema_catalog, SCHEMA_SPEC; compute ->
      sum(prior_credited_amt); verify B3-19: 10 matches on 202605, empty-with-reason 202604)
- [ ] 1 LLM_MODE=claude (sonnet-4-5) + EMBEDDING_MODE=local (MiniLM 384) + scripts/check_llm.py
- [ ] 2 C1 query catalog (24 queries, local impls + GSQL files)
- [ ] 2 C2 Insights Miner (3 tools, 40-query budget, agent_query_log, evidence rows)
- [ ] 2 C3 Insights Reporter (findings only, numeric assertion in code, template fallback)
- [ ] 2 C4 async runs (generate/status/get, supersede on re-run)
- [ ] 2 C5 AI Insights + Advisor screens per mockup
- [ ] 3 docs/sample/comp_plan_2026_sample.pdf (all rules incl. NEEDS_INPUT referral cap)
- [ ] 4 scripts/e2e_test.py with real AI, full output pasted
- [ ] 5 both servers on public forwarded URLs; docs/ROUND_C_COMPLETE.md

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
- Local test modes: EMBEDDING_MODE=mock LLM_MODE=mock (cdao only exists client-side).
- B2→B3 contract: extract_rules_for_document(document_id, chunks) with chunk dicts
  {chunk_id, text/chunk_text, page_no, section_path, has_table}.
- LLM spy point for no-call assertions: app.knowledge.rag_service.get_llm_client.
- Rule store is process-local, mirrored to graph; seed runs at startup AND lazily via router dep.
