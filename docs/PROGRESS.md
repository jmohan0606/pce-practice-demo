# Build Progress

## Round A1 (docs/ROUND_A1_SPEC.md) — backend + data layer only, no UI
- [x] Task 1 (main thread, 8e00dd8): driver identity split from label —
      driver_code (stable slug) STORED on findings (phx_dm_pce_finding
      driver_tag→driver_code across DDL/schema_catalog/SCHEMA_SPEC; legacy
      persisted findings migrate at rehydration), driver_label resolved at
      READ time via a durable registry (RuleStore.set_driver_label, SQLite
      driver_label table) so PATCH /api/rules/{key}/driver-label renames
      every historical finding's displayed name with no regeneration;
      driver_definition on rules (seed-authored for tech-written, compiler-
      drafted for document-derived — never overwrites a human's);
      GET /api/drivers + GET /api/glossary (app/shared/glossary.py = the one
      tooltip source: metrics, drivers, severity levels, provenance chips,
      9X causes from app/shared/reason_codes.py). Prose-frozen-names limit
      recorded in DECISIONS.md. verify a/b/c/e/h green.
- [x] Task 2 (main thread, bc78f1f): severity CRITICAL|HIGH|MODERATE|LOW|INFO
      + severity_reason on rules — extractor-assigned from provision language
      (invalid/absent lands honestly at INFO saying so), seeded on the five v0
      rules per the spec table; findings inherit the producing rule's severity
      (no rule → INFO, "observation"); /api/insights/exceptions now serializes
      severity, includes non-rule observation rows, filters ?severity= and
      sorts Critical→Info then |impact| (+ spec-path alias GET /api/exceptions
      ?from=&to=&severity=); PATCH /api/rules/{key}/severity mints a new
      version in one call — edit() special-cases display-only changes so the
      compiled plan survives (DECISIONS.md). Stale rule_store.db cleared for
      the corrected seed. verify a/b/c/e/h green.
- [ ] Task 3 (Subagent A, dispatched): dashboard metric queries + RETAINED_ACCOUNT
- [ ] Tasks 4+5 (Subagent B, dispatched): 9X non-credited analysis + top/bottom
- [ ] Task 6 (Subagent C, dispatched): export service (pdf/pptx/xlsx/csv)
- [ ] Task 7 (main thread, last): 17 checks + regressions + ROUND_A1_COMPLETE.md
Note: per Round E/G/H precedent, subagents report and the MAIN THREAD verifies
      then commits each task (subagents never run git or touch this file).

## Round H (docs/ROUND_H_SPEC.md)
- [x] Port change (e2eda07, pre-round): app now runs on 8002 (API) / 3002
      (frontend) — 8001/3001 taken by another app. .env(+example),
      frontend/.env.local(+example), package.json, lib/api.ts, next.config.mjs,
      e2e_finish.py, settings defaults; CORS derives from settings.frontend_port.
- [x] Task 1 (main thread): implicit transferred_keys accumulation DELETED from
      evaluate_rule_set — exclusion is explicit-only via exclude_matched_of;
      LOST_ACCOUNT declares ["ACCOUNT_TRANSFERRED_IN","ACCOUNT_TRANSFERRED_OUT"].
      Practice 202604: IN=13 AND OUT=13 independently (OUT was structurally 0).
      NEW scripts/verify_round_h.py H-1/2/3 (H-2 proves the exclusion with an
      injected 202605 transfer probe: IN claims it, LOST drops 10→9). Stale
      durable rule_store.db cleared so the corrected seed applies (DECISIONS.md).
      verify a/b/c/e re-run green 25/25, 19/19, 13/13, 8/8.
- [x] Task 2 (main thread): all 18 limit fields live in settings with env
      aliases (verify H-4 enumerates them; no module constants left) and 2.2
      defaults resized (tokens 60k→250k, queries 12→25, turns 20→35, rows
      25→40, evidence 50→200, payload 1.5k→4k; ingestion cap deliberately NOT
      resized — was Task 5's measurement). Every bound limit recorded as
      {limit_name, limit_value, limit_effect} on the run record (limits_json,
      rides the persisted run dict; graph mirror unchanged), in the API
      (limit_hit/limits_hit on insights + trace runs/detail) — query budget
      and turn cap now degrade through the same query-free wrap-up as the
      token ceiling (never a mid-thought cut); clipped results tell the model
      "showing N of M rows (a SAMPLE …)". never_fired(version) +
      GET /api/rules/never-fired (2.4). Log rotation: DatedSizeRotatingFileHandler
      — midnight roll to app.log.YYYY-MM-DD, 30-day retention, size cap kept as
      within-day safety net app.log.YYYY-MM-DD.N (2.5). verify_round_h
      H-4..H-8 + H-13 (9/9 with task 1); verify a/b/c/e green (E-5 re-pinned
      to the settings-resolved reserve).
- [x] Task 3 (Subagent A, verified in main thread): caching moved behind the
      LLM adapter — the Miner marks its two anchors ``stable: true``
      (app/llm/cache.py translates: Claude → cache_control ephemeral, cdao/
      OpenAI → flags stripped with the stable prefix kept byte-identical for
      automatic prefix caching, mock → ignored); grep proves no cache_control
      in app/agents/; old-vs-new Claude wire structures proven byte-identical
      across 4 growing turns. cdao/Real clients gain generate_conversation
      (usage incl. prompt_tokens_details.cached_tokens); SmartSDK Azure path
      keeps the single-string fallback (no clean usage surface — known gap).
      scripts/check_cache_support.py (3.2) reports whatever the configured
      provider returns — REAL Claude run: call 1 cache_write 8,631, call 2
      cache_read 8,631 (99.8%) — caching ENGAGES on this path (~$0.01).
      ASSUME_PROMPT_CACHING (3.3, default true): false reprices the
      /api/trace/summary projection at full input rate ($0.0115→$0.0475 avg
      run on the synthetic probe). C6-13 re-pinned on the wire format the
      Claude adapter sends (flagged deviation, accepted). verify a/b/c/e/h
      all green.
- [x] Task 4 (Subagent B, verified in main thread): LimitNotice renders the
      server's limit_effect strings as prose sentences on practice/advisor
      insights, transition cards and the drill-down panel (4.1); Trace gains a
      Limits column with amber row tint + full name=value—effect list in run
      detail, legacy budget flags folded in (4.2); Rule Versions gains a
      "Rules That Never Fired" card from /api/rules/never-fired with scopes
      chips and the honest all-fired empty state, and rule detail shows
      exclude_matched_of (4.3); evidence "showing N of M" via evidence_total
      confirmed across all renderers (4.4). Main thread closed the gap B
      found: the drill-down GET now serializes limit_hit/limits_hit from the
      stored run. npm run build passes; typed API clients updated.
- [x] Re-verification session (2026-08-12, post-restart): tasks 2/3/4 proven
      by EXECUTION, not inspection. Task 2: 18 limits printed at runtime,
      MINER_QUERY_BUDGET=2 override binds behaviourally. Task 3:
      check_cache_support real Claude (caching ENGAGES, 99.8% read call 2);
      check_cache_health real run PASS (one write turn 1, reads=176,148
      writes=0 after; write:read 0.04 vs Round E's 0.17); claude_wire 2
      anchors / openai path leak-free byte-identical. Task 4: npm build 8/8;
      headless-chromium OBSERVED: amber limit notice on insights, Trace
      Limits column + name=value—effect detail, never-fired card,
      "Showing 20 of 84" evidence clip. FOUND+FIXED en route: budget<3
      opening queries crashed bare (442b47e); rule-finding evidence hardcoded
      [:50] in service.py AND drilldown.py silently under-reported
      evidence_total (06831c7, found at scale); drill-down budget binds
      mislabelled MINER_QUERY_BUDGET (11c536f).
- [x] Task 5 (main thread, this session): --scale on generate_mock_data.py
      (S× txns, ceil(S/2)× accounts; S=1 preserves RNG order; 432c100).
      --scale 28 = 57,657 txns / 3,066 accounts / 490 households / 20
      advisors. Measured (ROUND_H_COMPLETE.md full table): gen 3.2s, ingest
      2m20s 46/46 verified, rule eval 3.34s, insight run 91.6s/$0.178
      (ROWS_SHOWN ×5 + MAX_RUN_INPUT_TOKENS bound, wrap-up + findings kept),
      drill-down 57.3s/$0.122 (8-query budget bound), largest tool result
      3,066 rows/306k chars → 40 rows shown as SAMPLE. NOTHING RESIZED —
      every bound limit degraded as designed; ingestion cap measured at 116
      calls max (500 kept, now with evidence). accounts_opened 3.1s latency
      outlier noted. FOUND: generator never cross-process deterministic
      (salted hash() product subsets; committed data/ canonical; DECISIONS.md).
      Scale data transient — canonical data/ restored, runtime dbs cleared.
- [x] Task 6 (main thread): all 13 checks PASS with actual output in
      docs/ROUND_H_COMPLETE.md (1–8, 13 via verify_round_h 9/9 on restored
      canonical data; 9 by grep+wire test; 10 by real run; 11 by the scale
      run; 12 by browser observation). verify a/b/c/e re-run green
      (25/25, 19/19, 13/13, 8/8). Servers restarted on this round's code
      (:8002 healthy, :3002 200); public visibility still needs the Ports
      panel (gh token lacks codespace scope).

## Round G (docs/spec/ROUND_G_SPEC.md)
- [x] Task 1 (main thread, 2d22311): rules declare their own scope — scopes on
      the rule model (derived at compile from :advisor_sid, human-overridable,
      serialized on every rule), evaluate_rule_set takes an explicit scope
      (derived when absent), non-applicable rules SKIPPED with skip_reason
      (normal state, distinct from failed), plan_by_scope per-scope plan
      variants (transfer rules gain practice plans — 13 transferred accounts
      firm-wide on 202604, keys still feed LOST_ACCOUNT exclusion), seed
      validates every scope plan, Rule Compiler emits/validates plan_by_scope.
      Practice 5/0 errors/0 skipped; advisor 5/0; missing-param contract
      re-pinned at explicit advisor scope (B3-18) + non-scope :threshold probe.
- [x] Task 2 (main thread, 7c094bb): finding generation diagnosed then fixed
      (docs/ROUND_G_DIAGNOSIS.md). Root causes measured: 60k token ceiling
      silently truncated runs at ~7/20 turns (no wrap-up); residual stated
      last; numeric gate was RIGHT (rejected fabricated account figures).
      Fixes: WRAPUP_TURNS=3 query-free ceiling wrap-up; no-silent-end nudge;
      residual leads the opening + rides the per-turn reminder; reporter gets
      one repair round naming rejected figures. V000002 202604→202605:
      agent findings 0 → 1 (genuine non-rule discovery), residual explained
      0% → 73.5%, real verified narrative (no fallback), explicit residual
      statement recorded. Round E task 2 PROVISIONAL lifted (DECISIONS.md).
- [x] Task 3 (Subagent A, verified in main thread, abb4d1e): five drill-down
      catalog queries (catalog 28→33, C6-1 widened), app/insights/drilldown.py
      scoped runs on the contract run_id format with parent_run_id chains,
      budgets 8q/12t product / 6q/10t below via a turn-cap wrapper, rules
      evaluated at the mapped scope with Task 1 skip semantics, transaction
      level provably LLM-free, six endpoints (one additive GET for the
      product_account insight level), honest labelled cost estimates.
- [x] Task 4 (Subagent B, verified in main thread, a7b6c08): DrilldownPanel —
      one general component keyed by a scope descriptor (useDrilldownPanel),
      760px slide-in with scrim/Escape/focus-restore, breadcrumb, three-part
      levels, drillable counts, Stored footer + Regenerate, ungenerated
      estimate-before-spend, ProductTable change cells as real buttons, typed
      API clients; npm build passes; nothing hardcoded.
- [x] Task 5 (Subagent C, verified in main thread, 4df5523): scoped_run_id /
      begin_scoped_run / generation_lock (one generation, concurrent same-key
      callers wait and read); durable SQLite layer (data/runtime/, overridable)
      persisting full runs+findings+logs and full rule dicts incl.
      plan/scopes/plan_by_scope; rehydrate-on-miss RAISES on partial data;
      ensure_v0_seed no-ops after restart (Round F compiled-plans-died problem
      closed); graph mirror unchanged; verify scripts isolated to tempdir dbs.
- [x] Task 6 (main thread): all 12 checks pass with actual output in
      docs/ROUND_G_COMPLETE.md (check 11 code-level — no browser here); one
      REAL scoped generation stored and served identically on re-GET and
      across a process restart via the API; verify a/b/c/e re-run green
      (25/25, 19/19, 13/13, 8/8); servers restarted on this round's code.

## Round F (docs/spec/ROUND_F_SPEC.md)
- [x] Task 1: PROGRESS.md current-position refreshed for Round F (the Round C
      staleness the spec flagged was already fixed in 54a07d0 during Round E;
      this task brings the position line to Round F and commits the Round F
      spec files: ROUND_F_SPEC.md, ROUND_D_EXTRACTION.md,
      PLAN_EXPECTATIONS_FINDINGS.md, MOCKUP_DRILLDOWN.html).
- [x] Tasks 2+3 (Subagent A, verified in main thread, 6e1b0b1): v0 seed is
      exactly 5 rules (FEE_REDUCTION_SHARING and PARTIAL_PERIOD removed,
      NEW_BILLING added at order 25 with data-driven exclude_matched_of —
      overlap probe proved a NEW_ACCOUNT-claimed account is excluded);
      NEW_BILLING fires 17 on 202605, empty-with-reason on 202604; three
      provisions added to the sample PDF as prose and 145 bps pinned as the
      standard schedule (115 only in labelled worked examples, DECISIONS.md);
      re-extraction (Sonnet per .env role pins, $1.72): 38 extracted,
      22 COMPILED (was 15), 4 NEEDS_INPUT, 12 NEEDS_DATA; all three provisions
      compiled with p.2/p.2/p.5 citations, grid-sharing rule extracted with
      p.3 §3.1 citation; miner VALID_TAGS gains "New Billing".
- [x] Task 4 (Subagent B, verified in main thread, 302a939): select_cohort
      (grid-reduction-first, 9/9 flag coverage, 3 no-flag slots),
      generate_extraction_sql (12 templates with the confirmed corrections),
      build_real_data (RAW_CONTRACT of all 12 raw files + ColumnMismatchError
      naming file+column, all transformations in Python, ALL 12 VALIDATIONS
      PASSED, per-file dropped-edge counts, manifest structurally identical to
      the mock generator's), thin load/verify wrappers, schema checklist now
      seven places — all proven on the fabricated data/real_test/ raw set
      (client PostgreSQL unreachable from this Codespace). NOTE:
      docs/spec/EXTRACTION_SQL.md doesn't exist in-repo; templates authored
      from prompts/COPILOT_EXTRACTION_COLD_START.md + corrections.
- [x] Task 5 (Subagent C, verified in main thread, 86c1da9): Chip gains a
      title prop; driver chips pass the matched rule's statement, else the
      single frontend/lib/driverDefinitions.ts table; fallback emits only
      real bullets (1 finding → 1 bullet, probe verified); "cached" →
      "✓ Stored — generated <time> · rule set v<n>" (Trace prompt-cache
      metrics deliberately unchanged); npm build passes.
- [x] Task 6 (main thread): all 10 checks pass with actual output in
      docs/ROUND_F_COMPLETE.md; verify a/b/c/e re-run green
      (25/25, 19/19, 13/13, 8/8); servers restarted on this round's code
      (:8001 healthy, :3001 200).

## Round E (docs/spec/ROUND_E_SPEC.md)
- [x] Task 1: rule grammar REMOVED (app/rules/grammar.py deleted); extractor emits
      plain-English statement/kind/missing (nothing discarded for form); new Rule
      Compiler agent (app/agents/rule_compiler.py, Sonnet, once per rule at approval,
      turn-logged as rule_compile|<key>) emits structured plan JSON; validation =
      the five data-protecting checks incl. EXECUTION against mock data;
      status flow DRAFT→COMPILED→PUBLISHED / NEEDS_INPUT / NEEDS_DATA; rule vertex
      schema V15 (statement/kind/plan_json/explanation/missing_note in DDL,
      schema_catalog, SCHEMA_SPEC); field-to-field + string-ordering comparisons now
      legal (fieldref). FOUND+FIXED en route: document_chunks silently served
      180-char catalog summaries after a process restart (graph mock store is
      process-local) — now rehydrates full text from Chroma and fails loudly
      (DECISIONS.md). Re-run on the sample PDF (real Sonnet): extracted 32 (was 32),
      COMPILED 15 (was 10), NEEDS_INPUT 4 (incl. the deliberately-unstated referral
      cap — no number invented), NEEDS_DATA 13 each naming the exact missing
      field/table (the client conversation list). LLM cost $1.13 (+$0.50 for the
      first, truncated-chunk run that exposed the bug). verify a/b 25/25, 19/19
      (B3-11/12/16/17 updated for the new lifecycle), verify c 12/12.
- [x] Task 2 (PROVISIONAL, DECISIONS.md): published rules pre-evaluate in code before
      the agent loop; fired rules land as pre-matched findings (rule_key, citation,
      evidence rows, source_query=rules_evaluate_plan); residual stated in the opening
      with "the residual is the interesting part"; rule evaluation spends no miner
      queries (exploration_reserved recorded, warn < 6); runs report rule_findings /
      agent_findings / residual_amt / residual_explained_pct. verify_round_c C6-2
      widened for rule-origin findings; 12/12.
- [x] Task 3 (Subagent A, verified in main thread): both MOVING cache anchors removed;
      exactly two anchors remain (system + opening blocks, byte-identical every turn);
      opening pushed past Haiku's 4096-token cache minimum with the full query catalog
      (typed params + return columns) and a schema digest — measured 3,384 -> 7,656
      tokens via count_tokens; STATIC_PREFIX_MIN_TOKENS guard + cache_health()
      reads>writes-after-turn-3 assertion; scripts/check_cache_health.py does a real
      run and asserts from response.usage. Real Haiku run (V000002, 202604->202605):
      7 miner turns + reporter, 10 queries, 21.0s; 65,417 prompt tokens = 10,383
      uncached + 47,172 cache-read + 7,862 cache-write; ONE write on turn 1 then pure
      reads, zero misses (was 5/13 turns missed); cache read 72.1% (target >=70 MET,
      was 28.7%); est cost $0.0364 (target <$0.03 near miss, was $0.0689 — remainder
      is unanchorable transcript replay + output). verify a/b 25/25, 19/19; new C6-13
      passes (committed with Tasks 4-5 — the file also carries B's C6-1 widening).
      Running LLM cost ~$1.67 of $15.
- [x] Tasks 4+5 (Subagent B, verified in main thread): four position queries in the
      catalog (24→28, C6-1 widened): advisor_aum (prior/change NULL on baseline
      month, never 0 or a guess), advisor_flows_summary, cohort_ranking (4 metrics,
      rank vs cohort median), advisor_opportunities (every row data_source='DUMMY');
      matching GSQL files; smoke-tested 20/20/20/36 rows on mock data.
      advisor_nnm_position NOT BUILT — operator override, DECISIONS.md: three months
      of flows cannot proxy an annual NNM measure; only NNM references left in code
      are the reporter's guard that BLOCKS NNM recommendations + rationale comments.
      Recommendations Level 2: search_documents INJECTED into the reporter
      (reporter_sources.py; module still imports only json/logging/re/typing — C6-9
      unchanged); PLAN→thresholds, GUIDANCE→quoted practice, ≤4 searches, all logged;
      verify_recommendations() drops any rec lacking source_query-or-citation, any
      invented number, any NNM text; assert backs the gate; recs persist and
      serialize on the run API. verify a/b/c 25/25, 19/19, 13/13 (incl. A's C6-13).
      $0.00 LLM spent on these tasks.
- [x] Tasks 6+7 (Subagent C, verified in main thread): 6.1 AI Insights owns a
      transition selector (first header control, "Apr 2026 → May 2026 ▲ $62,456"),
      zero Dashboard state, no duplicated bar chart; 6.2 practice view = KPI row
      (Credited Revenue / AUM / Net Flows / Open Exceptions — NNM KPI removed per
      override) + book-level narrative (bookLevel() strips account identifiers) +
      exceptions worklist (advisor, issue, impact, rule citation, click-through);
      new GET /api/insights/practice-summary + /exceptions; 6.3 rule detail shows
      statement/worked example/citation/compiled plan + explanation, edit →
      compile → approve → publish (new version, never mutates); 6.4 Documents &
      Rules renders "N extracted · N compiled · N need a value · N need data we
      don't have" from the extraction-summary API, each gap expandable with its
      reason — nothing hardcoded. Task 7: Trace All Time card (cost, runs, input/
      cache-read/cache-write/output tokens, LLM time) with cache read and WRITE as
      separate tiles+columns (write>read renders red), total rows on runs and
      per-turn tables; new GET /api/trace/alltime. npm run build passes (verified
      in main thread); practice-summary returns real figures (AUM $268.6M, net
      flows $13.6M for 202604→202605). Spec's per-subtask commits collapsed into
      one — work arrived complete from the parallel dispatch.
- [x] Task 8 (main thread): real run V000002 202604→202605 (Haiku miner, Sonnet
      reporter per model policy): 7 miner turns, 10 queries, 1 rule finding /
      0 agent findings, residual $9,502.82 explained 0%, exploration_reserved 9;
      69,354 prompt tokens (14,320 uncached + 47,172 cache-read + 7,862
      cache-write), cache 68.0% (target 70 — near miss), $0.0504 (target $0.03 —
      miss; the Task 5 search loop + Sonnet reporter added cost the Haiku-era
      target didn't anticipate; spec's model policy and cost target now in
      tension), 42.6s, cache_health PASS (one write turn 1, zero misses after).
      ONE recommendation kept by the gate, fully traced (rules_evaluate_plan +
      plan p.3 §3.1 citations, verbatim in ROUND_E_COMPLETE.md). Narrative fell
      back to the template (Sonnet output tripped the numeric gate) — honest
      but cosmetically weak ("No further findings" ×3); 0 agent findings on a
      $9.5k residual is the Task 2 provisional concern made observable.
      NEW scripts/verify_round_e.py 8/8 (E-7 amended: no NNM anywhere);
      verify a/b/c re-run green 25/25, 19/19, 13/13.
      docs/ROUND_E_COMPLETE.md written with actual output. Servers :8001/:3001
      up on forwarded URLs (public visibility still needs the Ports panel).
      Session LLM cost ≈ $1.72 of $15.

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
- [x] Task 5: schema additions — 5.1 phx_dm_pce_opportunity in all five places in one
      commit (DDL + loading job + create/drop, schema_catalog, manifest via generator,
      generate_mock_data builder with data_source='DUMMY' on every row, SCHEMA_SPEC V14;
      edges opportunity_for_household / opportunity_by_advisor); Dummy Data chip on any
      finding whose evidence rows carry data_source='DUMMY' (or an opportunity query);
      5.2 document_type PLAN|GUIDANCE at upload (Form field, default PLAN), GUIDANCE
      rejected by extract-rules (still chunked+embedded), upload UI selector;
      5.3 docs/spec/SCHEMA_CHANGE_CHECKLIST.md. Data regenerated (40 dummy
      opportunities); verify a/b/c 25/19/12; npm build OK.
- [x] Task 6: one Haiku run (V000002, 202604→202605): 14 turns, 12 queries, 67.5k
      prompt tokens (19.1k uncached + 19.3k cache-read + 29.1k cache-write, 28.7%
      hit rate — after adding two cache anchors, DECISIONS.md, because Haiku's 4096
      cache minimum silently defeated the two static breakpoints alone), $0.0689,
      32.4s (was ~427k tokens / 678s), 4 findings, COMPLETE with
      budget_hit_tokens=true (the 60k ceiling demonstrably stops a run).
      verify a/b/c 25/25, 19/19, 12/12 — full output in docs/ROUND_C_FIX_COMPLETE.md.
      Servers left running on :8001 / :3001 forwarded URLs.

## Current position
Round: H (docs/ROUND_H_SPEC.md) — COMPLETE. All 6 tasks done; tasks 2/3/4
      additionally re-verified BY EXECUTION after the mid-round restart;
      docs/ROUND_H_COMPLETE.md has the actual output of all 13 checks plus
      the full scale-test table (--scale 28: 57,657 txns). No limit resized —
      every bound limit degraded as designed and surfaced loudly. verify
      a/b/c/e/h green (25/25, 19/19, 13/13, 8/8, 9/9).
Carried observations: (1) the <$0.03 cost target vs Sonnet-reporter policy
      still needs an operator ruling (advisor run now $0.091, scoped product
      run $0.102); (2) the compiled grid-sharing rule matches 0 rows on mock
      data (reads eff_disc_pct as whole percent) — still worth a look;
      (3) the Task 6 scoped product narrative fell back to the template (the
      Sonnet rewrite tripped the numeric gate even after its repair round) —
      prose quality at product scope is a candidate for a future round;
      (4) editing only a rule's scopes still drops the compiled plan (edit()
      invalidates plans on ANY edit) — cheap to special-case if it annoys.
Also still open: the real client extract (Round D scripts proven on fabricated
      raw CSVs only); per-advisor sweep via scripts/e2e_finish.py; port
      visibility for 8001/3001 needs the Ports panel (gh token lacks the
      codespace scope).
SPEC CHANGE (operator, 2026-08-12): advisor_nnm_position DROPPED and every NNM
      reference removed from the practice view, exceptions table and
      recommendations — three months of net flows cannot stand in for an
      annually-measured NNM figure; even labelled, it presents a proxy as a fact.
      AUM and net flows ship; NNM waits for real data.
Cost: running LLM total ≈ $4.66 project-wide. This session ≈ $0.92 of its $10
      ceiling (cache support $0.01 + cache health $0.14 + forced-limit runs
      ~$0.10 + scale insight run ×2 $0.36 + scale drill-down $0.12 + small
      re-runs in verify sweeps ~$0.19).
Last updated: 2026-08-12 (Round H completion session, after Task 6)
Carry-over from Round C: per-advisor sweep still finishable via
      `python3 scripts/e2e_finish.py` once credits allow; port visibility for
      8001/3001 still needs the Ports panel (gh token lacks the codespace scope).

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
