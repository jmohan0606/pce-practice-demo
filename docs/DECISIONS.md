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

## 2026-08-11 · Round B · section_path is the full heading trail joined with " > "
Context: B2's spec example shows a leaf ("3.2 Discount Sharing"); nested sections need ancestry for provenance.
Decision: section_path renders the dotted heading trail joined with " > " (e.g. "3 Adjustments > 3.2 Discount Sharing").
Reversible: yes
