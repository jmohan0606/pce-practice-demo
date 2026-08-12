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

## 2026-08-12 · Round H task 5 · FOUND: the mock generator was never cross-process deterministic
Context: 5.1's S=1 byte-identity check exposed that build_transactions selects each advisor's product subset with builtin hash(), which is salted per process (PYTHONHASHSEED). Regenerating on ANY machine produces different transaction subsets than the committed CSVs — the "seed 42 deterministic" claim only ever covered the random module. Pre-existing since Round A; the committed data/ CSVs are canonical and verify pins depend on them.
Decision: NOT fixed this round — replacing hash() with a stable hash would change every data-derived pin mid-round. Recorded here so nobody regenerates data/ expecting a no-op diff. Scale measurements were run under PYTHONHASHSEED=0 so they are reproducible. Fix candidate for a future round: zlib.crc32, then re-commit data/ and re-pin.
Reversible: n/a (documentation)
