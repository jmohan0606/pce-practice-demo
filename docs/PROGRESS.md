# Build Progress

## Round 3 (docs/spec/ROUND_3_SPEC.md) — aggregate querying, exceptions model, full UI review
- [x] Task 1 (main thread, 366f746): queries return SHAPES, not rows — 14
      large-result catalog queries reduce in code over EVERY row (totals,
      named counts, per-column stats, top-10 concentration, >3σ outliers,
      optional group_by cut) via app/graph/queries/shapes.py;
      mode/group_by/limit envelope on run_catalog_query (rows default keeps
      API/services untouched); MinerTools + ChatTools default shape; agent
      rows-drill capped at 20; full rows always retained for evidence.
- [x] Task 2 (main thread, c7404e6): EVIDENCE_STORED_CAP + EVIDENCE_DISPLAY_CAP
      REMOVED — every row behind a finding stored, sorted by contribution
      desc, per-column footer totals (evidence_totals) reconcile to the
      headline; API serves the full set; verify_round_h H-4 re-pinned.
- [x] Task 3 (main thread, bf8eead): exceptions model — rates not counts
      (app/insights/exceptions.py): affected/denominator vs the cohort
      distribution; denominator resolves by its own language (revenue →
      dollar-weighted prior-month credited; managed → managed accounts;
      else accounts-in-month, labelled); product_scope narrows denominator
      AND cohort; floor (accounts|dollars) suppresses with the reason named;
      sensitivity flags rate > median + s×stdev (null→1.0 stated). Three
      altitudes: /api/exceptions/firm (one row per RULE) /rule/{key} (ranked
      by rate) /advisor/{sid}. PATCH /api/rules/{key}/exception-config
      (plan-preserving) applied plan-derived config → RSV_v9-11.
      driver_enabled/exception_enabled independent (driver-disabled rules
      still evaluate, produce no driver finding). Worklist ?advisor= filter
      + /api/insights/exceptions/advisors (H4).
- [x] Task 4 (main thread, d5163fd): AI Insights cross-cutting — the
      aggregate run's opening carries the CROSS-CUTTING MANDATE (connections
      / concentration / what-did-not-happen / what-is-about-to-matter);
      reporter cross_cutting flag on practice runs. Driver descriptions
      (4.1) built in CODE from the full match set (app/insights/describe.py):
      accounts named, top-3 share, advisor attribution, tail contribution —
      never the rule definition plus a count.
- [x] Task 5 (main thread, no change needed): jobs API verified live —
      GET /api/jobs (+kind/scope_key filters), GET /api/jobs/{id},
      POST /api/jobs/{id}/resume (INTERRUPTED-only, explicit, never
      automatic) all delivered in Round 1 task 2; smoke-tested this round.
- [x] Tasks 6+7 (main thread): shared UI foundations — Pager (usePager,
      5/10/20 default 5), CompareValue (every number carries its prior-month
      comparison), EvidenceTable (collapsed+note, labelized headers,
      paginated, shrink-to-content, reconciling footer totals),
      lib/labels.ts (labelize/yesNo); globals.css full-width .wrap, bold
      section/metric headers, .rowhead, .chip.newtag, and the ONE
      segmented-toggle rule (.pivot selected bold blue highlighted /
      unselected pale; switches keep their own styling).
- [x] Tasks 8+9 (main thread, shared surfaces): REAL/DERIVED/DUMMY finding
      chips removed from the shared FindingRow (driver tag stays, bold +
      nowrap); 'Source / Citation' prefix on rule links; 'Ask iPerform' →
      'Ask Connect Coach' in ChatPanel/ChatDock/agent persona/flags
      registry/mockup. Page-level removals ride the Phase 3 briefs.
- [x] Pre-dispatch fixes (main thread): B2 retained bug — RETAINED_ACCOUNT
      had been deactivated in the Round C demo trail; reactivated (RSV_v12),
      firm retained 177 == raw continuing-with-revenue count 177; lifecycle
      query now NOTES skipped rules (never a silent zero). B3 NCF derivation
      verified (total_net_financial_flows end to end — it IS Net Cash
      Flows). F2 root cause: rule findings carried group_id null —
      dominant_group() attribution (>=50% of matched revenue, never
      guessed) + group_name serialized. B7 coaching points gain severity
      from the rules' own severity model, sorted Critical→Info. D8:
      GET /api/dashboard/lifecycle (scope = group|advisor|all). D2/B1:
      aum_managed on advisor + practice summaries. FOUND+FIXED: shape
      results were mislabelled 'a SAMPLE' and recorded a phantom ROWS_SHOWN
      limit (miner + chat). Operator mid-round bug: coach/chat/guardrail
      model defaults were hardcoded Claude ids — now empty (unset role
      falls through to the primary LLM_MODE; proven by execution on a
      simulated cdao_openai/gpt-5.5 env). scripts/verify_round_3.py 10/10.
- [x] Task 10 (Subagent A, verified in main thread, a3823eb + 50d3540): all
      31 batch-1 B–H items + the firm exceptions altitude (one row per RULE
      from /api/exceptions/firm, drill-in ranked by rate); AUM off the
      chart; en-dash prefixes; drill-down LifecycleStrip/volume tile/
      managed-only AUM tile; shared EvidenceTable everywhere; worklist
      one-advisor default + advisors-with-exceptions dropdown; F2 pivot
      renders group_name. Follow-up 50d3540: contribution rows resolve
      Name (SID) via a cached /api/advisors map (found by observation).
- [x] Task 11 (Subagent B, verified in main thread, c92c3b8): batch-2 §B —
      ASSUMED/Dummy/apology text gone; aum_managed tile labelled; NCF (Net
      Cash Flows); Revenue Drivers + fixed pivot; value-based peer-ranking
      colour (thirds, rule stated); coaching reordered with severity chips;
      opportunities Amount/red-negative-days/Stalled-column-removed/
      glossary tooltips; NNM section properly titled.
- [x] Task 12 (Subagent C, verified in main thread, ad4dcb0): Documents &
      Rules redesigned into four tabs (Documents/Rules/Exceptions/Write a
      Rule) — full-width paginated rules, compiled query collapsed, attempts
      on click, NO horizontal scroll bar; NEW Exceptions tab with the
      independent toggles + materiality editing via exception-config PATCH
      (honest em-dash nulls, scope-source provenance, refetch-after-mint);
      Rule Versions paginated with v0 visible/editable; Trace paginated with
      the amber tint documented in a legend.
- [x] Phase 4 (main thread): verify_round_3 10/10; ALL suites green (a25
      b19 c13 e8 h9 a1-17, r1 12, r1b 8, r2a 16, flags 8, manual 17, nnm 19,
      parity, npm 8 routes); every screen OPENED and read in headless
      chromium (checks 11–25 in docs/ROUND_3_COMPLETE.md with what was
      actually seen). RSV_v12 regeneration: aggregate + 7 advisor runs
      landed (cross-cutting narrative pasted; data-driven driver text on
      screen; ROWS_SHOWN truncations 5→0) before the Anthropic credit
      balance ran out — 13 advisor runs failed isolated-and-recorded;
      serving falls back to their prior COMPLETE runs. FOUND+FIXED en
      route: shape results mislabelled as samples (phantom limit);
      version-id STRING comparison served RSV_v8 over RSV_v12; FAILED
      regenerations displaced served content; token ceiling now
      COST-WEIGHTED (cache reads 0.1×) — was a hidden ~16-turn cap;
      coaching severity resolves at read time. Session app-LLM spend
      ≈ $1.25 of the $15 ceiling. Servers :8002/:3002 left running;
      public visibility still needs the Ports panel (carried).

## Round 2a (docs/ROUND_2A_EXTRACTION_SPEC.md) — extraction ready for the real load
- [x] Task 1 (main thread, f6a1b42): ingestion batch size 5000 — the MEASURED
      default (3,169/5,375/7,706 rows/s at 500/1000/5000, 54ms round trip).
      New INGESTION_BATCH_SIZE setting (env override beats manifest); both
      generators + committed data/manifest.json carry 5000; _BATCH_OVERRIDES
      removed; INGESTION_MAX_BATCH_CALLS_PER_ENTITY 500→10,000 (12.4M/5000 =
      2,488 legitimate calls — the measurement Round H deferred).
- [x] Task 2 extraction side (main thread, 7188a19): temp-table scoping —
      00_session_setup.sql (cohort_adv + scoped_acct ONCE per session,
      re-created on every reconnect; a token refresh IS a reconnect); NO
      template inlines SIDs/account keys; five chunk families (balances per
      month never a UNION; account/eci_rel/eci_map by hashtext --buckets
      default 4; txn month × 200-advisor batch) = 109 checkpointed resumable
      chunks at firm scale; dry-run per-chunk projections from committed
      EXPECTED_COUNTS.json + >2M warning; 20GB disk check; adv_flows extends
      to June (166,985 aggregated of 19.4M daily); advisor_flags reduced to
      the four consumed columns. verify_round_1 R1-8b re-pinned.
- [x] Task 2 build side (main thread, 312a4cd): build_real_data STREAMS the
      four large entities (txns row-by-row with monthly_revenue accumulating
      in-pass; account/eci_rel/eci_map per bucket; account_month one month at
      a time from spilled per-month aggregates holding only the prior month's
      map); stage-then-commit preserves never-a-partial-build;
      --max-memory-mb guard (4096) with per-entity peak RSS in
      build_report.json; missing-bucket/both-forms refuse; CRM firm-wide file
      FILTERED to in-scope advisors/ECIs (out-of-scope count REPORTED,
      *_CWM_INVALID kept+reported — operator mid-round requirement). FIXED
      pre-existing bug: opportunity vertex wrote the pre-F2 dummy shape and
      advisor_nnm was missing from the built manifest (dangling nnm edges) —
      old-vs-new diff on the same drop differs ONLY in those fixes; chunked
      == single-file builds proven identical. Validator V-2/V-3 chunk-aware
      for all five families; transactions stream through V-7..V-10.
- [x] Task 3 (main thread, 793279a): manifest phase field (1=vertices,
      2=edges) in generators + committed manifests; load_real_data.py is its
      own two-phase orchestrator — --max-parallel (default 3) per-phase
      ThreadPoolExecutor, per-worker IngestionService, stop-flag halts
      siblings on failure and the phase fails (phase 2 never starts);
      assert_phase_complete REFUSES phase 2 while any phase-1 checkpoint is
      not COMPLETED (proven); SQLite 30s busy timeout. Fixture 49/49 loaded,
      0 mismatches.
- [x] Task 4 (main thread, 8fe062c): reconcile_load.py — three-way
      source/extracted/built/loaded proof per entity, CRM + NNM included;
      build_report.json records every explained delta; unexplained difference
      = hard failure naming entity + both numbers (40k-drop probe proven);
      committed EXPECTED_COUNTS.json baseline compared by default.
- [x] Task 5 (operator-authored, 8a1a688): docs/COPILOT_EXTRACTION_GUIDE.md
      delivered as planned — written separately AFTER the round's scripts
      landed so it describes what exists (extract → validate → build → review
      gate → two-phase load → reconcile, token-expiry resume, measured
      143M-row/2.9h figures). docs/CONNECTION_DETAILS.md deliberately NOT
      committed (credentials per its own header; gitignored). verify check 11
      still prints SKIP by design — the deferral was the pinned behaviour.
      Runbook Phases 2/3/5 surgically updated to stay truthful (task 6
      commit).
- [x] Task 6 (main thread): scripts/verify_round_2a.py 16/16 (check 11 =
      the deferred guide, marked SKIP); 12.4M-row streaming proof via
      scripts/make_scale_proof.py at the client-measured cardinalities;
      actual output in docs/ROUND_2A_COMPLETE.md. Regression all green
      (a25 b19 c13 e8 h9 a1-17, flags 8, manual 17, nnm 19, round_1 12/12,
      round_1b 8/8, parity, npm 8 routes). Servers :8002 (healthy, 0
      mismatches) / :3002 (200). Session LLM spend $0.00 of the $4 ceiling.

## Round 1b (docs/spec/ROUND_1B_SPEC.md) — final schema additions (schema closes)
- [x] Task 1 (main thread, aeffaf4): job_code STRING on phx_dm_pce_advisor
      (confirmed pcr.fpic_employee_tb.job_cd varchar(30) not null) across
      DDL/schema_catalog/SCHEMA_SPEC/loading job/manifest; raw_advisor.sql
      selects COALESCE(e.job_cd,'') on the existing em_standard_id join;
      blank stays blank (V000008 mock + counterparties). Committed advisor
      CSV updated by deterministic column-append post-pass (no RNG); field
      CARRIED only — no plan-applicability logic (client mapping pending).
- [x] Task 2 (main thread, 9d6ad1f): l1_pay_type_cd/l2_pay_type_cd on
      phx_dm_pce_product — the export's parallel snake_case taxonomy carried
      ALONGSIDE the unchanged grouping; extraction SQL selects
      level_one/two_pay_type_product_cd; build_real_data passes through
      (txn-only products blank, never guessed); mock PAY_TYPE_CODES
      transcribed from PRODUCT_HIERARCHY_FULL.md; committed product CSV
      post-passed.
- [x] Task 3 (main thread, a6835be): referrals_private_bank 26th group —
      PCS splits on sub-code like ELIS/LEND (PCS/SP RECURRING unchanged,
      PCS/PBR NON_RECURRING, unknown sub -> unmapped, sub-less PCS kept as
      SP for the committed pre-split rows — documented alias). Committed
      data additive post-pass only (group row + PCS|PBR product + edge,
      manifest 26/32/32, NO transaction touched — PBR honestly revenue-less
      in mock, B1-5 re-pinned). Fixtures reshuffled legitimately and now
      prove the split end-to-end. Pins widened: verify_round_a 3a/3b.
- [x] Task 4 (main thread, 48f6338): migrations/002_schema_additions.gsql —
      one GLOBAL SCHEMA_CHANGE JOB, two ALTERs, no data statement; grown
      task-by-task so every commit stayed parity-green.
      verify_schema_parity.py applies ALL migrations/0NN_*.gsql in order:
      baseline_f2 + 001 + 002 == clean install 31V/44E; corrupted-002 probe
      fails SP-4 naming l2_pay_type_cd (proven). Four DECISIONS recorded.
- [x] Task 5 (main thread, 439912a): runbook Phase 1 = three explicit
      install paths (fresh DDL-only / F2 -> 001+002 / Round-1 -> 002 only),
      parity required after every path; Phase 5.4 rollback (resumable rerun
      normal; 90_drop_all + reinstall the stated-destructive last resort;
      never hand-edit CSVs).
- [x] Task 6 (main thread): NEW scripts/verify_round_1b.py — 8/8 PASS run
      twice; all spec checks with actual output in docs/ROUND_1B_COMPLETE.md.
      Regression all green (a25 b19 c13 e8 h9 a1-17, flags 8, manual 17,
      nnm 19, verify_round_1 12/12, parity, npm build 8 routes). Servers
      restarted on this round's code/data (:8002 healthy 0 mismatches,
      :3002 200); public visibility still needs the Ports panel (carried).
      Session LLM spend $0.00 of the $3 ceiling.

## Round 1 (docs/spec/ROUND_1_SCHEMA_FREEZE_SPEC.md) — schema freeze + client runbook
- [x] Task 1 (main thread): eight exception-configuration attributes on
      phx_dm_pce_rule (DDL / schema_catalog / SCHEMA_SPEC / store mirror
      _RULE_GRAPH_ATTRS) — driver_enabled and exception_enabled INDEPENDENT;
      denominator/floor(+unit)/sensitivity/product_scope(+source). Defaults:
      three rules exception_enabled=true (DISCOUNT_SHARING_THRESHOLD_TRIGGER /
      DISCOUNT_SHARING_MINIMUM_GRID_RATE / LOST_ACCOUNT — mapping in
      DECISIONS.md), everything else driver-only; applied by setdefault at
      store normalization so rehydrated stores migrate in place and proposals
      are never overwritten. Extractor PROPOSES denominator/floor/scope from
      the provision's own language with product_scope_source the citation or
      "NOT STATED" — null honest, nothing invented (scripted-LLM proven). All
      eight fields plan-preserving-editable + always serialized on the rules
      API. Suites a/b/c/e/h green.
- [x] Task 2 (main thread): phx_dm_pce_job + job_for_document/job_for_run in
      every schema place (31V/44E) — app/shared/jobs.py JobStore (durable
      data/runtime/jobs.db + graph mirror; runtime upsert IS the loading job,
      turn-log precedent). Wired: document ingest (parse→chunk→embed then
      COMPLETE-at-embed; extract REOPENS the job per-window with
      resume_token={next_window} — extract_with_job persists EACH window
      before the next, so an interruption loses at most one window and resume
      repeats none, PROVEN: interrupt at window 2 of 3 → INTERRUPTED
      {next_window:2} → resume made exactly 1 LLM call; compile/audit
      per-stage touches), insight generation (evaluate_rules→
      investigate_residual with per-turn items→narrate→persist, run_id edge,
      FAILED carries the error), data_load (load_mock/real_data: one stage
      per entity; ingestion checkpoints are the real resume). Resume is
      EXPLICIT: GET/POST /api/jobs + /{id}/resume (?resume=1 on
      extract-rules). All suites green (a25 b19 c13 e8 h9 a1-17, flags 8,
      manual 17, nnm 19).
- [x] Task 3 (main thread): migrations/001_exceptions_and_jobs.gsql — one
      GLOBAL SCHEMA_CHANGE JOB (valid on an installed 4.2.2 graph): the eight
      rule attributes + phx_dm_pce_job + both edges ADDed to the graph; NO
      DROP or data-touching statement anywhere. F2 baseline snapshotted from
      commit 388bf22 into migrations/baseline_f2/.
      scripts/verify_schema_parity.py: parses GSQL, applies the migration to
      the baseline IN MEMORY and requires equality with the clean install
      (names AND types), plus data-safety scan, 03_create_graph exact type
      list, schema_catalog==DDL both ways, and 90_drop_all exact-reverse
      order — 13 PASS on 31V/44E; a deliberately corrupted migration fails
      SP-4 naming the missing attribute (proven). Manifest +
      generate_mock_data untouched BY THE CHECKLIST'S OWN RULE (both
      additions are app-written — no CSV load).
- [x] Task 4 (main thread): docs/spec/SOURCE_TO_VERTEX_MATRIX.md — THREE
      source kinds (PostgreSQL tables, the four NNM .txt files, the CRM
      .csv), the derived vertices named (monthly_revenue/rpg/household),
      seeded constants, all 13 app-written vertices with their writers, and
      the edge rule; script-checked that every one of the 31 DDL vertices
      appears (missing: NONE).
- [x] Task 5 (main thread): three source kinds in ONE directory
      (data/real/_raw): raw_*.csv PostgreSQL extracts, the four NNM .txt
      files under ORIGINAL names, crm_opportunities.csv.
      build_real_data.detect_sources() detects by filename pattern BEFORE
      reading — 3-of-4 NNM refuses to start (proven verbatim), ambiguous
      duplicates refuse, txn table accepted as extract_chunked chunks
      (per-chunk contract, sorted concat — 6-chunk build ALL 12 VALIDATIONS
      PASSED, identical totals to the single-file build).
      scripts/extract_chunked.py: month × advisor-batch (default 200) chunks
      for the trade table + 11 single-table chunks, SQL from
      generate_extraction_sql.templates() (one source of truth; txn template
      date bounds re-scoped per month, count asserted), checkpoint JSON with
      plan fingerprint, --dry-run offline plan, resume DEFAULT/--restart
      explicit, atomic .part writes, clean token-expiry exit with the resume
      instruction (stub-connection proven: fail at chunk 14/17 → rerun runs
      exactly the 3 remaining). NEW scripts/validate_raw_extracts.py V-1..
      V-10 over all three kinds (chunk-gap + checkpoint row cross-check,
      contracts, NNM parse, CRM, key normalization, reason_cd spelling,
      month agreement, unmapped product codes with counts, the $33k/advisor/
      month sanity anchor naming proc_dt/team-join when out) — 11 PASS on
      the fabricated drop ($33,200 measured); gap and row-mismatch
      corruptions both FAIL loudly (proven).
- [x] Task 6 (main thread): docs/CLIENT_ENV_RUNBOOK.md — Phases 0–6,
      numbered, exact command + correct-result + what-to-do-when-not at
      every step; Phase 3.1 states the exact file placement of all three
      source kinds in data/real/_raw (original NNM filenames, load-bearing);
      Phase 4 is the HARD REVIEW GATE ("STOP HERE", wait for explicit
      go-ahead); token-expiry resume procedure stated verbatim; 46-query
      catalog count corrected from the spec's 38; both embedded snippets
      (46/46 catalog sweep, monthly-total reconciliation) EXECUTED here and
      proven (reconciliation matches to the cent). NEW
      prompts/COPILOT_SIZING_AND_RATE.md (Part A row-count SQL incl. the
      cohort.txt query extraction needs; Part B measured-ingestion-rate
      procedure with the p95×1.2 projection rule).
- [x] Task 7 (main thread): NEW scripts/verify_round_1.py — 12/12 PASS, run
      twice (repeatable; the R1-5 probe now isolates the knowledge catalog
      too). All 10 spec checks with actual output in
      docs/ROUND_1_COMPLETE.md, including the LIVE Sonnet extraction over
      the real plan document proposing exception config with page citations
      (DISCOUNT_SHARING_THRESHOLD_TRIGGER: denom 'managed accounts', scope
      'products billed on the Standard Managed 145 bps Fee Schedule', src
      'Page 3, Section 3…'; unstated → null + NOT STATED — ≈$0.08, the
      session's only LLM spend). Regression all green (a25 b19 c13 e8 h9
      a1-17, flags 8, manual 17, nnm 19, parity, npm build 8 routes).
      Servers restarted on this round's code (:8002 healthy with /api/jobs,
      :3002 200); public visibility still needs the Ports panel (carried).

## Round F2 (docs/spec/ROUND_F2_CRM_NNM_SPEC.md) — real CRM data, NNM, plan-unlocked rules
- [x] Task 1 (main thread, d5eb45c): discovery AUTHORED, not run — no client
      data source reachable here (no PostgreSQL; neither the real CRM extract
      nor the NNM files are in-repo). discovery_job_code.sql +
      discovery_crm_amount.sql committed as operator-run artifacts with
      how-to-read notes; working assumptions in DECISIONS.md (amount=forecast
      pipeline / actual_assets=landed, NEVER summed; job_code NOT added until
      discovery answers — manufactured schema refused); plan tables enter ONLY
      via document files (the new PCA-style doc renders from a non-Python
      content source via the generic scripts/render_plan_pdf.py).
- [x] Pre-dispatch foundations (main thread, dabbe39): both vertices in every
      schema place (30V/42E) — real 23-column CRM opportunity shape replaces
      the V14 dummy; phx_dm_pce_advisor_nnm + nnm_by_advisor/nnm_in_month;
      catalog.py end-of-module merge hooks (crm_catalog.py=A, nnm_catalog.py=B
      — zero shared-file edits across three concurrent subagents);
      scripts/parse_nnm.py with frozen signatures, deterministic round-trip.
- [x] Tasks 2+3 (Subagent A, verified in main thread, 9b13a9b): mock builder
      is an ADDITIVE post-pass (own RNG; every committed credited CSV
      byte-identical, proven by git diff) — 77 CRM rows (4 *_CWM_INVALID refs
      kept+reported, stage_group from the 14 transcribed stages with UNGROUPED
      counted never guessed, NO Won/Lost anywhere, comments never
      keyword-parsed) + 480 NNM rows generated THROUGH parse_nnm; ingest 49
      targets 0 mismatches. ai_read pass (real Haiku, crm_ai_read|*): 60
      comments, 35 readings / 42 no-signal, substring gate 0 violations,
      $0.026, re-run no-op. build_real_data on fabricated raw set: ALL 12
      VALIDATIONS PASSED, 4 invalid refs reported. 5 CRM catalog queries
      (spec's 4 + advisor_opportunity_detail) with GSQL twins;
      /api/advisor/{sid}/opportunities on the fixed contract (data_quality /
      assumption_note / won_lost_note). Main-thread fixes: crm_catalog
      circular import (both orders proven); legacy flows-proxy NNM block +
      hardcoded-$4MM note REMOVED from the advisor summary.
- [x] Task 4 (Subagent B, verified in main thread, 55cf41f): parse_nnm
      hardened (duplicates raise naming both lines); check_nnm_parse 19/19.
      advisor_nnm_position / advisor_nnm_all_categories(+TOTAL) /
      nnm_threshold_position — latest-month YTD IS the position (never a sum
      of MTD, never annualised); threshold resolves AT READ TIME from the
      published extracted rule (zero/conflicting candidates → honestly
      unavailable with the reason named); GET /api/advisor/{sid}/nnm on the
      fixed contract (EC confirmed=true only, raw file prefix on every
      category, assumed_note). Re-pins: C6-1 38→46; E-7 re-amended (NNM
      confined to sanctioned surfaces, reporter guard intact, NO hardcoded
      plan threshold in any .py — now a permanent pin).
- [x] Tasks 5+6 (Subagent C, verified in main thread, d7dceac): advisor page
      Managed/Brokerage split REMOVED; four real categories (EC prominent vs
      the API-resolved threshold + ASSUMED chip; raw-file-prefix tooltips on
      the three inferred ones; total; MTD+YTD with as-of month; NO dollar
      threshold anywhere in the frontend); Opportunities rebuilt — stage-group
      summary, stalled callout with days-past-due chips, three-provenance
      columns (Stage / verbatim Notes / ◆ AI chip with confidence+evidence
      hover, "No signal" never blank, non-sortable), Dummy chips gone from
      CRM, assumption + no-Won/Lost notes, invalid-advisor data-quality line;
      ChatMarkdown renders ai_read table columns as the AI chip. npm build 8
      routes.
- [x] Task 7 (main thread): all 19 checks with actual output in
      docs/ROUND_F2_COMPLETE.md. CHECK 12: cwm_pca_plan_2026.pdf (content in
      a non-Python .md, generic renderer) uploaded → real Sonnet extraction
      found ALL THREE tables with page citations (26 rules: the full grid in
      MONTHLY_INCENTIVE_GRID_CALCULATION p.2, the discount-sharing series
      p.3, NNM_AWARD_THRESHOLD + the award-rate bands p.3, SAG definitions
      p.4); NNM_AWARD_THRESHOLD + two discount-sharing rules COMPILED and
      published as RSV_v8; the /nnm endpoint's threshold went
      available=false → {4000000.0, R_NNM_AWARD_THRESHOLD_RSV_v8, gap
      306211.01} — the $4MM figure reached the UI through extraction alone.
      CHECK 13: grid rates / award bps / $4MM / $500 in NO Python file (grep
      pasted; sanctioned exceptions stated up front in DECISIONS.md). CHECK
      18: no aggregate touches ai_read (grep pasted). Browser-observed 11/14/
      17 (four categories + ASSUMED threshold line; Dummy gone + assumption
      note; ◆ AI chip with "confidence 85% — evidence: …" hover, No signal
      cells, STALLED · Nd PAST DUE chips, invalid-advisor line on V000003).
      Tiered band schedules honestly NEEDS_DATA at compile (no tiered-band
      construct in the plan grammar — named per rule, client conversation).
      All suites green: a 25/25 · b 19/19 · c 13/13 · e 8/8 · h 9/9 ·
      a1 17/17 · flags 8/8 · manual 17/17 · nnm_parse 19/19; npm build 8
      routes. Pre-generated on RSV_v8: practice aggregate BOTH transitions +
      V000001/V000014/V000019 both transitions.

## Round E chat (docs/spec/ROUND_E_CHAT_SPEC.md) — conversational chat
- [x] Task 1 (main thread): Layer 2 tool boundary — app/chat/tools.py ChatTools
      with EXACTLY four capabilities (run_catalog_query validated-before-
      execution, search_documents, get_stored_insight, generate_insights the
      one write); no other method exists — approve/publish/rename/toggle are
      unreachable at the tool layer, never by prompt. app/chat/verify.py:
      unverified_figures (reuses the reporter's numeric machinery) +
      system_prompt_leak literal substring check. New roles chat
      (CHAT_MODEL=claude-opus-4-6, probed live) + chat_guardrail (Haiku);
      chat budgets in settings with env aliases (CHAT_QUERY_BUDGET=6,
      CHAT_MAX_TURNS=10, CHAT_MAX_SEARCHES=4, block threshold 0.8). Two-layer
      design + do-not-tighten warning recorded in DECISIONS.md.
- [x] Task 2 (main thread): Layer 1 — app/chat/guardrail.py classifies every
      message into CLEAN/PROMPT_INJECTION/JAILBREAK/SQL_INJECTION/
      SOCIAL_ENGINEERING/DATA_EXFILTRATION/OFF_TOPIC with confidence; blocks
      ONLY attack tags at >=0.8; OFF_TOPIC never blocks (redirect, not
      refusal); mixed messages get BLOCKED_PARTIAL with the legitimate half
      extracted and answered; classifier unavailability degrades LENIENT
      (proceed untagged — Layer 2 contains), the opposite of V2's fail-safe
      refusal. Live-proven on Haiku: 7/7 correct incl. the V2 story-wrapped
      case (BLOCKED_PARTIAL, legit='Show revenue for V000014') and broad
      data questions staying CLEAN.
- [x] Task 3 (main thread): conversation agent — app/chat/agent.py JSON-action
      loop on Opus (query/search/get_insight/generate_insights/note/confirm/
      answer), sentence-first answers, note-action reference resolution stated
      in the steps, page context as a default not a constraint, confirm only
      when genuinely ambiguous, tool failures said never hidden, budget binds
      surfaced; in-code verification (regenerate once naming figures →
      deterministic what-was-found fallback) + literal system-prompt-leak
      replacement; service.py streams guardrail→step*→answer→done (SSE),
      every LLM call turn-logged under chat|<conversation_id>; store.py
      working in-memory baseline behind the Task-4 interface; router behind
      global.chat (OFF = endpoints 409). LIVE-proven on real Opus: reference
      resolution ('her'→V000013 stated as a step), rule citation link, the V2
      partial-block case (injection blocked + revenue answered, tools 2),
      full block (tools 0, no agent call), ~$0.04/message.
- [x] Tasks 4+5 (Subagent A, verified in main thread): durable ChatStore —
      SQLite write-through (data/runtime/chat.db) + rehydrate-on-construction
      + graph mirror of phx_dm_pce_conversation / phx_dm_pce_chat_message /
      message_in_conversation edge (runtime upsert IS the loading job, no CSV
      job — turn-log precedent); schema 29 vertices / 40 edges across DDL /
      schema_catalog / SCHEMA_SPEC, zero pins widened; restart survival proven
      across two processes (4 messages + guardrail_log intact, _history()
      serves the rehydrated rows the agent resolves 'her' against); delete is
      three-layer and proven; endpoints already matched the Task-5 spec and
      now run durable; flag-off 409 re-proven; global persistence recorded as
      the demo simplification (DECISIONS.md).
- [x] Task 6 (Subagent B, verified in main thread): ChatDock/ChatPanel/
      ChatMessage/ChatHistory/ChatMarkdown + chatApi (fetch-ReadableStream
      SSE) + chatContext pub/sub (dashboard + advisor pages publish their
      selection in one-line effects); 440px docked panel on every page with
      the floating Ask iPerform pill, localStorage open/conversation
      persistence, ?chat= deep link; context bar with keyed Clear context and
      answered-context updates; markdown renderer with app-token tables,
      NarrativeText figures, SID autolinks, rule:/doc: link schemes; live
      pulsing reasoning collapsing to 'Show reasoning · N steps · Ns';
      guardrail block chip with 'Tools called: 0' + partial answers beneath;
      confirm box prefills the composer; suggestions refresh with context;
      footer verbatim; global.chat off renders nothing and 409s handled.
- [x] Task 7 (Subagent C, verified in main thread): GET /api/trace/guardrail
      (?tag= narrows rows, summary/total always full — honest chips) +
      Guardrail tab on Trace: When / expandable Message / coloured Tag chip /
      Confidence / Action / bold Tools called (0 on blocked rows) /
      Conversation link to /?chat=<id>; summary chips filter; chat scopes in
      the runs table now kind "chat".
- [x] Task 8 (main thread): ALL 23 checks ran as REAL conversations against
      the live servers (real Opus agent, real Haiku classifier; headless
      chromium for the visual ones) — verbatim exchanges in
      docs/ROUND_E_CHAT_COMPLETE.md (the spec's ROUND_E_COMPLETE.md name is
      taken by the earlier insights round; overwriting it would have destroyed
      that record). Check 5: injection tagged+blocked with the chip stating no
      tool could return a prompt anyway AND the revenue half answered (tools
      1). Check 9: answered directly, zero confirmation friction. Check 14's
      turn log shows the numeric gate observably rejecting a first draft and
      repairing it (check 12: 0 unverified figures across all 14 answers).
      Check 19 resolved 'she' + 'the top managed accounts advisor you listed
      earlier' from the rehydrated transcript across TWO backend restarts.
      Check 22 (CHAT_QUERY_BUDGET=2): the agent says the budget bound and
      offers narrower options. Check 23: injected TimeoutError stated in the
      answer, ERROR row in the query log. FOUND+FIXED by observation: ###
      headings/--- rendered literally; navy-on-navy advisor links in message
      table headers. Timings honest: 7.5–11.4s no-tool/single-query, 43–66s
      multi-query fan-outs. Verify a/b/c/e/h/a1 green + check_flags 8/8 +
      check_manual_rules 17/17; npm build 8 routes. Session chat spend ≈ $1.0
      of $12. Tasks 4–7 landed in one verified commit c489c80 (parallel-
      dispatch collapse precedent).

## Round C docs/rules (docs/spec/ROUND_C_DOCS_RULES_SPEC.md) — documents & rules management
- [x] Task 1 (main thread, a4ea703): applies_to PRACTICE|ADVISOR|PRODUCT|ALL
      (+key) filters evaluation BEFORE Round G's scopes — orthogonal axes,
      each skip has its own reason, never an error; evaluate_rule_set gains
      group_id (drill-down passes its product group); four-tag provenance
      (RULE_PROVENANCE_TAGS code→chip label, provenance_label serialized,
      glossary definitions) with ALL SIX v0 rules renamed TECH_TEAM_WRITTEN
      (rehydrated stores migrate in place); STANDARD_MANAGED_FEE_BPS=145.0
      pinned in app/shared/fee_schedule.py with its three schedule citations
      (no 115 constant by design). B3-13 re-pinned.
- [x] Task 2 (main thread, 6b7da20): active flag independent of status —
      set_active = edit→approve→publish in one call, plan preserved, reason
      REQUIRED both directions, who/when/why on the row AND version notes;
      inactive rules feed NOTHING into new runs (evaluator skip + miner-context
      filter) while staying queryable with prior insights valid; delete of
      UNAPPROVED rules only, enforced AT THE STORE (all-or-nothing);
      PATCH /{key}/active + POST /delete.
- [x] Shared foundations (main thread, pre-dispatch): frontend/components/rules/
      chips + ReasonModal + PlanView + RuleListManager shell as a fixed
      contract; frontend/lib/rulesApi.ts owns the round's new-endpoint clients
      — the reason three concurrent subagents produced zero file conflicts.
- [x] Tasks 3+4 (Subagent A, verified in main thread, 29162a8+d183286): six
      document categories on document_type (only PLAN+FAQ feed the extractor,
      refused honestly at the one extraction route; category PATCH with
      extraction_offered), .txt/.csv parsing (colon/title-case headings; csv =
      one has_table chunk), 145→125 conflict sample authored; RuleListManager —
      counts line with expandable reasons, data-derived filters, group
      select-all, mixed-selection Delete honestly disabled with the store's
      rule stated.
- [x] Tasks 5+6 (Subagent B, verified in main thread, 36501ff): POST
      /api/rules/manual (two MANUAL tags only); generate_query=false →
      natural_language_only guidance (no plan BY DESIGN, approve()'s one
      documented exception, evaluator skip, labelled MANUAL GUIDANCE block in
      the miner opening, "Guidance only, not computed" in the UI);
      promote/demote version-mint with required reason; three seeded
      MANUALLY_WRITTEN_TECH examples (BILLABLE_DAYS + QUARTERLY_BILLING_CYCLE
      compile honestly simplified, FEE_SCHEDULE_VARIANCE lands NEEDS_DATA
      naming the ratio-of-aggregates gap); recompile-with-note keeps every
      attempt (append-only, pick re-validates, turn-logged rule_compile|key);
      check_manual_rules 17/17; B's real LLM spend $0.17.
- [x] Task 7 (Subagent C, verified in main thread, 61cb6bc): Rule Versions —
      every version incl. v0/superseded expands to full detail and every rule
      is editable (closes the client's cannot-see-v0 complaint); RuleEditDialog
      (recompile is a real choice); VersionCompare client-side diff by
      rule_code over meaningful fields, churn ignored; Inactive amber with
      who/when/why, distinct from Superseded; never-fired kept.
- [x] Task 8 (main thread): ALL checks observed live (headless chromium for the
      visual ones) — actual output in docs/ROUND_C_COMPLETE.md. Check 11: the
      one-line 145→125 .txt produced a real OVERLAPPING_POPULATION_TRIGGER /
      SUPERSEDE proposal with both citations (compile-then-audit; the
      uncompiled draft honestly has no population to overlap). Check 20: the
      document→rule→insight→citation chain shown END TO END for the first time
      — dashboard bullet cites plan_addendum_2026.txt · p.1 · Account
      Concentration Review (A2B carried observation #1 closed). FOUND+FIXED by
      observation: extractor citations carried no document_name, so the UI's
      citation line fell back to "No document citation" on document-derived
      rules — both citation serializers now resolve it from document_id.
      21-run insight batch regenerated on RSV_v7. verify a/b/c/e/h/a1 green,
      check_manual_rules 17/17, check_flags 8/8, npm build 8 routes.
Note: subagents reported, the MAIN THREAD re-verified by execution then
      committed each task (subagents never ran git or touched this file).

## Round A2B (docs/spec/ROUND_A2B_SPEC.md) — dashboard UI + advisor page + coaching + flags
- [x] Task 1 (main thread, fb08b3d): shared foundations — useGlossary/<Term>
      (session-cached, ONE tooltip source, no hardcoded explanatory strings),
      <Money>/<Pct>/<Delta> + NarrativeText prose parser, <DriverChip>
      read-time labels, <AdvisorLink> Name (SID) → /advisor?sid=,
      <RuleCitation> with the tech-written fallback; all A2B CSS + tokens;
      shared api.ts clients so subagents never touched api.ts/globals.css.
- [x] Tasks 2+3 (Subagent A, verified in main thread, 4da4384+bc3f83c):
      TransitionChart (shared prop contract with the advisor page, four views
      each with own colour+legend, AUM bold navy, tint-never-solid pills) and
      page.tsx (advisor dropdown REMOVED, chart fetches on view change only);
      ProductChangeTable (th.grp column groups, 12px headers, drill buttons,
      __TOTAL__ distinct-account row, no roll-up), TopBottomModal (≤10/side,
      null dominant driver → "AI Insights not generated yet"), ExportMenu.
- [x] Task 4 (Subagent B, verified in main thread, 9260399): InsightsSection
      (every ruled bullet links rule + citation, per-transition Generate with
      honest projection), DriversSection (By Driver/By Product client-side
      pivot), NoncreditedSection + CauseDetailModal (four cause-specific
      shapes; eligibility grouped by product, no advisor column),
      ExceptionsSection (server-side severity filter) — self-contained
      components with a common {fromMonth, toMonth, monthName} contract.
- [x] Task 5 (main thread, 7aa6f78): assembly chart → table → insights →
      drivers → non-credited → exceptions, one transition drives all,
      sections fetch independently; <Gated> flag wiring throughout.
- [x] Tasks 6+7 (Subagent C, verified in main thread, f4a971e+01302da):
      /advisor "iPerform Advisor AI Insights" (search name/SID/rep code,
      Team/Individual chip, lifecycle+AUM+NCF+NNM-both-ways metrics — NB/YI/
      EC/FS absent from feed, stated; ASSUMED chip on $4MM), Single/Compare
      drivers, peer ranking (discount rank prominent), coaching agent
      (Haiku coach role, GUIDANCE-only retrieval, citation-gated; real run
      V000002 2 points $0.0024) + authored guidance PDF uploaded as GUIDANCE,
      CRM opportunities with Dummy chips; feature flags — 26 flags,
      phx_dm_pce_feature_flag (27 vertices), durable FlagStore, OFF = not
      rendered AND queries do not run (require_feature 409 before any query),
      reason-required history, presets, guardrail Always On; check_flags 8/8.
- [x] Task 8 (main thread, 959295a + this doc): npm build passes; ALL 24
      checks OBSERVED in headless chromium against the live servers — actual
      output in docs/ROUND_A2B_COMPLETE.md. FOUND+FIXED by observation:
      rec/nrec view names 400'd the chart/table clients; NarrativeText signed
      "(3.99%)" and "lost $54,977" wrongly; 9X modal ignored Escape. The
      21-run insight batch ($1.52) populated exceptions (20 rows) and advisor
      runs; verify a/b/c/e/h/a1 re-run green + check_exports 43/43.
Note: subagents reported, the MAIN THREAD re-verified by execution then
      committed each task (subagents never ran git or touched this file).
      Session LLM cost ≈ $1.52 of the $12 ceiling.

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
- [x] Task 3 (Subagent A, verified in main thread, 2c661a0): catalog 33→38
      (product_month_metrics, product_transition_table with filtered-total
      share_pct and distinct-account totals, month_aum,
      advisor_count_by_product, account_lifecycle_counts from rule outcomes —
      consecutive months only, net_flows null-with-note at group scope) + 5
      GSQL files; /api/dashboard/table+chart+definitions (definitions imported
      from glossary); RETAINED_ACCOUNT sixth v0 rule (TECH_TEAM_WRITTEN, INFO,
      order 35, excludes NEW/NEW_BILLING/TIN) — partition proven (202605:
      new 8 / lost 10 / retained 177 / tin 0 / tout 0; baseline retained 0
      with honest notes). Pins widened per precedent (C6-1 38, B3-13/17 six
      rules exact-provenance, H-8 msg); rule_store.db reseeded to 6 rules.
- [x] Tasks 4+5 (Subagent B, verified in main thread, 304f256+664ef19): 9X
      codes via DETERMINISTIC POST-PASS on the committed data (own seeded RNG,
      no builtin hash(); all 1,948 credited rows byte-identical vs git HEAD —
      ZERO pin changes; 9E 95 / 9H 77 / 9G 44 / 9D 26 rows; wired into
      generation for future regens, refuses double application; ingest 46/46);
      non_credited_by_cause + four per-cause detail queries with the exact
      documented shapes (eligibility grouped by PRODUCT; household threshold
      constants in app/shared/reason_codes.py; from_advisor_departed DERIVED);
      /api/noncredited/summary + /detail/{cause}; product_advisor_ranking +
      /api/dashboard/product/{group_id}/ranking — dominant_driver_code
      deterministic from rule outcomes (RETAINED excluded as a stock measure),
      null never guessed (V000009 +$7,043 → null, demonstrated).
- [x] Task 6 (Subagent C, verified in main thread, 3fe0ccf + repoint bfce6cc):
      POST /api/export — provider registry + 4 renderers (pdf/pptx/xlsx/csv),
      navy-header PDF with definitions footnote, raw-value XLSX (percent as
      fraction + format), PPTX 18-row cap with honest "showing N of M",
      traceability footer (source/timestamp/rule-set version) on every file;
      43/43 check_exports with independent read-back proof. /mnt/skills does
      not exist here (DECISIONS.md); dashboard provider repointed at
      product_transition_table by the main thread (the designed swap).
- [x] Task 7 (main thread): NEW scripts/verify_round_a1.py — 17/17 PASS with
      actual output in docs/ROUND_A1_COMPLETE.md; verify a/b/c/e/h re-run
      green (25/25, 19/19, 13/13, 8/8, 9/9) + check_exports 43/43; servers up
      on :8002 (healthy, 6-rule RSV_v0, 9X live) / :3002 (200); public port
      visibility still needs the Ports panel (gh token lacks codespace scope).
Note: per Round E/G/H precedent, subagents reported and the MAIN THREAD
      re-verified by execution then committed each task (subagents never ran
      git or touched this file). Session app-LLM cost $0.00 — the whole round
      is deterministic.

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
Round: 3 (docs/spec/ROUND_3_SPEC.md) — COMPLETE. The last build round: the
      behaviour changes (shape queries over every row, evidence without a
      cap, the exceptions rate model over the Round-1 fields, cross-cutting
      AI Insights, jobs API) and all 73 review items from both batches are
      in, verified by scripts/verify_round_3.py (10/10) plus a full
      headless-chromium pass over every screen
      (docs/ROUND_3_COMPLETE.md). The schema stayed frozen at 31V/44E —
      no migration was needed.
POST-ROUND RERUN (2026-08-17, operator-funded then operator-stopped): the
      advisor="all" batch was relaunched after the credit top-up and stopped
      at 10 of 21 runs ("enough testing"): 0 failures, 0 limits on ALL 10
      runs, 67 findings, $2.15 — the COST-WEIGHTED token ceiling is now
      LIVE-PROVEN (aggregate run: natural completion, 24 queries,
      limits_hit []; every pre-fix run was cut at ~16 of 35 turns).
      Open items carried out of the round:
      (1) 10 advisors (V000002/6/9/10/11/12/16/17/18/19/20) still serve
      their prior COMPLETE runs — one advisor="all" batch rerun supersedes
      them whenever wanted; nothing else is pending on it;
      (2) port visibility for 8002/3002 still needs the Ports panel
      (gh token lacks the codespace scope);
      (3) subagent-noted polish: an AdvisorLink cell-renderer hook on the
      shared EvidenceTable, group-level pagination inside Revenue Driver
      groups, glossary keys for the CRM column tooltips (ColHead falls back
      to labelize), and lib/api.ts exporting its base URL for the newer
      per-domain API clients.
Round 3 session app-LLM spend ≈ $1.25 of the $15 ceiling (trace-measured).

Previous position — Round: 1 (docs/spec/ROUND_1_SCHEMA_FREEZE_SPEC.md) — COMPLETE. THE SCHEMA IS
      FROZEN at 31 vertices / 44 edges: a client environment installs fresh
      (01→02→03) or migrates from F2 (migrations/001_exceptions_and_jobs.gsql,
      additive-only, one GLOBAL SCHEMA_CHANGE JOB) and verify_schema_parity.py
      proves the two paths identical. Rounds 2 (behaviour: exception
      evaluation over the eight new rule fields, aggregate-first queries,
      evidence without cap, AI-Insights-cross-cutting) and 3 (UI: both review
      batches, Documents & Rules redesign, job progress) need NO further
      migration — checked against REVIEW_COMMENTS_BATCH1/2 item by item
      (ROUND_1_COMPLETE.md "Deviations / notes"). The one deliberately-open
      schema item stays job_code on the advisor vertex, blocked on the
      operator running discovery_job_code.sql — if confirmed, it is one
      additive migration file, no reinstall. Client-load deliverables ready:
      CLIENT_ENV_RUNBOOK.md (Phase 4 = hard review gate),
      COPILOT_SIZING_AND_RATE.md, extract_chunked.py (checkpointed,
      token-expiry-safe), validate_raw_extracts.py (three source kinds),
      build_real_data.py source detection over data/real/_raw.
Round 1 session LLM spend ≈ $0.08 of the $6 ceiling.

Previous round: F2 (docs/spec/ROUND_F2_CRM_NNM_SPEC.md) — COMPLETE. All 7 tasks done;
      docs/ROUND_F2_COMPLETE.md carries the actual output of all 19 checks.
      The round's principle held: the client's grid rate table, discount
      sharing table and NNM award rates live ONLY in documents — the new
      cwm_pca_plan_2026.pdf renders from a non-Python content file, the
      extractor found all three tables with page citations, and the $4MM
      threshold reaches the UI exclusively via extraction → compile →
      publish (RSV_v8) → read-time resolution. The CRM opportunity vertex now
      matches the real Salesforce extract (invalid advisor refs reported
      never hidden; no Won/Lost invented; ai_read is labelled interpretation
      that drives no figure); the four NNM category files load with
      latest-month-YTD semantics, never annualised.
Round F2 standing client questions (stated, not guessed): (1) does a job-code
      column exist on fpic_employee_tb/fpic_prm_rr_tb (discovery_job_code.sql
      ready; plan applicability per advisor is blocked on it); (2) confirm
      amount=forecast vs actual_assets=landed (discovery_crm_amount.sql
      ready); (3) confirm EC is the measured NNM threshold category (ASSUMED
      chip until then); (4) is Won/Lost outcome tracked anywhere structured;
      (5) tiered band schedules (grid rates, award rates) are inexpressible
      in the plan grammar — extracted faithfully, honest NEEDS_DATA at
      compile (same class as the ratio-of-aggregates gap).
Round F2 carried observations: (1) synthetic-run turn logs (crm_ai_read|*,
      doc_extract|*, coach) remain process-local — durable evidence is the
      run-time capture; (2) NNM_AWARD_THRESHOLD compiled against category
      TOTAL / month 2026-12 per the document text — matches 0 rows on data
      ending 202606 (fires when December data exists); the endpoint's
      EC-measured position carries the ASSUMED chip.

Previous round: E chat (docs/spec/ROUND_E_CHAT_SPEC.md) — COMPLETE. All 8 tasks done;
      docs/ROUND_E_CHAT_COMPLETE.md carries the verbatim exchange of every
      check. The two-layer guardrail design (tool boundary is the protection,
      classifier stays lenient — DO NOT TIGHTEN, see DECISIONS.md warning) is
      live: the V2 story-wrapped injection is blocked while its legitimate
      half is answered, and plain questions get zero refusal friction. Chat
      runs on claude-opus-4-6 (CHAT_MODEL); classifier on Haiku; all other
      roles unchanged. Durable chat store (data/runtime/chat.db + graph mirror,
      29V/40E schema) survives restarts with full-context resumption proven.
      Servers: uvicorn :8002 / next :3002 on this round's code; public
      visibility still needs the Ports panel (carried limitation).
Round E chat carried observations: (1) multi-query answers run 43–66s (Opus
      latency × fan-out) — a snappier model or capped-table instruction is a
      polish candidate if the demo needs it; (2) "toggle the feature flag"
      blocks at Layer 1 as JAILBREAK 0.85 — defensible but arguably the
      agent's no-such-tool refusal reads better; threshold/prompt tweak
      candidate; (3) consent messages ("yes, go ahead") can classify OFF_TOPIC
      at low confidence — harmless under leniency, worth a classifier example
      if the trace log tidiness matters.

Previous round: C docs/rules (docs/spec/ROUND_C_DOCS_RULES_SPEC.md) — COMPLETE. All 8
      tasks done; docs/ROUND_C_COMPLETE.md has the observed output of every
      check, incl. the verbatim conflict-auditor proposal (check 11) and the
      first-ever document-cited dashboard bullet (check 20). verify
      a/b/c/e/h/a1 green (25/25, 19/19, 13/13, 8/8, 9/9, 17/17),
      check_manual_rules 17/17, check_flags 8/8, npm build passes (8 routes).
      Served store: RSV_v0…v7 demo trail (deactivate/promote/demote/scope/
      publish), 22 stored insight runs regenerated on RSV_v7, NEEDS_DATA
      drafts incl. the deliberately-unpublished 125 bps conflict draft.
Round C carried observations: (1) reporter_sources/coach classify every
      non-GUIDANCE document category as PLAN search material — PLAYBOOK/
      TRAINING/OTHER now count as PLAN retrieval sources (never extraction
      inputs); needs an operator ruling; (2) the never-fired card lists the
      guidance-only rule as "never evaluated" — true by design, but a
      "guidance only" note there is a polish candidate; (3) recompile is
      draft-pool only (immutability); (4) the conflict auditor needs a
      compiled population — extract → compile → audit is the flow.
A2B closed observation: check 20 closed A2B's carried observation #1 (a
      dashboard bullet now carries a real document citation).

Previous round: A2B — COMPLETE (all 24 checks in docs/ROUND_A2B_COMPLETE.md).
Remaining A2B carried observations: (2) the
      NarrativeText direction heuristics (paren-pct inheritance, decline
      verbs) are pragmatic — if the Reporter ever emits structured spans,
      prefer those; (3) 21 stored insight runs + coaching survive restarts
      (proven twice); coach turn-log rows are process-local like doc_extract;
      (4) exceptions data currently has no CRITICAL rows (severity seed maps
      LOST_ACCOUNT→HIGH, RETAINED→INFO) — the filter is proven on High.

Previous round: A1 — COMPLETE (all 17 checks in docs/ROUND_A1_COMPLETE.md).
Round A1 carried observations: (1) the ranking's dominant-driver nulls are
      common on this small data (many advisors have no qualifying rule impact
      in a group) — expected, the UI copy handles it; (2) exports cap PPTX at
      18 rows/slide by design; (3) verify_round_a1 A1-3 mints RSV_v1 in its
      isolated tempdir only — the served store stays at RSV_v0.

Previous round: H (docs/ROUND_H_SPEC.md) — COMPLETE. All 6 tasks done; tasks 2/3/4
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
Cost: running LLM total ≈ $9.5 project-wide. Round C docs/rules session ≈ $3.30 (trace-measured)
      of its $10 ceiling (Subagent B compiles $0.17 + live seed/manual/retry
      compiles ≈ $0.23 + two small .txt extractions & conflict audit ≈ $0.35 +
      one advisor run $0.10 + 21-run RSV_v7 insight batch ≈ $2.5). Previous
      A2B session ≈ $1.52.
Last updated: 2026-08-14 (Round C docs/rules completion session, after Task 8)
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
