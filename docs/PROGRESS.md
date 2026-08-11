# Build Progress

## Cost & UI fix session (docs/spec/SESSION_PROMPT_COST_AND_UI_FIXES.md)
- [x] Hard rule 2: ANTHROPIC_MODEL=claude-haiku-4-5-20251001 in .env; settings default
      already Haiku; all four roles inherit it (no per-role overrides set)
- [x] Task 1: token/cost logging — phx_dm_pce_agent_turn_log vertex (DDL, schema_catalog,
      graph, drop, SCHEMA_SPEC, phx_dm_pce_turn_in_run edge); ClaudeLLMClient returns
      response.usage via generate_with_usage (never estimated); TurnLoggingLLM wrapper
      (app/llm/usage.py) logs every miner/reporter/extractor/conflict-auditor call with
      est_cost_usd (app/llm/pricing.py); rollups total_*_tokens/est_cost_usd/wall_ms +
      budget_hit_tokens on phx_dm_pce_insight_run; MAX_RUN_INPUT_TOKENS=60000 hard stop
      in the miner loop. verify a/b/c: 25/25, 19/19, 12/12 (2a/2b/2e widened to >=,
      DECISIONS.md)
- [x] Task 2: context engineering — miner sends a real messages array (system +
      opening blocks carry cache_control ephemeral, byte-identical every turn;
      turns appended, not rebuilt) via ClaudeLLMClient.generate_conversation;
      single-string path kept for mock/scripted/non-Claude. Pruning:
      RECENT_RESULTS_KEPT 10→3, payload cap 1500 chars, ROWS_SHOWN 25 with
      row_count= always appended; superseded results compress to code-built
      factual one-liners (summarize_result — no LLM). Budgets MAX_TURNS 60→20,
      query budget 40→12 (MINER_QUERY_BUDGET). verify a/b/c still 25/19/12.
      NOTE: Haiku's minimum cacheable prefix is 4096 tokens — the opening block
      (rules+catalog+initial) makes the cached prefix large enough; the system
      block alone would not be.
- [x] Task 3: Trace tab — /api/trace/runs (runs table: advisor, transition, version,
      turns, queries, tokens, cache hit %, cost, wall, status incl. budget flags),
      /api/trace/runs/{run_id} (per-turn table with prompt-size bar — runaway turn
      visible at a glance), /api/trace/summary (per-advisor, document-extraction,
      conflict-audit, full-refresh projection). Projection line under the insights
      Generate button (avg of previous runs; greyed with no history). npm build OK.
- [x] Task 4: UI corrections — 4.1 AI Insights + Advisor merged into one page with a
      Practice/Advisor toggle (tabs: Dashboard · AI Insights · Documents & Rules ·
      Rule Versions · Trace); 4.2 Advisor Generate runs exactly one advisor+transition
      (no fan-out), the all-advisors batch lives only in Practice behind a confirm
      dialog showing the cost projection; 4.3 straight SVG arrows (arrowheads kept);
      4.4 selected pill = 2px navy border + pos/neg tint, green/red text preserved;
      4.5 June complete — is_partial=false for 202606, trading days 30/31/30 in mock
      generator + SCHEMA_SPEC, "12 Trading Days" caption and partial-month note
      removed, mock data regenerated (verify a/b/c re-passed); 4.6 Rule Versions
      expand to every rule (name, description, source citation, compiled query,
      status) with Edit that creates a draft → approve → publish (new version,
      never mutates). npm build passes.
- [ ] Task 5: schema additions (opportunity, document_type, checklist)
- [ ] Task 6: one cheap verification run + ROUND_C_FIX_COMPLETE.md

## Current position
Round: C — COMPLETE except the all-advisors batch, STOPPED EARLY on operator
      instruction after API credits ran out a second time (aggregate run COMPLETE,
      20 per-advisor runs FAILED on "credit balance too low"; no new runs started).
Task: to finish the per-advisor sweep later: add credits, then
      `python3 scripts/e2e_finish.py` (it skips the already-published v1 and re-runs
      the batch; supersede semantics replace the FAILED rows in place).
      Port visibility for 8001/3001 still needs the Ports panel (gh token lacks the
      codespace scope).
State on the LIVE server (process-local): rule set v1 PUBLISHED (from the sample PDF);
      insight runs for 202604->202605: `all` COMPLETE with 10 findings (real Claude,
      36 logged queries, numeric assertion passed — docs/ROUND_C_E2E_FINISH_OUTPUT.txt),
      V000001..V000020 FAILED with the credit error recorded. AI Insights page renders
      the real aggregate run; Advisor page honestly shows the failed state.
Last updated: 2026-08-11 (Round C session, after credit-limited batch)

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
