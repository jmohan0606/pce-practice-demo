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
