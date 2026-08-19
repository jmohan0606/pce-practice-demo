# Decisions

Append-only. Every decision the spec did not cover.

## 2026-08-11 · Round A · Ingestion support models live inside app/ingestion
Context: V2's ingestion pipeline depends on app/models/ingestion.py and app/feature_store/sqlite_manager.py, neither of which is in the port list.
Decision: Port them as app/ingestion/models.py and app/ingestion/sqlite_manager.py so the ingestion package is self-contained; checkpoint SQLite lives at data/checkpoints/ingestion.db (gitignored).
Reason: The port list says "app/ingestion/*"; the pipeline cannot run without these, and pulling in V2's whole models/ and feature_store/ trees would drag V1/V2 domain code along.
Reversible: yes

## 2026-08-11 · Round A · LLM role config keys are the four PCE agents
Context: V2's app/llm/roles.py resolves per-role config for writer/judge/assistant/guardrail — V2 domain roles the build plan says not to port.
Decision: Keep the resolution machinery but define ROLES = (rule_extractor, rule_conflict_auditor, insights_miner, insights_reporter) with env keys RULE_EXTRACTOR_MODE/MODEL/DEPLOYMENT/API_VERSION/TEMPERATURE etc.
Reason: BUILD_PLAN §2 ports roles.py for "per-role config resolution"; the roles that exist in this system are the four agents in §3.4.
Reversible: yes

## 2026-08-11 · Round A · LLM_MODE=cdao normalises to the cdao_openai adapter
Context: BUILD_PLAN's .env uses LLM_MODE=cdao / EMBEDDING_MODE=cdao; V2's adapters key on the mode string "cdao_openai".
Decision: "cdao" is accepted as an alias of "cdao_openai" in both the LLM and embedding client selectors.
Reason: Keeps the .env exactly as specified while reusing the verified V2 adapter code unchanged.
Reversible: yes

## 2026-08-11 · Round A · V1 TigerGraphDocumentLinker not ported
Context: V1's knowledge_management_service writes document links through V1 graph vertices; the PCE schema has its own phx_dm_pce_document / _document_chunk vertices (app-written, Round B).
Decision: Drop the linker in the Round A port; Round B's upload endpoint writes the PCE document vertices directly.
Reason: The V1 vertex names must not survive, and the Round B spec (§5.8) defines the replacement explicitly.
Reversible: yes

## 2026-08-11 · Round A · Account-key normalisation lives in app/shared/ids.py
Context: BUILD_PLAN §4 constraint: ltrim(trim(x),'0') in ONE shared function used everywhere; spec doesn't say where.
Decision: normalize_account_key() in app/shared/ids.py; the mock data generator, ingestion and any query code import it from there.
Reason: app/shared is the only package everything already depends on.
Reversible: yes

## 2026-08-11 · Round A · Commit 6a7dd75's message overstates its content
Context: The prior commit is titled "Round A: foundation, ported graph/ingestion/llm, GSQL DDL, mock data" but its diff contains only the three spec docs; app/, data/, scripts/ were empty.
Decision: Treat Round A as starting from task 1; do not trust the commit message.
Reason: Verified via git show --stat.
Reversible: n/a (observation)

## 2026-08-11 · Round B · Account-key normalisation is manifest-derived in the ingestion path
Context: normalize_account_key existed but only the mock generator used it; real CSVs will arrive with padded/zero-prefixed keys.
Decision: The entity registry derives normalize_columns per entity from the manifest — vertex columns named acct_key/acct_src_key, plus edge endpoint columns whose from_type/to_type is phx_dm_pce_account — and IngestionService normalises those values on every record before primary key, validation, delta hash and graph write. acct_src_raw is deliberately excluded (raw source value preserved for audit).
Reason: One derivation rule instead of a hand-kept column list; normalisation before hashing means already-clean data re-ingests as SKIP (verified: 0 churn on mock data) while padded keys land normalised (verified via dry run).
Reversible: yes

## 2026-08-11 · Round B · Transition txn_count is the to-month's count
Context: B1.1's transitions example shows one txn_count per transition without saying which month it belongs to.
Decision: txn_count = the destination (to) month's transaction count.
Reason: The mockup's May→Jun card shows ~10,880, consistent with partial June — i.e. the to-month.
Reversible: yes

## 2026-08-11 · Round B · change_pct is null when from_amt is 0
Context: Spec keeps zero-in-one-month rows (a real signal) but a percent change from zero is undefined.
Decision: change_pct: null in the API; the UI renders "—". direction is "up" for change ≥ 0. With class=RECURRING|NON_RECURRING the total and share_pct are of the filtered scope so shares still sum to 100.
Reversible: yes

## 2026-08-11 · Round B · Rule persistence: internal store + graph mirror
Context: The graph schema's phx_dm_pce_rule vertex lacks fields the B3.1 rule object needs (driver_tag, citations, unclear_notes, evaluation_order).
Decision: app/rules/store.py RuleStore holds full rule dicts and mirrors the schema-catalogued subset to phx_dm_pce_rule / phx_dm_pce_rule_set_version via the tiered graph client on every write.
Reason: Keeps the graph honest to its schema while losing nothing from the richer rule object; same upsert path persists on a live TigerGraph.
Reversible: yes

## 2026-08-11 · Round B · LOST_ACCOUNT seeded literally as specced
Context: B3.7's LOST_ACCOUNT compute sum(credited_amt) / trigger value > 0 matches 0 accounts on the mock data even in 202605/202606 (zero-balance prior-present rows have credited_amt 0 in the current month).
Decision: Seed the rule exactly per the B3.7 table rather than reinterpreting compute as prior-month revenue.
Reason: The spec says "write these exactly"; reinterpretation is an operator edit, which the immutable-edit flow exists for.
Reversible: yes (edit mints a new rule row in a new version)

## 2026-08-11 · Round B · verify_round_a 8b widened to >= 16 vertex types
Context: The B3 v0 seed writes phx_dm_pce_rule + phx_dm_pce_rule_set_version at startup, so health now honestly reports 18 vertex-type counts and Round A's "== 16" check failed.
Decision: 8b now requires >= 16; the 16 foundation types must all still be counted.
Reason: Later rounds legitimately add app-written vertex types; suppressing them from health would be dishonest.
Reversible: yes

## 2026-08-11 · Round C task 0 · LOST_ACCOUNT reads prior-month revenue (supersedes the "seeded literally" decision)
Context: Independent review confirmed the B3.7 LOST_ACCOUNT rule can never fire: its population is exactly the rows whose current-month credited_amt is 0, and its compute sums that same field, so `value > 0` is unreachable. A spec error, not an implementation error.
Decision: `phx_dm_pce_account_month` gains `prior_end_balance` / `prior_credited_amt` (DDL V11, loading job, mock generator, schema_catalog, SCHEMA_SPEC), and the v0 LOST_ACCOUNT compute becomes `sum(prior_credited_amt)`. Verified: 10 matches on 202605 mock data; 202604 still returns empty-with-reason (baseline guard).
Reason: A lost account is "zero now, had revenue last month" — a same-vertex rule needs the prior month carried onto the row to see that.
Reversible: yes

## 2026-08-11 · Round C task 0 · Rule parameters validate before the population is fetched
Context: Review found parameter validation was order-dependent: a missing `:advisor_sid` raised only when the scoped month had rows (202604 has 13 transfers) and passed silently as matched=0 when it did not (202605/202606) — a confident wrong answer the Insights Miner would read as "no transfers".
Decision: `evaluate_plan` validates every parameter declared in the compiled plan BEFORE fetching rows; the compiler now also collects params referenced in the attribute expression. verify_round_b B3-18/B3-19 pin both fixes.
Reversible: yes

## 2026-08-11 · Round C task 1 · Local embeddings are a Codespace-only substitute
Context: Anthropic has no embedding API and the cdao gateway exists only in the client environment, so real-embedding work on this Codespace needs a third path.
Decision: EMBEDDING_MODE=local with sentence-transformers/all-MiniLM-L6-v2 at EMBEDDING_DIM=384 on the Codespace ONLY. The client environment uses cdao `text-embedding-3-large-1` at its own dimension — ROUND_D preflight D0.2 must OBSERVE that dimension from a live embed rather than assume 3072, and the Chroma collection must be rebuilt on any dim change (vectors of different dims never mix).
Reason: There is no EMBEDDING_MODE=mock (the Round B note claiming so was wrong — corrected in PROGRESS.md); local is the only real-vector mode available here.
Reversible: yes (env-only)

## 2026-08-11 · Round C · generate advisor="all" runs the aggregate book plus every cohort advisor
Context: C4 defines advisor:"V…"|"all" with a per-advisor batch, but the AI Insights screen needs a whole-book narrative, and every catalog query already accepts advisor="all" as an aggregate scope.
Decision: advisor="all" expands to the pseudo-advisor "all" (one aggregate-book run, addressable as /api/insights/all/{from}/{to}) followed by one run per cohort advisor — run_count = cohort_size + 1. The Insights screen generates/reads the aggregate runs; the Advisor screen generates/reads single-advisor runs.
Reversible: yes

## 2026-08-11 · Round C · Reporter's allowed-number set includes the transition totals
Context: C3 requires every numeric token to appear in the findings, but the mockup narrative leads with the transition's total change — which is a stored query result on the run (advisor_totals), not a finding.
Decision: verify_numbers() allows findings figures (impact_amt, evidence cells, counts) PLUS the transition totals passed to the reporter; date phrasing (month names/years/month ids) is excluded from extraction. Anything else trips the template fallback.
Reversible: yes

## 2026-08-11 · Cost-fix session task 1 · Turn log has no CSV loading job; verify_round_a counts widened
Context: SESSION_PROMPT_COST_AND_UI_FIXES task 1 says "Add DDL, loading job entry, schema_catalog" for phx_dm_pce_agent_turn_log — but app-written vertices have no CSV loading jobs anywhere in this repo; they are written at runtime through the store's mirror entries (file "runtime:<vertex>").
Decision: The turn log follows the same pattern as phx_dm_pce_agent_query_log: DDL + schema_catalog + graph membership + runtime mirror entry in InsightStore; no docs/tigergraph/loading/*.gsql file. verify_round_a checks 2a/2b/2e widened to >= (precedent: check 8b in Round B) since the schema legitimately grew to 25 vertices / 37 edges.
Reversible: yes

## 2026-08-11 · Cost-fix session task 1 · Extractor/auditor turns log under synthetic run ids
Context: Turn rows need a run_id, but document extraction and conflict audits have no insight run.
Decision: doc_extract|<document_id> and conflict_audit|<document_id|adhoc> as synthetic run ids in the same turn log; no phx_dm_pce_turn_in_run edge instance exists for those rows. The Trace summary aggregates them as "document extraction" cost.
Reversible: yes

## 2026-08-11 · Cost-fix session task 6 · Two extra cache anchors in the miner's messages array
Context: The spec's two static cache_control blocks (system + opening) never cached on Haiku — its minimum cacheable prefix is 4096 tokens and system+opening measured ~3.4k, so the first live run showed 0 cache reads AND 0 cache writes (silent, per Anthropic's documented behavior).
Decision: _build_messages sets two additional ephemeral breakpoints (4 total, the API maximum): the newest COLLAPSED transcript entry (stable forever once collapsed — readable next turn even after the pruning window slides) and the newest assistant turn (full-prefix read on turns with no new collapse). Measured effect on the verification run: 28.7% cache hit rate vs 0%.
Reversible: yes

## 2026-08-11 · Round E task 1 · document_chunks rehydrates full text from Chroma, never the summary
Context: Task 1.5's first extraction run produced 12 "the chunk is truncated" NEEDS_INPUT rules. Diagnosis: every chunk served to the extractor was exactly 180 chars — `document_chunks` fell back to the catalog's `chunk_summary` (`text[:180]`) because the graph mock store is process-local, so after a process restart a deduped document has no graph chunk vertices while the SQLite catalog + Chroma persist on disk.
Decision: `document_chunks` now sources text graph-first, then Chroma's stored documents (`KnowledgeVectorStore.document_chunk_texts`), and RAISES if both are empty — a truncated summary is never served as document content.
Reason: Chroma persists the full chunk text on disk and survives restarts; silently degrading to a summary produced confidently wrong extraction results (the worst failure mode this project guards against).
Reversible: yes

## 2026-08-11 · Round E task 1 · verify_round_b B3-11/B3-12/B3-16/B3-17 updated for the grammar removal
Context: ROUND_E_SPEC task 1 deletes the expression grammar; B3-11 pinned grammar parse errors, B3-16/17 exercised the approve→publish flow that now requires COMPILED status.
Decision: B3-11 now pins the data-protecting plan validation (unknown vertex / disallowed aggregate / out-of-set parameter all rejected); B3-12 probes an unknown field through translate_plan; B3-16 compares plans instead of trigger_expr; B3-17 marks the draft COMPILED deterministically (validate_plan, no LLM) before approving.
Reason: The five Round E checks are the replacement contract for what the grammar used to guarantee; the verify script pins the contract, not the deleted implementation.
Reversible: yes

## 2026-08-11 · Round E task 1 · Grammar removal verdict: compiled 10→15, and the honest-gap lists are the real product
Context: The spec ordered "stop and report" if compiled was not materially above 10. First run compiled exactly 10 — but that run was invalidated by the truncated-chunk bug above. With full chunks: extracted 32, COMPILED 15 (+50%), NEEDS_INPUT 4 (each a genuinely unstated value, incl. the deliberate referral-cap trap), NEEDS_DATA 13 (each naming the exact missing field/table/anti-join).
Decision: Proceed with the round. Recorded learning: the grammar was ONE constraint (field-to-field and string-ordering rules now compile); the equally large constraint is schema expressiveness — NOT EXISTS/anti-join, prior-month references, lookup tables and decision-date fields dominate the NEEDS_DATA list and belong in the Round D client-schema conversation.
Reversible: n/a (observation)

## 2026-08-11 · Round E task 2 · PROVISIONAL — the Miner receives pre-evaluated rule outcomes and hunts the residual
Context: ROUND_E_SPEC task 2. **The operator is not fully convinced of this design and wants it revisited once the output is visible — treat as provisional, not settled.**
Decision: Before the agent loop, every PUBLISHED rule evaluates in code (no LLM) for the advisor+transition; fired rules become pre-matched findings (origin="rule", rule_key + first citation + matched rows as evidence, source_query=rules_evaluate_plan); the residual (change_amt − rule impacts) is stated in the opening message with the instruction that the residual is the interesting part. Rule evaluation spends none of the 12-query budget; the reserve for free exploration is recorded per run (exploration_reserved, warned if < 6). Runs report rule_findings / agent_findings / residual_amt / residual_explained_pct.
Sub-decision: a rule finding's impact_amt is the sum of matched values ONLY when its plan computes sum() over a *_amt field — counts and rates never pollute the residual arithmetic. For advisor="all" runs, advisor-scoped rules (:advisor_sid) report "not evaluated" honestly instead of a fake aggregate.
Reversible: yes (and expected to be revisited)

## 2026-08-11 · Round B · section_path is the full heading trail joined with " > "
Context: B2's spec example shows a leaf ("3.2 Discount Sharing"); nested sections need ancestry for provenance.
Decision: section_path renders the dotted heading trail joined with " > " (e.g. "3 Adjustments > 3.2 Discount Sharing").
Reversible: yes

## 2026-08-12 · Round E task 4 · advisor_nnm_position DROPPED (operator override of the spec)
Context: ROUND_E_SPEC task 4 lists `advisor_nnm_position` (cumulative net flows in scope, months covered, never annualised). The operator overrode the spec before the task started.
Decision: The query is not built, and every NNM reference is removed from the recommendations/reporter path (including the "Net-new-money" wording on flows_for_advisor's description; NNM-based recommendations are dropped in code by the reporter's verification gate). The spec's Task 5 "allowed" example that quotes an NNM figure is treated as illustrative of the traceability rule only, not as an NNM requirement.
Reason: We hold only three months of net flows and the plan measures NNM annually; reporting NNM, even labelled with its limitation, presents a proxy as a fact. AUM and net flows ship; NNM waits for real data.
Reversible: yes (build it when a full measurement year of flows exists)

## 2026-08-12 · Round E task 5 · The Reporter's document search is INJECTED, not imported; recommendations gated in code
Context: Task 5 needs the Reporter to fetch thresholds/guidance with citations, but the Reporter is findings-only BY CONSTRUCTION (module imports json/logging/re/typing only; verify_round_c C6-9 scans its imports).
Decision: The import surface stays untouched. `app/insights/reporter_sources.py::build_reporter_search(run_id)` builds a `search_documents(query, source, top_k)` callable (PLAN -> thresholds/rules/qualifications, GUIDANCE -> recommended practice; filtered on the document vertex's document_type; every call logged to agent_query_log as insights_reporter) and the service injects it into `report()`. The reporter may search up to 4 times (excerpts labelled D1..Dn), then emits optional recommendations. `verify_recommendations()` is the in-code gate: a recommendation is DROPPED (never emitted, drop logged) unless it carries a source_query naming a query that produced a finding OR >=1 citation resolving to a fetched excerpt; its numbers must all appear in the findings/transition/cited excerpts; NNM-based text is dropped outright per the task-4 decision. An `assert` over the kept list backs the gate. Recommendations persist as recommendations_json on the run and serialize on the run API.
Reason: Injection keeps the by-construction guarantee auditable (the module still cannot reach a graph client) while giving the model retrieval-with-citations instead of recall.
Reversible: yes

## 2026-08-12 · Round E task 4 · verify_round_c C6-1 catalog count 24 -> 28
Context: C6-1 pinned `len(CATALOG) == 24`; task 4 adds four position queries (advisor_aum, advisor_flows_summary, cohort_ranking, advisor_opportunities — NOT advisor_nnm_position, dropped above).
Decision: C6-1 now pins 28 with sample params for the four new queries (precedent: 8b and 2a/2b/2e widenings). advisor_aum returns prior_balance/change_amt as null for the baseline month rather than 0 or an estimate.
Reversible: yes

## 2026-08-12 · Round E task 3 · Cache anchors are static-only — SUPERSEDES the 2026-08-11 "two extra cache anchors" decision
Context: The 2026-08-11 decision added two cache_control anchors on the newest collapsed entry and the newest assistant turn to clear Haiku's 4096-token minimum cacheable prefix. Measured result: both anchors move every turn, so the prefix changed and invalidated — 5 of 13 turns missed the cache entirely, writes 29,114 vs reads 19,348, net saving 13%.
Decision: Both moving anchors removed. Exactly two anchors remain — the system block and the opening block, byte-identical every turn. The opening now clears the 4096 minimum on its own by carrying the full query catalog (typed params + return columns) and a schema digest (measured 3,384 → 7,656 tokens). STATIC_PREFIX_MIN_TOKENS=4096 guard warns at run start; cache_health() asserts reads > writes after turn 3 (verify_round_c C6-13; scripts/check_cache_health.py asserts from real response.usage).
Reason: A cache anchor must sit on content that never moves. Measured after the fix: one write on turn 1 then pure reads, zero misses; hit rate 28.7% → 72.1%; cost per advisor $0.0689 → $0.0364.
Reversible: yes

## 2026-08-12 · Round G task 2 · Round E's provisional rules-first design STANDS, with the truncation and attention fixes
Context: Round E task 2 (miner receives pre-evaluated rule outcomes, hunts the residual) was recorded PROVISIONAL pending evidence. Round G's instrumented diagnosis (docs/ROUND_G_DIAGNOSIS.md) found the 0-agent-findings failure was NOT the design: the MAX_RUN_INPUT_TOKENS=60000 ceiling silently truncated every run at ~7 turns with no wrap-up, and the residual instruction trailed the opening while the per-turn reminder never mentioned it. The numeric gate, separately, was RIGHT — it rejected fabricated account figures, not a correct narrative.
Decision: The design stands. Fixes: (1) the token ceiling now grants WRAPUP_TURNS=3 query-free turns to emit already-formed findings or an explicit unanswerable statement; (2) a run may not end silent — done with zero discovered findings and no unanswerable gets one nudge; (3) the residual LEADS the opening and rides the per-turn reminder together with the already-recorded rule findings ("do NOT re-emit"); (4) the Reporter gets ONE repair round naming gate-rejected figures before the template fallback (the gate itself unchanged). Measured on V000002 202604→202605: agent findings 0 → 1 (a genuine non-rule discovery), residual explained 0% → 73.5%, fallback_used → False, plus an explicit residual explanation in unanswerable. The PROVISIONAL flag is lifted.
Reversible: yes

## 2026-08-12 · Round F task 3 · 145 bps is the standard managed fee schedule; 115 bps is worked-example-only — RESOLVED
Context: The sample PDF's worked example used "a standard schedule rate of 115 bps", and the (now removed) FEE_REDUCTION_SHARING seed's worked example carried the same figure, leaving 145 vs 115 ambiguous. Copilot's transcription of the four real plan documents (docs/spec/PLAN_EXPECTATIONS_FINDINGS.md) resolves it: 145 bps appears three times as *the schedule* (FAQ p.13, PCA p.3, SAG p.4); 115 bps appears exactly once, inside a worked example (FAQ p.15). Both are correct — they are different things.
Decision: Wherever the sample PDF or any seeded text implies a standard rate, it is 145 bps (the sample PDF's §3.1 now states "the standard managed fee schedule is 145 bps"; the mock data generator already used std_bps=145.0). 115 bps may appear ONLY inside an illustrative worked example clearly labelled as such (sample PDF §3.2 "Worked Example (Illustrative Only)", mirroring FAQ p.15).
Reversible: yes (regenerate the PDF)

## 2026-08-12 · Round H task 1 · Stale durable rule store cleared for the corrected seed
Context: Task 1 moves the transfer exclusion from an implicit `transferred_keys` accumulation in `evaluate_rule_set` onto `LOST_ACCOUNT`'s explicit `exclude_matched_of`. The Round G durable store (`data/runtime/rule_store.db`, gitignored) held the pre-fix seed WITHOUT that declaration, and `ensure_v0_seed` is a no-op when any version exists — so the running system would have kept a LOST_ACCOUNT that no longer excludes transfers at all.
Decision: The gitignored `data/runtime/*.db` files were moved aside (session scratchpad backup) so the corrected seed re-runs at startup. Round G's stored drill-down runs go with them; Round H task 6 generates fresh ones. In a client environment with real history this would instead be an operator edit→publish minting a new version — acceptable here because the dbs are regenerable dev artifacts and no real data is involved.
Reversible: yes (backup retained for this session)

## 2026-08-12 · Round H task 1 · Verify H-2 proves the exclusion by injected probe
Context: All 13 mock transfers sit in 202604, the baseline month where LOST_ACCOUNT cannot fire, so on stock mock data the transfer exclusion never binds and a naive check would pass vacuously.
Decision: verify_round_h H-2 injects a synthetic 202605 transfer row for an account LOST_ACCOUNT actually matches, then asserts TRANSFERRED_IN claims it AND LOST_ACCOUNT's count drops by exactly one (10→9), removing the probe row afterwards.
Reversible: yes

## 2026-08-12 · Round H task 2 · limits_json rides the persisted run dict; no graph schema change
Context: 2.3 requires limit_hit/limit_name/limit_value/limit_effect "on the run record, in the API response, and in the UI". Adding them to the graph mirror would be a 7-place schema change for observability fields.
Decision: `limits_json` lives on the in-process run dict and the durable SQLite run_json (like scope/scope_key, the documented Round G precedent); the API serializes limit_hit (bool) + limits_hit (list) on insight responses and trace rows. The graph mirror's attribute set is unchanged. The ingestion batch cap, which has no run record, encodes the four fields in its loud abort error string.
Reversible: yes

## 2026-08-12 · Round H task 2 · Turn cap records a limit even when the model finishes inside the wrap-up window
Context: The turn cap enters query-free wrap-up at (max_turns − wrapup_turns) so the run is never cut mid-thought. A model that would have finished naturally at turn 34/35 still passes through that window.
Decision: Entering the wrap-up window records the MINER_MAX_TURNS limit — because the cap DID bind (queries were forbidden from that point), even if the model then finished. Over-reporting a bound is acceptable; under-reporting is the failure mode this round exists to kill.
Reversible: yes

## 2026-08-12 · Round H (operator, mid-session) · Task 5 scale test DEFERRED; subagent C not dispatched
Context: Session budget ran low. Operator instruction: finish Task 2, dispatch only subagents A and B, skip Task 5 entirely, run Task 6 with the checks that apply and mark check 11 deferred.
Decision: Task 5 (--scale generator, scale run, limit measurements) is untouched and moves to the next session; PROGRESS.md carries an explicit "nothing of 5.1–5.3 exists" note. The 2.2 resized defaults therefore remain sized-but-unmeasured. The ingestion batch-call cap keeps its 500 default until the scale run measures it.
Reversible: yes (run the task next session)

## 2026-08-12 · Round H task 5 · Scale data is transient; canonical data/ restored after measurement
Context: 5.2 needs the pipeline run at client volume (--scale 28: 57,657 txns / 3,066 accounts / 490 households), but every verify pin (13 transfers, NEW_BILLING 17, transition deltas) is against the committed small data set.
Decision: The scale CSVs were generated in place, measured, and then data/ + docs/data/ restored from git; the gitignored data/runtime run stores were cleared with them so no scale-sized stored run (e.g. an 84-match NEW_BILLING) survives into the small-data servers. The scale run's full measurements live in docs/ROUND_H_COMPLETE.md — the numbers outlive the data that produced them.
Reversible: yes (rerun scripts/generate_mock_data.py --scale 28)

## 2026-08-14 · Round A1 task 1 · Driver rename is a registry write, not a rule edit; prose keeps old names
Context: Spec 1.2 — renaming a driver must change every historical finding's displayed name with no regeneration; spec 2.1 — a severity change mints a new version. The two are deliberately different.
Decision: The display label lives in a durable driver-label registry keyed by the STABLE driver_code (RuleStore.set_driver_label, SQLite table driver_label); resolution happens at read time in ONE place (app/rules/drivers.resolve_driver_label). A rename does NOT mint a rule-set version — identity (driver_code) never changes, and versioning the label would pin historical findings to the old name, defeating the feature. Findings store driver_code only (phx_dm_pce_finding.driver_tag renamed driver_code — DDL/schema_catalog/SCHEMA_SPEC); the API's driver_tag field is now derived, never stored; legacy persisted findings migrate via slug at rehydration.
Known limit (spec-acknowledged): a driver name embedded in narrative PROSE is frozen text — prose written before a rename keeps the old word. The UI must render bullet-lead driver names from driver_code (served per finding), not from prose. Recorded for Round A2.
Reversible: yes

## 2026-08-14 · Round A1 task 2 · Severity edits keep the compiled plan; PATCH publishes in one call
Context: Spec 2.1 — a severity change mints a new rule-set version like any other edit. But edit() invalidates the compiled plan on ANY edit (Round H carried observation #4), which would force a recompile+approve for a triage-level change.
Decision: edit() special-cases DISPLAY-ONLY changes (severity, severity_reason, driver_label, driver_definition, driver_tag, rule_name): the compiled plan/scopes/plan_by_scope carry to the new draft, which lands COMPILED and can be approved+published immediately. PATCH /api/rules/{key}/severity does edit→approve→publish in one call; note publish() also publishes any OTHER already-approved drafts sitting in the pool (documented publish behaviour, not a severity special case). A draft-pool rule with no version just gets its fields updated — there is no version to mint. The stale data/runtime/rule_store.db was cleared (Round H task 1 precedent) so the severity+driver seed reapplies; identical R_*_RSV_v0 keys re-mint.
Reversible: yes

## 2026-08-14 · Round A1 task 6 · Export skills unavailable; format-honesty choices
Context: The spec orders reading /mnt/skills/public/{pdf,pptx,xlsx}/SKILL.md before writing export code; that path does not exist in this environment (verified).
Decision: Renderers follow library best practice (reportlab / python-pptx / xlsxwriter) and every generated file is proven non-blank by independent read-back (pypdf text extraction, python-pptx cell reads, raw-XML numeric-cell parse) in scripts/check_exports.py. XLSX stores percentages as FRACTIONS with a percent number format (raw values pivot correctly; PDF/PPTX/CSV show percent-points — one representation per medium, same payload value). PPTX caps at 18 body rows per slide with an explicit "showing first N of M — use XLSX/CSV" note rather than silent truncation. The dashboard_table provider read Round B's product-contribution query at build time and was repointed at Task 3's product_transition_table by the main thread (the designed one-function swap in app/export/providers.py).
Reversible: yes

## 2026-08-14 · Round A1 task 3 · Verify pins widened for legitimate growth; table/lifecycle semantics
Context: Task 3 grows the catalog 33→38 and the v0 seed 5→6 (RETAINED_ACCOUNT, provenance TECH_TEAM_WRITTEN — the operator-dictated five stay OPERATOR_SPECIFIED). Widening precedents: C6-1 24→28, 8b, B3-17.
Decision: C6-1 re-pinned at 38 with sample params; B3-13/B3-17 re-pinned exactly at 6 with per-rule provenance; H-8 message cosmetic. data/runtime/rule_store.db cleared and reseeded (Round H precedent — regenerable dev artifact). Semantics fixed by measurement: share_pct in a filtered view is of the view's own class total (sums 100.01–100.02 at 2-dp rounding, inside ±0.1); the transition table's total row sums revenue/trades but counts DISTINCT accounts across the view (an account in two groups counts once in the total, once per row — matches the mockup); account_lifecycle_counts is consecutive-months only (the lifecycle rules read each row's own stored prior month), the baseline is queryable as (202604,202604) surfacing empty-with-reason in notes, and net_flows is NULL with a note at group scope because phx_dm_pce_advisor_flow_month is advisor-attributed — allocating flows to a product group would be invented.
Reversible: yes

## 2026-08-14 · Round A1 task 4 · 9X codes arrive by deterministic post-pass, never regeneration
Context: The generator's builtin-hash() nondeterminism (Round H finding) means regenerating data/ breaks every data-derived pin. Task 4 needs 9H/9G/9D/9E in the data.
Decision: apply_noncredited_postpass() in generate_mock_data.py — its own random.Random(99), stable sort keys, no builtin hash(), never consumes the module RNG stream. It relabels legacy ADJ/INELG rows (9H when household assets < minimum, else 9E) and appends 9H/9G/9D rows; the --retag-noncredited mode applied it to the COMMITTED CSVs (all 1,948 credited rows byte-identical — verified against git HEAD; only reason-coded rows changed/appended, plus the derived monthly_revenue/account_month.txn_count/edge/manifest updates appends force). Wired into normal generation too (volumes ride the scale factor); refuses double application. All five verify suites green with ZERO pin changes.
Modelling: HOUSEHOLD_MIN_ASSETS=$800,000 with a $10k threshold window live in app/shared/reason_codes.py (one place, imported by generator AND queries); household assets = summed member-account end balances for the queried month ("within $10k" = 0 in May, 1 in June — honest, not inflated). from_advisor_departed is DERIVED (source advisor has no credited revenue in the month) — the schema stores no departure flag and deriving beats fabricating a measured-looking field. Grid points expected = one per 1% of effective reduction above the 10% threshold; recorded = the transaction's grid_reduction. Appends create monthly_revenue rows with credited 0 / non-credited > 0 — "accounts" metrics must keep meaning credited-revenue accounts (they do).
Reversible: yes

## 2026-08-14 · Round A1 task 5 · Dominant driver competition excludes stock-measures; null is never guessed
Context: Task 5's dominant_driver_code must come from rule evaluation outcomes deterministically.
Decision: dominant driver = the rule driver with the largest absolute monetary impact (same _monetary_impact semantics as the residual arithmetic) over matched accounts restricted to the advisor's accounts in the product group. RETAINED_ACCOUNT is excluded from the competition (NON_CHANGE_DRIVERS): it measures a stock, not a change contribution, and would otherwise dominate every advisor. An advisor with no qualifying rule outcome gets null — the UI says "AI Insights not generated yet"; a driver is never guessed (demonstrated: V000009, +$7,043 change, dominant null).
Reversible: yes

## 2026-08-12 · Round H task 5 · FOUND: the mock generator was never cross-process deterministic
Context: 5.1's S=1 byte-identity check exposed that build_transactions selects each advisor's product subset with builtin hash(), which is salted per process (PYTHONHASHSEED). Regenerating on ANY machine produces different transaction subsets than the committed CSVs — the "seed 42 deterministic" claim only ever covered the random module. Pre-existing since Round A; the committed data/ CSVs are canonical and verify pins depend on them.
Decision: NOT fixed this round — replacing hash() with a stable hash would change every data-derived pin mid-round. Recorded here so nobody regenerates data/ expecting a no-op diff. Scale measurements were run under PYTHONHASHSEED=0 so they are reproducible. Fix candidate for a future round: zlib.crc32, then re-commit data/ and re-pin.
Reversible: n/a (documentation)

## 2026-08-14 · Round A2B task 6 · NNM ships labelled; the four categories are absent from the feed
Context: The A2B spec (superseding Round E's advisor_nnm_position drop) orders NNM shown both ways on the advisor page with the four categories (NB/YI/EC/FS) "available", and the $4MM qualification marked ASSUMED. Verified in phx_dm_pce_advisor_flow_month: comp_group_type carries only 'NNM' and flow products only BRKF/MGDF — the four categories do not exist in the data.
Decision: The metrics strip shows "NNM YTD (from Apr 2026 — first loaded month)" (cumulative net flows across loaded months, coverage named — never annualised or presented as a full-year figure) and "NNM in scope (<From>→<To>)", plus the Managed/Brokerage split that IS in the feed, with the explicit note "NB / YI / EC / FS categories are not present in the current data feed". The $4MM qualification statement carries an ASSUMED chip. verify_round_e E-7 re-pinned to allowlist exactly these sanctioned surfaces; the reporter's NNM-recommendation block stays.
Reversible: yes (render the categories when the feed carries them)

## 2026-08-14 · Round A2B task 7 · Flag toggles apply immediately; mockup reconciled
Context: MOCKUP_FEATURE_FLAGS.html shows a staged "Save Changes" bar. The built page applies each toggle immediately via PATCH (each write is one durable, history-recorded, reason-gated operation; a staged batch would need partial-failure semantics for no user benefit at this scale).
Decision: Toggles apply on change; the savebar shows live counts and "changes apply immediately and persist". The mockup file is updated to match the built app per the spec's divergence rule. Also: spec's "Practice Dashboard (7)" enumerates 8 sections — reconciled at 8 (the per-cause 9X detail is its own child flag); final count 26 of ceiling 30. Cost hints read /api/trace averages; chat's "~$0.02 per message" is the one static string, labelled "estimate, feature not built".
Reversible: yes

## 2026-08-14 · Round C (docs/rules) task 1 · applies_to and scopes are different axes
Context: Round G's `scopes` declares which evaluation scopes a rule CAN run at (derived from its plan's parameters — a plan needing :advisor_sid cannot run at practice scope without a variant). Spec 1.1 adds `applies_to`/`applies_to_key`.
Decision: They are orthogonal and both filter evaluation, in this order: (1) `active` (task 2), (2) `applies_to` — SHOULD this rule apply to the entity being evaluated (PRACTICE = firm-level runs only; ADVISOR[+sid] = that advisor's runs; PRODUCT[+group] = that product group's drill-downs; ALL = everywhere, the default), (3) `scopes` — CAN the rule's plan execute at this evaluation scope. A rule can be ADVISOR-applied yet practice-evaluable: applies_to=ADVISOR limits it to advisor runs even though its plan could run firm-wide. Each filter produces `skipped` with its own reason, never an error. `evaluate_rule_set` gained an optional `group_id` (drill-down passes its product group) so PRODUCT-applied rules can match. An `applies_to`/`applies_to_key` edit preserves the compiled plan (the query itself is unchanged — Round A1 display-only precedent) and so publishes without a recompile.
Reversible: yes

## 2026-08-14 · Round C (docs/rules) task 1.2 · Rule provenance is a four-tag closed set; v0 renamed TECH_TEAM_WRITTEN
Context: Spec 1.2 replaces the binary provenance with DOCUMENT_DERIVED / TECH TEAM WRITTEN / MANUALLY WRITTEN-PRACTICE / MANUALLY WRITTEN-TECH and renames the v0 seed's tag.
Decision: Codes are stored as identifiers (TECH_TEAM_WRITTEN, MANUALLY_WRITTEN_PRACTICE, …) with the spec's chip text as display labels in `RULE_PROVENANCE_TAGS` (app/rules/store.py); the API serializes both `provenance` and `provenance_label`. ALL SIX v0 rules (including the five ex-OPERATOR_SPECIFIED) are TECH_TEAM_WRITTEN — the spec's definition ("logic we supplied because no document states it") covers them all; rehydrated stores migrate in place at construction, no reseed. Glossary gains the four rule-provenance definitions alongside the finding chips (REAL/DERIVED/DUMMY), same `provenance.*` namespace, distinct keys. verify_round_b B3-13 re-pinned.
Reversible: yes

## 2026-08-14 · Round C (docs/rules) task 1.3 · 145 bps pinned as a code constant with citations
Context: The Round F DECISIONS entry resolved 145-vs-115 for documents, but no code constant existed — generator scripts carried bare `145.0` literals.
Decision: `app/shared/fee_schedule.py` exports STANDARD_MANAGED_FEE_BPS = 145.0 with its three schedule citations (FAQ p.13, PCA p.3, SAG p.4); generate_mock_data.py and make_test_raw_extracts.py import it. NO constant is exported for 115 by design — it exists only inside labelled worked-example prose (sample PDF §3.2, make_test_pdf), per FAQ p.15.
Reversible: yes

## 2026-08-14 · Round C (docs/rules) task 2 · Deactivation is a plan-preserving version-minting edit; deletion is store-enforced and all-or-nothing
Context: Spec 2.1/2.2 — active independent of status, deactivating mints a version with who/when/why; approved rules can never be deleted, enforced in the store.
Decision: `RuleStore.set_active` does edit→approve→publish in one call (severity-PATCH precedent) with `active`/`active_reason`/`active_changed_by`/`active_changed_at` on the new rule row; the reason is required for BOTH directions (reactivation equally changes what the next generation produces). The compiled plan is preserved (active is in the display-only/plan-preserving set). An inactive rule feeds NOTHING into a new run: `evaluate_rule_set` skips it with "rule is inactive — <reason>" AND the miner's rule-context list filters it; it stays queryable in its version and prior insights citing it stay valid. `delete_rules` is all-or-nothing — the whole selection is validated before anything is removed, so a mixed selection deletes nothing; approved = has version_id OR approved flag OR status PUBLISHED/SUPERSEDED. Deletion removes the durable SQLite row and issues a graph delete_vertices (best-effort, logged).
Reversible: yes

## 2026-08-14 · Round C (docs/rules) task 3 · Six categories are the same document_type axis; extraction gated at the one extraction route
Context: Spec 3.1 — six categories, only PLAN and FAQ feed the Rule Extractor; category editable after upload.
Decision (Subagent A, verified in main thread): categories live on the existing `document_type` field (legacy V1 enum values kept parseable, case-insensitive `_missing_`); `EXTRACTING_CATEGORIES=(PLAN, FAQ)` in app/knowledge/models.py, enforced at POST /{id}/extract-rules (grep-confirmed the only extraction trigger) with an honest per-category refusal; unknown category = 400 naming the valid set everywhere (upload's previous 422 included — no pin existed on it). PATCH /api/documents/{id}/category updates the SQLite catalog (authoritative) and mirrors the graph vertex best-effort; `extraction_offered=true` iff the new category is PLAN or FAQ. Chroma chunk metadata untouched — its `document_category` is the legacy V1 field; all type filtering reads `list_documents()`.
Reversible: yes

## 2026-08-14 · Round C (docs/rules) task 3.2 · .txt headings are single-line colon- or title-cased; .csv is one table chunk
Decision (Subagent A): .txt — blank-line blocks are paragraphs; a line ending ':' or in title case (minor words may stay lowercase; sentence-punctuated or 80+-char lines never headings) is a heading; page_no=1; section_path from the nearest heading via the existing chunker trail. .csv — the whole file renders via table_to_markdown into ONE has_table=true chunk (the chunker's never-split-a-table rule). Proven by upload: the 145→125 sample chunks with section_path "Fee Schedule Change 2026".
Reversible: yes

## 2026-08-14 · Round C (docs/rules) task 4 · Approved rules are selectable so a mixed selection is honestly disabled
Decision (Subagent A): RuleListManager shows checkboxes on published rows too — that is the only way a mixed selection can exist, and Delete Selected then disables with a note naming the store rule, mirroring the store's all-or-nothing refusal rather than hiding it. Filter option sets derive from the data, never hardcoded lists.
Reversible: yes

## 2026-08-14 · Round C (docs/rules) task 5.2 · NL rules approve without a compile; the two kinds never blur
Decision (Subagent B, verified in main thread): the compile gate protects computed figures; a `natural_language_only` rule has no plan BY DESIGN, so approve() takes that one documented exception (gate fully intact otherwise), publish() carries it plan-less, and the evaluator skips it with "guidance only — no plan by design…" (skip order: active → NL → applies_to → scopes). PUBLISHED+active NL rules ride the miner opening as a labelled MANUAL GUIDANCE block, separate from the computed-rule list, with an explicit never-cite-as-computed instruction. Promote/demote are version-minting with required reason and promoted/demoted who/when recorded (set_active pattern; draft-pool rules update fields).
Reversible: yes

## 2026-08-14 · Round C (docs/rules) task 5.3 · Seed example compile outcomes are the honest ones; no grammar invented
Decision (Subagent B): the three MANUALLY_WRITTEN_TECH examples seed as draft-pool DRAFTs (statements only, idempotent by rule_code, no LLM at seed time). Real Sonnet compiles: BILLABLE_DAYS → COMPILED with an honestly simplified plan (opened_in_scope ∧ not present_prior_month; no day_of_month() — the grammar has none and none was invented); QUARTERLY_BILLING_CYCLE → COMPILED; FEE_SCHEDULE_VARIANCE → NEEDS_DATA naming the exact gap (no ratio-of-aggregates in the plan grammar — sum/sum book-wide average is inexpressible). A ratio_of_sums grammar extension was considered and deliberately not built this round; the named gap is the client conversation.
Reversible: yes

## 2026-08-14 · Round C (docs/rules) task 6 · Compile attempts are append-only; the plan is whatever was picked
Decision (Subagent B): every compile (first included) records a compile_attempt (COMPILED|NEEDS_DATA|FAILED, never overwritten); a retry on an already-compiled draft leaves the current plan untouched until the user picks; pick re-validates the attempt's plan through all five checks (execution included) and resets approval; recompile refuses version-bound rules (400 — edit to mint a draft first). Retries turn-log under rule_compile|<key> so they appear in the cost trace.
Reversible: yes

## 2026-08-14 · Round C (docs/rules) task 7 · Version diff is client-side, code-matched, meaningful-fields-only; edit everywhere, active-toggle current-version-only
Decision (Subagent C, verified in main thread): comparison computes from two GET /api/rules?version= responses, rules matched by rule_code (rule_key is per-mint churn); compared fields = statement, rule_name, worked_example, severity(+reason), applies_to(+key), active(+reason), driver_label, driver_definition, plan (deep, key-order-insensitive), provenance, scopes, evaluation_order, exclude_matched_of; bookkeeping deliberately ignored. Editing is offered on EVERY version's rules (v0 and superseded included — store.edit clones any row; this closes the client's "cannot see/edit v0" complaint) and mints the next version; deactivate/reactivate targets only the current version's row, since active governs the next generation and minting from a stale row would resurrect superseded content. The edit dialog's statement-change recompile is a real choice — unticked leaves an uncompiled draft in the pool and publishes nothing, stated in the UI.
Reversible: yes

## 2026-08-14 · Round E chat task 1 · The tool boundary is the protection; the classifier is allowed to be lenient — DO NOT "TIGHTEN" LAYER 1
Context: V2's guardrail failed in both directions at once: a story-wrapped injection PASSED (the classifier saw a story) and ordinary questions were REFUSED (when a classifier cannot tell, refusing is its safe answer). The cause was asking "is this input bad?" — a question with no reliable answer — and then giving the agent full access once it passed.
Decision: Two layers doing DIFFERENT jobs. Layer 2 (app/chat/tools.py, built FIRST) is the real protection: the chat agent has exactly four capabilities — run_catalog_query (the 38 named queries, params validated before execution), search_documents, get_stored_insight, and generate_insights (the ONE state-changing action). No free SQL, no settings read, no tool returning prompts or configuration; approve/publish/rename/toggle are unreachable because NO SUCH METHOD EXISTS on the tools object. Layer 1 (app/chat/guardrail.py) classifies and TAGS every message, blocks only at high confidence (CHAT_GUARDRAIL_BLOCK_CONFIDENCE, default 0.8), and lets ambiguity through — an injection that slips past detection still only reaches the same catalogued queries the user is entitled to run anyway. A blocked instruction inside a mixed message does not block the legitimate half.
WARNING TO FUTURE SESSIONS: the temptation will be to "tighten" Layer 1 (lower the block threshold, block on ambiguity, refuse off-topic). That reintroduces exactly the V2 false-refusal failure this design exists to fix. If a new attack class worries you, close it at the TOOL layer, never by making the classifier stricter.
Also: the chat agent runs on Opus (CHAT_MODEL=claude-opus-4-6, probed live) — the one place a subtle reasoning failure is expensive; the guardrail classifier runs on Haiku (a fast tagging pass). All other roles keep their current models.
Reversible: yes (but read the warning first)

## 2026-08-14 · Round E chat task 4 · Chat persistence is global; chat vertices have no CSV loading job
Context (Subagent A, verified in main thread): spec Task 4 orders global persistence and the two chat vertices.
Decision: Every user sees every conversation — a deliberate demo simplification; per-user scoping comes later. phx_dm_pce_conversation / phx_dm_pce_chat_message (+ phx_dm_pce_message_in_conversation edge, reverse conversation_has_message) are app-written vertices: the ChatStore's runtime upsert is their loading job, no CSV loading job exists (turn-log precedent). The durable copy lives in data/runtime/chat.db (SQLite write-through, rehydrate-on-construction, PCE_CHAT_DB_PATH overridable); guardrail_json/extra_json are SQLite-only, the graph mirrors the catalogued subset. Delete is three-layer (in-process, SQLite one-transaction, graph best-effort) — proven by probe. Schema now 29 vertices / 40 edges; no verify pins widened (2a/2b already >=).
Reversible: yes

## 2026-08-14 · Round E chat task 6 · Chat UI conventions: lazy conversation creation, scoped CSS, keyed Clear-context
Decision (Subagent B, verified in main thread): conversations are created lazily on first send (the ✚ button only clears the current id) so empty conversations never pile up; all chat CSS is scoped under .chatpanel/.chat-dock with the mockup's --warn/--block tokens mapped to existing --der-*/--sev-crit* tokens (no new root variables); "Clear context" is keyed to the current context identity — it suppresses page_context until the page selection next CHANGES, and the bar label switches to the answered context when an answer event carries one (spec 3.4); the flag's loading state renders nothing (a moment of absence beats a flash of chat UI that the flag then removes). Deep link: any route with ?chat=<conversation_id> opens the panel on that conversation (the guardrail trace's Conversation links use it).
Reversible: yes

## 2026-08-14 · Round E chat task 7 · Guardrail trace: filter narrows rows, never the counts
Decision (Subagent C, verified in main thread): GET /api/trace/guardrail?tag= filters rows server-side but summary/total always cover the FULL log, so the count chips stay stable and honest while a filter is active. The endpoint passes guardrail_log() through unmodified — tools_called is derived in ONE place (the store). Tag colours reuse the existing chip palette (attack tags red; SOCIAL_ENGINEERING amber — deception, not code; CLEAN grey-green; OFF_TOPIC neutral). Chat scopes in the runs table carry kind "chat" ("chat conversation" label).
Reversible: yes

## 2026-08-16 · Round F2 task 1 · Discovery queries AUTHORED, not run — no client data source is reachable here
Context: Task 1 orders two discovery queries (job-code column existence; amount vs actual_assets semantics). Verified this session: no PostgreSQL config or connectivity exists in this Codespace (carried from Round F task 4 — the client's fpicdb was never reachable here), the real CRM extract CSV (45f440b6…, 308,534 rows) is NOT in the repo, and none of the four NNM files are either — only the operator's transcription in docs/spec/CRM_AND_PLAN_FINDINGS.md.
Decision: The discovery queries are committed as hand-authored operator-run artifacts (docs/data/extraction/discovery_job_code.sql, discovery_crm_amount.sql — each states how to read its result), and the round proceeds on recorded working assumptions plus fabricated raw data (the proven Round D/F pattern: build_real_data.py exercised against data/real_test/_raw fabrications; demo servers run on additive mock data).
Reversible: yes (run the queries client-side; the answers slot in)

## 2026-08-16 · Round F2 task 1.1 · job_code NOT added to the advisor vertex until discovery answers
Context: Plan eligibility depends on job code (SAG p.9: HK0176/HK0186/HK0187/HK0188 → CWM Select Advisor), but whether fpic_employee_tb / fpic_prm_rr_tb carry a job-code column has never been observed and cannot be observed from here.
Decision: phx_dm_pce_advisor does NOT gain job_code this round. Adding a column no data source is known to populate would manufacture schema — the failure mode this app exists to avoid. Until the operator runs discovery_job_code.sql, plan applicability stays as-is (applies_to, default ALL) and "which plan applies to which advisor" is a standing client question, stated rather than guessed.
Reversible: yes (one SCHEMA_CHANGE_CHECKLIST pass once the column is confirmed)

## 2026-08-16 · Round F2 task 1.2 · ASSUMPTION — amount is forecast pipeline value; actual_assets is landed assets; never summed
Context: In the transcribed sample, `amount` is 0 in every row while `actual_assets__c` carries 100–5,000,000; the operator reports `amount` spans −1 to 2 billion over the full file. The profile-by-stage query cannot run here (no data source).
Decision: WORKING INTERPRETATION until the client confirms: `amount` = the Salesforce standard opportunity Amount, the forecast pipeline value; `actual_assets__c` = a custom field (the __c suffix marks it) recording the assets that actually landed. The two are NEVER summed — they describe the same opportunity and summing double-counts. The UI carries an assumption note wherever both are shown (Task 6.3); discovery_crm_amount.sql states the observation that would falsify the interpretation (both fields populated on the same rows at scale).
Reversible: yes (env/none — flip the labels when the client answers)

## 2026-08-16 · Round F2 task 1 · Plan tables enter ONLY via document files; the new PCA-style plan renders from a non-Python content source
Context: Check 13 fails the round if a grid rate table, award rate, bps threshold or dollar threshold from the plan documents appears in any Python file — but the existing sample plan PDF is generated by scripts/make_sample_plan_pdf.py with its content hardcoded in Python. Extending that pattern with the PCA grid/discount/NNM tables would hardcode exactly what check 13 forbids.
Decision: The new plan document (PCA-style: grid rate table p.3, discount sharing p.3–4, NNM award rates p.4, definitions) is authored as a non-Python content file under docs/sample/ and rendered to PDF by a generic renderer that carries no plan values; the extractor must find the tables there (check 12). Consequences for check 13's grep, stated up front as the documented exceptions it will surface: (1) app/shared/fee_schedule.py's STANDARD_MANAGED_FEE_BPS=145.0 — spec-sanctioned since Round C task 1.3 (mock-data generation constant with its three schedule citations); (2) make_sample_plan_pdf.py's INVENTED demo payout schedule (A1–D4 bands, 30–48%) — not the client's plan tables. Neither the PCA grid (22–35%), the NNM award rates (50–70 bps), the $4MM threshold, the $500 floor, nor the discount-sharing adjustment may appear in any .py file. The $4MM threshold in the UI/API resolves at read time from the EXTRACTED rule, never from a constant.
Reversible: yes

## 2026-08-16 · Round 1 (schema freeze) task 1 · Exception-default rules mapped to existing rule_codes; exception config is plan-preserving
Context: The spec ships three rules with exception_enabled=true: "fee reduction above threshold, discount sharing not applied, lost accounts". The rule set (RSV_v8) has no rule literally named "discount sharing not applied".
Decision: EXCEPTION_DEFAULT_RULE_CODES = {DISCOUNT_SHARING_THRESHOLD_TRIGGER (fee reduction ≥ threshold — "fee reduction above threshold"), DISCOUNT_SHARING_MINIMUM_GRID_RATE (the closest published discount-sharing compliance rule — stands in for "discount sharing not applied" until a dedicated rule exists), LOST_ACCOUNT}. The default applies by rule_code at store normalization (setdefault — an extractor proposal or human edit is never overwritten), so re-extractions and rehydrated stores get it without a reseed. All eight exception fields join the plan-preserving edit set (they govern how Round 2's exception evaluation reads the rule, never what the compiled query computes) — same class as applies_to/active.
Reversible: yes (edit the set when the dedicated rule exists)

## 2026-08-17 · Round 1b · Committed data updated by additive post-pass, never regeneration
Context: Tasks 1–3 add job_code / the two pay-type columns / the PCS|PBR product+group to the mock data, but the generator was never cross-process deterministic (Round H finding — builtin hash() product subsets), so regenerating data/ breaks every data-derived pin.
Decision: The committed CSVs were edited by deterministic column-append/row-insert post-passes (Round A1 9X precedent): advisor.csv gained job_code via the generator's own mock_job_code(i) rule; product.csv gained the two pay-type columns from PAY_TYPE_CODES (transcribed from PRODUCT_HIERARCHY_FULL.md); product_group/product/product_in_group gained exactly the referrals_private_bank rows. NO transaction, monthly_revenue or account row changed. Consequence: referrals_private_bank has no mock revenue — verify_round_b B1-5 re-pinned to allow exactly that one seeded group absent from the revenue sections. The generator itself emits all three fields for future regens (which remain non-comparable to the committed bytes, as recorded 2026-08-12).
Reversible: yes

## 2026-08-17 · Round 1b · Sub-less PCS still resolves to Situational Partnership
Context: Narrowing PCS to PCS/SP would strand the committed mock data's 59 pre-split `PCS|` transactions (empty sub-code): build_monthly_revenue re-derives group_id from product_id, so they would silently move to unmapped.
Decision: `_SUBCODE_MAP[("PCS","")] = "referrals_sit_partnership"` — an explicit, commented alias. PCS/PBR maps to the new group, and any OTHER unknown PCS sub-code lands in unmapped per the ELIS/LEND rule (strictly narrower than the old wholesale PCS mapping). In the real export PCS rows always carry SP or PBR, so the alias binds only on legacy/degenerate rows.
Reversible: yes

## 2026-08-17 · Round 1b · Migration 002 grew task-by-task; parity script applies migrations/0NN_*.gsql in order
Context: The spec puts migration 002 in task 4, but committing tasks 1–3 with the clean-install DDL ahead of the migration would leave intermediate commits failing verify_schema_parity.
Decision: 002_schema_additions.gsql was created in task 1 (advisor ALTER) and extended in task 2 (product ALTER) so every commit stays parity-green; verify_schema_parity.py now globs migrations/0NN_*.gsql sorted and applies each in sequence (SP-1 data-safety per file, SP-2 per file), asserting baseline_f2 + 001 + 002 == clean install. A deliberately corrupted 002 (l2_pay_type_cd removed) fails SP-4 naming the attribute — probe proven 2026-08-17.
Reversible: yes

## 2026-08-17 · Round 1b · data/real_test fixtures legitimately reshuffled
Context: Adding the two PCS rows to make_test_raw_extracts.HIERARCHY changed every RNG.choice(products) draw, so the fabricated transactions regenerated differently.
Decision: Accepted — the fixtures are regenerable fabrications with no byte-level pins (all checks recompute from the drop: V-1..V-10 pass, sanity anchor $33,130/advisor/month, verify_round_1 12/12). The reshuffle is a feature: the fixture path now exercises PCS/SP and PCS/PBR end-to-end through build_real_data.
Reversible: yes

## 2026-08-17 · Round 2a task 1 · Ingestion batch size 5000 — a MEASURED default, not a guess
Context: The client environment measured ingestion throughput at batch 500 / 1000 / 5000: **3,169 → 5,375 → 7,706 rows/sec** (vertices, p95; edges 25,250 rows/s at 5000), with a 54 ms RESTPP round trip — a 500-row batch spends nearly half its wall time on the network. The old default of 500 would more than double the ~2.9-hour projected load window for no benefit.
Decision: `batch_size: 5000` in both manifest generators AND the committed `data/manifest.json` (scalar post-pass edit, no CSV touched); new `ingestion_batch_size` setting (alias `INGESTION_BATCH_SIZE`, default 5000) — an explicit env override beats the manifest, otherwise the manifest value rules. The spec's named settings key `ingestion_batch_size` did not exist (only an UNUSED `graph_load_batch_size` — left in place, still unused); it exists now and is the one the registry consults. Two consequences applied with it: (1) `_BATCH_OVERRIDES` (1000 for the three high-volume files) deleted — "larger than 500" overrides would now LOWER the batch on exactly the biggest files; (2) `INGESTION_MAX_BATCH_CALLS_PER_ENTITY` default 500 → 10,000 — the largest real entity is 12,436,738 rows = 2,488 legitimate batch calls at 5000; Round H deliberately kept 500 "until the scale run measures it", and this round's measured volumes are that measurement.
Reversible: yes (env-only for the batch size)

## 2026-08-17 · Round 2a task 2 · Extraction scoping: temp tables, five chunk families, flags reduced
Context: The cohort is now the firm (5,746 SIDs; the in-scope account set is ~3M keys) and four "single table" extracts are millions of rows (spec 2.2/2.4, measured).
Decisions:
- **No template inlines a SID or account-key list.** Every session starts with `00_session_setup.sql` (emitted by generate_extraction_sql; run automatically by extract_chunked on EVERY connection): TEMP `cohort_adv` loaded by 500-SID multi-row INSERTs + TEMP `scoped_acct` computed ONCE per session (with the cohort join — identical to the old per-table subqueries, and equal to the spec's date-only form when the cohort is the firm). Transaction CHUNKS still inline their per-chunk advisor batch (≤ --batch-size, default 200) — the spec forbids inlining the 5,746/3M lists, not a 200-SID batch, and a temp-table sub-cohort per chunk would need per-chunk DDL.
- **Chunk families**: balances one chunk per month (`raw_balance_<month>.csv`, never a UNION; the ~2.9M/month size is the spec's own design, so those chunks are exempt from the >2M dry-run warning — month is their finest split and --buckets does not apply); account/eci_rel/eci_map split by `mod(abs(hashtext(s.k)), --buckets)` (default 4) over scoped_acct — deterministic, resumable, checkpointed per bucket exactly like txn chunks.
- **Dry-run projections** come from the committed `docs/data/extraction/EXPECTED_COUNTS.json` (the spec's measured client counts), labelled "projected"; live counts print when a connection exists.
- **raw_advisor_flags reduced** to advisor_sid / rep_code / advisor_name / total_credited_amt: verified nothing in build_real_data consumes any of the nine scenario-flag columns (they were read for the contract and never used; only select_cohort.py consumed them, and the cohort is now the firm — nothing selects anything). No flag survives. select_cohort.py is retired for the firm-wide load (kept for history; it reads old-format files only).
- **raw_adv_flows extends to June** (client-measured: 19,443,868 daily rows Apr–Jun aggregate to 166,985; the earlier "no June rows" finding no longer holds). The GROUP BY aggregate is unchanged — only the date bound moved.
- verify_round_1 R1-8b re-pinned for the 27-chunk plan + 5 session-setup executes (widening precedent).
Reversible: yes

## 2026-08-17 · Round 2a task 2 · build_real_data streams; stage-then-commit replaces validate-then-write
Context: Every builder took list[dict] — ~25 GB for the 12.4M transactions alone; the client machine cannot hold that, and the old "NOTHING is written until every validation passes" was implemented by holding the whole dataset in memory.
Decisions:
- The four large entities STREAM (transactions row-by-row with monthly_revenue accumulating as rows pass; account/eci_rel/eci_map per bucket, with dedupe and latest-bus_dt state confined to one bucket — the hash buckets partition by account key, so cross-bucket state is provably unnecessary); account_month processes ONE MONTH AT A TIME from per-month aggregates spilled to temp files during the transaction pass, holding only the prior month's (pair)→(balance, credited, present) map.
- The never-a-silent-partial-build guarantee is preserved by STAGING: everything streams into `<out>.building/`, validations run from accumulators at the end, and only a fully-validated set moves into --out (which is otherwise untouched; a failure removes the staging directory). Same guarantee, different mechanism — recorded because the old wording said "nothing is written".
- `--max-memory-mb` (default 4096) checks peak RSS after every entity and fails with a named message instead of being OOM-killed; per-entity peaks land in build_report.json. PK-uniqueness for the streamed transaction file uses a 64-bit blake2 hash set (~4e-6 false-positive odds at 12.4M — a false duplicate would BLOCK a build, never pass a bad one).
- PRE-EXISTING BUG FIXED: VERTEX_COLUMNS still carried the pre-F2 opportunity dummy shape (the 23 real CRM columns were silently dropped at write) and omitted phx_dm_pce_advisor_nnm entirely — the built manifest had 17 vertices while 31 edge files (nnm edges included) were written: dangling nnm edges at load, exactly the Task-3 failure mode. Proven by diff: old code vs new code on the same fixture drop differ ONLY in these two fixes; data/real_test outputs recommitted (they were additionally stale from the Round-1b reshuffle).
- CRM (operator requirement, mid-round): the firm-wide flat file (308,534 rows) is FILTERED at build — kept iff the suffix-stripped owner sid is a known advisor OR the eci is a known in-scope household; out-of-scope rows drop WITH A REPORTED COUNT; *_CWM_INVALID references stay kept+reported. Account_month row order is now month-major (was pair-major) — content proven identical order-insensitively; nothing pins CSV order.
- Validation 11's sanity flag now states the expected firm-scale figure (5,746 × ~$33k ≈ $190M/month) so the flag reads as calibration, not failure; it remains print-only, and validate_raw_extracts V-10 (per-advisor anchor) is the scale-independent gate.
Reversible: yes

## 2026-08-17 · Round 2a task 3 · Two-phase parallel load: refusal at the checkpoint layer, stop-flag failure semantics
Context: load_real_data/ingestion_service had zero concurrency (verified); --max-parallel is new code. Edges loaded before vertices dangle silently.
Decisions: the manifest carries `phase` (1 = vertices, 2 = edges) in both generators AND the committed manifests (data/manifest.json post-pass; data/real_test rebuilt); entity_registry derives phase from kind for older manifests. load_real_data.py is now its own orchestrator (load_mock_data.py untouched for the mock path): per-phase ThreadPoolExecutor (--max-parallel default 3), each worker its OWN IngestionService (own SQLite handles; SQLiteManager gains a 30s busy timeout), a failing entity sets a stop flag that halts every sibling at its next batch boundary, and the whole phase fails — phase 2 never starts. `assert_phase_complete` refuses (raises, not warns) unless EVERY phase-1 entity has a COMPLETED checkpoint — checked from the checkpoint layer, so a hand-run edges-only load against a half-loaded vertex set refuses too. The data_load job row keeps one stage per entity (Round 1 pattern).
Reversible: yes

## 2026-08-17 · Round 2a task 4 · Reconciliation proves raw − explained == built == loaded; flat files included
Context: source/extracted/loaded are only comparable when the transform's legitimate deltas (dedupes, out-of-scope drops, superseded snapshots, the CRM in-scope filter) are themselves recorded — otherwise every honest dedupe would read as silent loss.
Decisions: build_real_data writes `build_report.json` (raw rows in / rows out / every named delta per entity, plus per-entity peak RSS); `reconcile_load.py` then proves, per entity: checkpoint source == raw CSV recount (truncation check), raw − explained deltas == built rows, built == manifest == graph count — any unexplained difference is a hard failure naming the entity and both numbers. The CRM export and the four NNM files ride the same table (operator requirement): CRM raw vs in-scope kept with the out-of-scope and *_CWM_INVALID counts shown; NNM parsed rows == advisor_nnm vertex == loaded. The committed baseline (docs/data/extraction/EXPECTED_COUNTS.json) is compared wherever it carries a number; `--no-baseline` exists for fixture drops whose sizes legitimately differ (baseline comparison is ON by default — the client path). monthly_balance reconciles source-vs-extracted only (its grain feeds account_month, not a 1:1 vertex). Proven: fixture load PASSES 49 targets; a doctored report simulating 40k silently-dropped rows FAILS naming revenue_transaction and both numbers.
Reversible: yes

## 2026-08-14 · Round A2B · Per-subtask commits collapsed for parallel-dispatched work
Context: The spec asks for commits after 6.2/6.4/6.7; Subagent C's work arrived complete from the parallel dispatch (Round E tasks 6+7 precedent).
Decision: One verified commit per task (6 and 7). Batch insight generation (advisor="all", 21 runs, $1.52) was run by the main thread during the round so exceptions/insights/advisor views verify against real stored runs.
Reversible: n/a (process note)

## 2026-08-17 · Round 3 (operator, mid-round) · Per-role model defaults are EMPTY — SUPERSEDES the Round A2B/E "deliberately configured" defaults
Context: coach_model / chat_model / chat_guardrail_model shipped with hardcoded Claude model-id defaults ("the non-empty default deliberately makes the role configured"). In the client environment (LLM_MODE=cdao_openai, CDAO_MODEL=gpt-5.5) those three sent a Claude model id to a cdao endpoint even with the variables absent from .env — unfixable by omission.
Decision: all three default to "" like the other roles: an unset role falls through to the primary LLM_MODE and its model; setting the variable still overrides per role. Verified by execution with a clean env (all eight roles resolve cdao_openai/gpt-5.5; an explicit CHAT_MODEL still wins). The remaining model defaults (anthropic_model, azure_*, cdao_model) are mode-scoped adapter defaults that cannot leak across modes. This Codespace's .env pins CHAT_MODEL=claude-opus-4-6 / CHAT_GUARDRAIL_MODEL explicitly, so local behaviour is unchanged; .env.example documents the unset-is-correct rule and warns that a Claude id under cdao_openai fails.
Reversible: yes

## 2026-08-17 · Round 3 task 1.2 · MAX_RUN_INPUT_TOKENS is COST-WEIGHTED — cache reads 0.1×, cache writes 1.25×
Context: With shapes in place the ROWS_SHOWN truncations disappeared, but every RSV_v12 run still tripped the 250k token ceiling at ~16 of 35 turns. Measured composition: the cached opening (~15k tokens of catalog+schema) is re-READ every turn at 10% price — the ceiling was acting as a hidden turn cap on cheap tokens, not a spend guard.
Decision: TurnLoggingLLM gains budget_tokens_total = input + 0.1×cache_read + 1.25×cache_write (the providers' actual billing weights); the miner ceiling enforces against it (falling back to the raw total on wrappers without it — never unmetered). The 250k default is UNCHANGED: it now buys a full 35-turn run whose prefix re-reads are cheap while stopping a runaway loop at the same worst-case dollar spend. The cap's purpose — "a run must never spend without limit" (Round H) — is preserved exactly; only the unit now matches the bill. Proving a full natural-completion run under the weighted ceiling is BLOCKED on API credits (exhausted mid-batch, 13 of 21 runs unfunded) — the weighted arithmetic is unit-proven; the live rerun is the first action once credits exist.
Reversible: yes

## 2026-08-17 · Round 3 post-round · Cost-weighted ceiling LIVE-PROVEN; rerun stopped at 10/21 by operator
Context: The 2026-08-17 cost-weighted-ceiling decision recorded "the live rerun is the first action once credits exist." Credits were topped up; the advisor="all" batch was relaunched (first relaunch failed 21/21 on a not-yet-propagated top-up — cost nothing, displaced nothing per the serve-latest-COMPLETE rule) and then stopped by the operator at 10 of 21 completed runs ("enough testing"; generation halted by backend restart — the durable layer only persists completed runs, so the mid-flight advisor left no orphan).
Result: 10/10 completed runs hit ZERO limits (the aggregate reached natural completion at 24 queries, generation 4, limits_hit []); 0 failures; 67 findings; $2.15 trace-measured (~$0.22/run — full-depth runs cost more than ceiling-cut ones, as expected). The weighted ceiling's live proof is complete. The 10 not-regenerated advisors serve their prior COMPLETE runs; one batch rerun supersedes them whenever wanted.
Reversible: n/a (observation)

## 2026-08-17 · Round 4 task 2 · The numeric gate VERIFIES two-figure arithmetic instead of banning it; stock measures leave the residual
Context: The Round 3 cross-cutting mandate asks the practice narrative for connection statements ("together these added $85,341", "7.2% of the book") while the Round C gate rejected every computed figure — the same transition fell back to the template on four consecutive real-LLM attempts, twice on whole-dollar roundings of allowed figures ($34,166 for 34,165.52) and twice on correct sums of headline impacts. Separately, the reactivated RETAINED_ACCOUNT's $804,787 (a STOCK, not a change contribution) was being summed into the residual, producing a confidently-wrong "-$911K residual" in a served narrative.
Decisions: (1) verify_numbers accepts a whole-dollar rounding of a non-integer allowed figure; (2) it accepts a token that provably equals a sum or difference of TWO headline figures (impact_amts + transition totals only — never evidence cells, whose hundreds of values would accept almost anything) or a percentage of one headline figure over another at 0.1pp — the gate re-computes the arithmetic, so the no-invented-figures guarantee is unchanged and anything unreproducible still falls; the reporter prompt states the new contract. (3) The repair round no longer contradicts it ("do not sum" removed), keeps the cross_cutting system prompt, and logs an unusable rewrite instead of silently standing on the old rejection list. (4) NON_CHANGE_DRIVERS (RETAINED_ACCOUNT) are excluded from the residual arithmetic — the Round A1 dominant-driver precedent applied to the residual; the finding still displays its total. Measured: rejections fell 10 → 0 across regenerations; the served Apr→May narrative is cross-cutting with fallback_used=False and every combined figure reproducible.
Reversible: yes

## 2026-08-18 · Round 5 task 1 · Cohort scripts retired; reference-table joins killed beyond the letter of the spec
Context: The client's 17 Aug definitions retire cohort selection (select_cohort.py + raw_advisor_flags.sql -> scripts/build_cohort.py, chunk plan 109->108) and mandate IN (SELECT ... FROM cohort_adv), never a join, because fpic_prm_rr_tb/fpic_employee_tb carry one row per branch/location.
Decisions beyond the spec's list, all from the same fan-out mechanism:
- raw_advisor.sql now uses DISTINCT ON (r.standard_id) — without it the one-row-per-branch reference table emits one advisor row PER BRANCH and the build would fail validation 2 on duplicate PKs at load. build_real_data additionally collapses duplicate SIDs first-row-wins WITH A REPORTED COUNT (defence in depth; the raw file may be hand-made).
- raw_adv_flows.sql's rep-code->SID join now goes through (SELECT DISTINCT standard_id, prm_rr_no FROM fpic_prm_rr_tb) — the bare join could multiply daily flow rows per branch row before the GROUP BY sums them, silently inflating every flow figure.
- validate_raw_extracts gained V-0: generated transaction SQL (template AND a real chunk) must not join fpic_prm_rr_tb OR fpic_employee_tb — the check guards the GENERATOR so the 4.1M-row join can never silently reappear.
- make_test_raw_extracts.py DECLARES its 20-advisor fixture cohort (the same advisors the retired selector picked); the 6 "loser" candidate rows existed only to exercise selection and are gone. Fixtures legitimately reshuffled (regenerable, no byte pins — Round 1b precedent).
- build_cohort.py refuses to write cohort.txt when the count differs from the client's stated 5,455 (report-and-stop per spec); --allow-count-mismatch is the explicit operator override for after the client confirms a population move.
Reversible: yes

## 2026-08-18 · Round 5 task 2 · proc_dt is the month/scope basis — SUPERSEDES every "never use proc_dt" statement
Context: The client confirmed (17 Aug) their authoritative PCE report is dated by proc_dt (reconciles to 0.36%; trade_dt is 1.7% off and never reconciles). Every earlier spec said "never use proc_dt" — sound reasoning in the abstract (processing runs after month end), wrong for this client. Their definition wins.
Decisions:
- Extraction scope filter AND month_id derive from proc_dt (templates, scoped_acct, month_meta, transform_txn). trade_dt is still extracted and stored — it remains the business date. A row with an unparseable proc_dt cannot be month-attributed and is counted out_of_scope_or_undated, never guessed.
- month_meta's trading_days is now count(DISTINCT proc_dt) — months are PROC months throughout, one basis everywhere.
- Corrected in place: SCHEMA_SPEC §0, ROUND_D_EXTRACTION (rule + diagnostics), COPILOT_EXTRACTION_GUIDE, CLIENT_ENV_RUNBOOK, TRACEABILITY row 6, the three Copilot prompts, and superseded-note annotations on the historical specs (ROUND_F, ROUND_1, ROUND_D_CLIENT_DEPLOYMENT) so no old document silently re-teaches the wrong rule.
- The committed DEMO mock data keeps its stored month_id values (generated trade-dt-based; regenerating data/ breaks every data-derived pin — the 2026-08-12 hash() finding). The mock generator is not regenerated this round; the proc_dt rule governs the real-data path, which is what re-extraction runs. The fixture generator now emits proc dates that roll month-end trades into the next PROC month (in scope), so the fixture path exercises proc-month attribution end to end.
Reversible: yes

## 2026-08-18 · Round 5 task 3 · Two reason filters, two precomputed columns; credited_amt == advisor_credited_amt
Context: The client uses TWO reason-code filters — firm/dashboard (NOT IN 9X,XX; NULL/blank included) and advisor (also excluding 9R,98,99,9H) — and credited_amt is baked into the data at build time, so two stored columns now exist on revenue_transaction AND monthly_revenue (migration 003 touches three vertices; the earlier only-the-advisor-vertex statement is superseded by the spec itself).
Decisions:
- Both filters live ONLY in app/shared/reason_codes.py (FIRM_REASON_FILTER / ADVISOR_REASON_FILTER), used by the real build, the mock generator, the committed-data post-pass and the query layer. Never inlined.
- credited_amt is KEPT and set equal to advisor_credited_amt (spec-directed): advisor-level is what most of the app computes — every rule plan, finding, exception denominator and insight narrative keeps meaning without touching a single stored run. non_credited_amt stays its complement; is_credited = passes the advisor filter.
- THE DEMO-DATA CALL: the registered demo cause codes (9G/9D/9E + legacy ADJ/INELG) do not exist in the client feed — reason_codes.py has said since Round A1 that real extraction maps the client's actual codes into that table. ADVISOR_REASON_FILTER therefore also excludes registry codes: on REAL data both filters are exactly the client's literal sets; on MOCK data the non-credited demo (four causes, inheritance drill-down) keeps its meaning and every committed credited_amt byte is unchanged (the --add-credited-columns post-pass VERIFIES stored credited_amt against the filter and refuses on divergence). 9H sits in both worlds, consistently.
- Column assignment (full 46-query audit in ROUND_5_COMPLETE.md): dashboard totals / product contribution / product_month_metrics / product_transition_table / product_transition_metrics (the product level of the drill-down) read firm_credited_amt over the FIRM scope (cohort + __UNATTRIBUTED__); advisor pages, rankings, peer comparisons, exception rates, drill-downs below product, rule evaluation and all insight generation stay on credited_amt (= advisor). The insights narratives therefore quote advisor-basis totals while the dashboard headline is firm-basis — exactly the firm-vs-advisor gap task 14's tooltip explains.
- The Non-Credited Revenue section stays keyed on the reason-code cause registry (advisor-level non-credited): its causes — inheritance from a departed advisor included (client req §5) — are advisor-crediting stories. A firm-basis non-credited total is derivable as amount − firm_credited_amt and is stated in the audit, not silently substituted.
- Measured on mock after the switch: May firm dashboard total $951,879.85 vs advisor-basis $890,127.59 — the firm > sum-of-advisors property the client described, now visible in the demo.
Reversible: yes

## 2026-08-18 · Round 5 task 4 · Advisor vertex: SEVEN attributes, not six — is_synthetic rides migration 003
Context: Task 4 lists six advisor attributes; task 3's own load block requires is_synthetic=true on the __UNATTRIBUTED__ synthetic advisor. Deriving it from the SID would leave the spec's stated field unimplemented in schema.
Decisions:
- Migration 003 adds SEVEN advisor attributes (the six + is_synthetic BOOL). Additive, parity-proven; the spec's "six" undercounted its own task-3 requirement — recorded here rather than silently diverging.
- The client's job_cd → DisplayName / plan-family mapping lives in app/shared/job_codes.py ONLY (it exists in no source table; the mapping is authoritative over em_pay_title_txt — four codes have blank source titles by design). Unmapped code → the raw code shown, plan family blank; blank stays blank. The 12 codes double as the cohort filter list (build_cohort.py carries them inside the client's verbatim query).
- NULL-advisor extraction: the scope is (advisor IN cohort OR advisor IS NULL) — still never a join; NULL rows ride EXACTLY ONE transaction chunk per month (batch 1 carries the OR IS NULL predicate) so they are never duplicated across batches and the chunk plan stays 108. scoped_acct and month_meta include the NULL-advisor scope for consistency (their accounts/months are firm-relevant).
- build_real_data appends the synthetic advisor row only when the stream actually saw blank-SID rows; the advisor transform delta records it as a NEGATIVE explained delta (a row ADDED), so reconcile_load's raw − explained == built arithmetic stays exact. Fixtures now carry two blank-advisor rows to exercise the path end to end.
- Committed mock advisor CSV extended by --add-advisor-attributes post-pass (column-append; byte-identical existing columns): all mock advisors em_status_cd 'A' / not departed (inventing mock departures would silently change stored-insight semantics), deterministic work state/city, display name + plan from the real mapping (mock's HK0300 renders as the raw code — the unmapped path visible in the demo).
Reversible: yes

## 2026-08-18 · Round 5 task 7 · CRM map is header-built; a missing opportunity id derives from eci + createddate
Context: The real CRM export uses Salesforce column names (eci__c, stagename, createddate, ...). The real file is not in this repo, so the map cannot be transcribed from it here.
Decision: CRM_COLUMN_MAP in build_real_data.py lists, per contracted target, the accepted source spellings (target-named first, then the Salesforce name); resolve_crm_header() builds the actual mapping from the file's OWN header case-insensitively — the spec's table is the candidate list, the header is the authority. Every contracted column must resolve or the build fails naming each miss and the header seen. Two sanctioned absences: opportunity_id (derived deterministically as CRM|<eci__c>|<createddate> — stable across re-runs, collision-visible as a duplicate-PK failure) and days_to_close (defaults 0, noted). Proven against a fabricated Salesforce-headered file (resolution + derived id) and the target-named fixture (no-op mapping).
Reversible: yes

## 2026-08-18 · Round 5 Part C · COMPENSATION_ENGINE is a stored-and-skipped scope, and the skip says why
Context: The client wants a fourth applies-to level available for both rule origins, with no behaviour required of it yet.
Decision: APPLIES_TO gains COMPENSATION_ENGINE (store validation, extractor proposal with lenient coercion to ALL, Write a Rule dropdown, edit dialog, chip, data-derived list filter). The evaluator's applies_to filter SKIPS such rules at every evaluation with the explicit reason "its evaluation target is not yet defined; the rule is stored and displayed but produces no findings" — a scope that exists in the model but silently produced nothing would be exactly the "worse than not adding it" failure the spec warns about, so the absence of behaviour is stated, never implied.
Reversible: yes (define the evaluation target later; the skip branch is one place)

## 2026-08-19 · Round 7 task 1 · The list API's document_category is the category axis, not the legacy V1 column
Context: The operator observed the row dropdown always reading OTHER. Diagnosis: the catalog table carries TWO columns — document_type (the Round C six-category axis, correct) and document_category (a legacy V1 field defaulting "Comp Plan") — and list_documents served the legacy one, which the frontend reads first; "Comp Plan" is not in the six-value set, so the select fell back to OTHER on every document.
Decision: list_documents serves document_category = the stored document_type. The legacy column stays in the catalog (Chroma chunk metadata still carries the V1 field, untouched); nothing else read the legacy value from this API. The upload response now also carries document_category + extraction_offered so the upload flow offers extraction directly — the row dropdown keeps only its reclassification job.
Reversible: yes

## 2026-08-19 · Round 7 tasks 2+4 · Extraction candidates ride the job resume token; ONE ranking call groups duplicates AND orders provisions; top N selected in code
Context: Task 2 (rank, don't truncate) conflicts with the Round 1 persist-per-window resume design — persisting unranked candidates would leave the draft pool holding 153 rules mid-run.
Decisions:
- Candidates are NOT persisted per window any more; they accumulate in the job's resume_token ({next_window, limit, candidates}) so an interruption still loses at most one window and the draft pool only ever holds SELECTED rules. The jobs API summarizes the token (candidate_count) — the full candidate list would ship ~100KB+ per 1.5s progress poll. verify_round_1 R1-4/R1-6 re-pinned (recorded in the script).
- Dedup is two-level: exact restatements collapse in code (normalized statement; the keeper is the instance with the fuller citation and absorbs the duplicates' citations — dedup never loses provenance), then ONE LLM call groups semantic duplicates (same threshold/scope/subject regardless of generated rule_code) and returns the distinct provisions ordered most-significant-first with a stated reason each. The top N are taken IN CODE, so a lower limit selects a prefix of the same ranking. A candidate the ranker never mentions is appended last, never dropped.
- A FAILED ranking call keeps every deduplicated candidate with the failure stated in the funnel — a cap applied by truncation would be worse than no cap (the spec's own words). Unparseable-window stubs bypass ranking entirely (operator-review placeholders, not provisions).
- The funnel (candidates → after_dedup → selected, + duplicates_collapsed and the limit) is recorded on the job (JobStore.update gained an `extra` merge) and returned by the API; runs at different limits are distinguishable by extraction_limit on the job.
Reversible: yes

## 2026-08-19 · Round 7 task 6 · The scope challenge counts advisor_sid only with a concrete value — ":advisor_sid" is evaluation plumbing
Context: The spec lists four advisor attributes (job_code, advisor_plan, em_status_cd, advisor_sid) whose presence in a compiled plan's filters makes the rule advisor-scoped. But a filter {field: advisor_sid, value: ":advisor_sid"} is how nearly every advisor-evaluable plan scopes to "the advisor being evaluated" (all six v0 lifecycle rules included) — it selects no fixed subpopulation.
Decision: detect_scope_contradiction flags job_code / advisor_plan / em_status_cd with ANY value, and advisor_sid only with a literal value; the ":advisor_sid" parameter is excluded as scope plumbing. The challenge is recorded on the rule (original + proposed + fields + reason), NEVER applied — POST /{key}/scope-challenge {accept} is the human confirmation (draft-pool rules only; version-bound rules go through the plan-preserving edit dialog). A clean recompile clears a stale challenge.
Reversible: yes

## 2026-08-19 · Round 7 task 8 · The startup seed call already existed; the fix is unmistakable logging + observed proof
Context: The spec states ensure_v0_seed() "is never called at application startup" — but app/api/main.py has called it at create_app() since Round B (git-verified). The operator's environment nonetheless had no v0 rules, which this repo cannot reproduce: with an empty store the startup seed runs (proven by observation — fresh PCE_RULE_DB_PATH → log "v0 seed: SEEDED RSV_v0 with 6 rules at startup", RSV_v0 with 6 rules on the Rule Versions page). Likeliest client-environment causes: a stale main.py copy (files are moved by hand) or a rule_store.db that already carried a version.
Decision: the startup call now logs BOTH branches explicitly ("SEEDED RSV_v0 with 6 rules" / "no-op — RSV_vN already exists (M rules)"), so the client environment's next start is diagnosable from the startup log alone. No behavioural change to the seed itself.
Reversible: yes

## 2026-08-19 · Round 7 task 9 · Preview is store-free by construction and asserted per call; its LLM cost is turn-logged
Context: Preview must persist nothing while costing a real compile call.
Decision: preview_compile() in app/agents/rule_compiler.py runs the same agent loop (search/repair budgets included) with ZERO store calls, executes the validated plan through rules_evaluate_plan for real matched rows, and the endpoint asserts len(store.rules) unchanged (500 "preview persisted a rule — this is a bug" if not) and serializes persisted:false + rule_count. LLM calls turn-log under rule_preview|<key>; /api/trace/summary gained a rule_compile bucket (rule_compile|* + rule_preview|*) whose measured avg_cost_usd feeds the button's cost hint. Known pre-existing limit: synthetic-run-id turn logs live in process memory only, so the hint has no history after a restart until the next compile.
Reversible: yes

## 2026-08-19 · Round 7 task 10 · Blank filter values get an explicit "(blank …)" bucket; blank-state observation used response interception
Context: "An advisor with no work state or city still appears — a blank stays blank … never a reason to hide them." The mock cohort has one genuinely blank job_code (V000008, the Round 1b pin) but NO blank work_state/work_city.
Decision: each cascade level derives its options from the data and adds a "(blank …)" bucket whenever blanks exist, so blank-value advisors are both visible under "All" and reachable by selection. The blank-job_code path is observed on real data (V000008); the blank-state/city path was observed in the browser by intercepting /api/advisor/list and blanking one advisor's state/city — the UI code path is the thing under test, and the client data is where blanks actually occur. Recorded so nobody mistakes the interception for stored data.
Reversible: yes

## 2026-08-19 · Round 8 (operator, mid-round) · The evaluator read the LOCAL store — fixed via an internal catalog query; the wider debt audited and ratcheted
Context: Client-environment finding — app/rules/evaluator.py read the foundation store directly (all_vertices ×2, vertex ×1), so in real mode every rule evaluated against MOCK rows while the dashboard showed TigerGraph figures; both look plausible and nothing flags it. A follow-up sweep found the problem systemic: 44 direct reads across 11 modules outside app/graph/.
Decisions:
- The evaluator now reads EVERY row through `rule_evaluation_rows` — a new INTERNAL catalog entry (validated by run_catalog_query, served by the tiered client, GSQL twin to be installed client-side). rules_evaluate_plan itself stays Python-interpreted (the recorded decision) — only WHERE the rows come from changed. The query is hidden from catalog_signatures() and refused without allow_internal=True, so no agent tool layer can ever pull raw vertex rows into a prompt (MinerTools/ChatTools untouched — they were already correct).
- Mock-mode identity PROVEN: v0 evaluated over 9 scope×month combinations before and after — outputs byte-identical; runtime counts run_catalog_query=97, direct evaluator store calls=0 (immediate-caller instrumentation), static grep 0.
- The remaining 41 reads are audited per-site in docs/STORE_READ_AUDIT.md (22 covered by existing queries, 7 need additive extensions to three queries, 9 need three small new queries, 3 raw-coverable) — a day of work, not a week; the fixes themselves are a later round per the operator's read-the-report-first instruction.
- scripts/check_store_reads.py is the guard, as a RATCHET: the audited per-module line counts are the baseline, which may only shrink; any new read (or growth) fails naming file+line (probe-proven both directions). With an empty baseline it becomes the strict zero-tolerance test.
- verify_round_c C6-1 re-pinned: 47 catalog entries (46 agent-visible + 1 internal, hidden-and-refused asserted).
Reversible: yes (the audit and ratchet; the evaluator fix should not be reverted)

## 2026-08-19 · Round 8 task 4 · A "month" grain and an absolute-threshold exception branch; the threshold is a plan edit, not exception config
Context: HIGH_9R_MONTH is a firm-level monthly aggregate ("total 9R revenue in a month > $50M"). The plan machinery had no way to group by month, the exceptions engine evaluates per advisor at advisor scope (a PRACTICE rule skips there), and the $50M lives in the plan's trigger — not in the eight exception-config fields.
Decisions:
- GRAINS gains "month" (group_by month_id) — app-level, no schema change; the frozen 31V/44E stands. The rule sums firm_credited_amt (a 9R row passes the FIRM reason filter, so that column carries its full amount) filtered reason_cd='9R'.
- compute_rule_exceptions branches for applies_to=PRACTICE rules into an ABSOLUTE model (model="absolute_threshold"): evaluated ONCE at practice scope; `fired` comes from the real evaluation; the OBSERVED value comes from the same plan with its trigger opened, so the row shows the actual figure even when nothing fired — the operator sees whether the threshold discriminates. No cohort, no rate, advisors=[] — there is one firm, and the spec says an absolute here is correct, not an inconsistency. The firm response also carries published_version + published_rule_count (the three-empties distinction), and the advisor altitude states "firm-level absolute threshold — not evaluated per advisor".
- The threshold edit is a NEW store path `set_trigger_threshold` (PATCH /{key}/trigger-threshold): deterministic re-validation (all five checks, no LLM), formatted-value rewrite of statement/worked_example, then mint+publish in one call (set_active precedent). The Exceptions tab shows the editor for ANY applies_to=PRACTICE rule with a numeric trigger — nothing keys on the rule_code, and 50000000 exists nowhere outside the seed definition (grep in ROUND_8_COMPLETE).
- The LIVE demo store predates the seed change (ensure_v0_seed no-ops), so HIGH_9R_MONTH was added to it as an operator-style approve+publish (RSV_v17, noted in the version's own notes; fresh installs seed it in v0). Verification advanced the store to RSV_v19 (v18 = the threshold-edit proof 50M→60M, v19 = the restore to 50M) — the audit trail is the feature.
- Mock data has NO 9R rows (sums $0.00/month) — reported, threshold NOT adjusted (the operator decides against client data; April alone carried 1,915,772 9R rows there). verify_round_h H-8 re-pinned: the never-fired report now legitimately lists HIGH_9R_MONTH on mock data — that is the report working. B3-13/B3-17/R1-3 re-pinned for the seventh seed rule / fourth exception-enabled default.
Reversible: yes

## 2026-08-19 · Round 8 task 5 · The demo rule is account-grain by the data's own shape; Write a Rule gained the Entity select
Context: The spec's demo rule ("a couple of transactions together produce more than $100,000 for an advisor") asks for an advisor-month total constrained by a transaction count. Rehearsed through the REAL UI: at advisor grain the compiler consistently and CORRECTLY refuses (no advisor-month total vertex; two aggregates + a compound trigger are inexpressible — pasted in DEMO_WRITE_A_RULE.md), while account_month carries credited_amt AND txn_count precomputed per account, so the account-grain phrasing compiles reliably and the exceptions rate model then measures each ADVISOR by their rate of concentrated accounts — the advisor scoping the demo needs, plus the firm row above it (the three-altitude story).
Decisions: the walkthrough (docs/DEMO_WRITE_A_RULE.md) teaches the account-level phrasing, pastes the real Unsupported for the advisor-total phrasing as a stage asset (the compiler refusing to fake a query IS the product), and records the fallback threshold ($2,000 — determined by running it; $100,000 matches nothing on demo data). ManualRuleForm gained an "Entity" (grain) select — the API always accepted grain; the form now exposes it, and the preview passes it through. money(0) folding to an em dash was excluded for the absolute exception row ($0 observed is a real figure).
Reversible: yes
