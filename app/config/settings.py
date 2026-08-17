from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Every relative data path resolves against the REPO ROOT, never the process
# working directory (V2 Round 5 A7 lesson — a backend launched from a different
# directory read a different data set).
APP_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_PREFIX = "phx_dm_pce_"


def resolve_app_path(path: str | Path) -> Path:
    """Absolute path for a possibly-relative configured path, anchored at APP_ROOT."""
    p = Path(path)
    return p if p.is_absolute() else (APP_ROOT / p)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(APP_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = Field(default="pce-practice-demo — Practice Management Dashboard", alias="APP_NAME")
    app_env: str = Field(default="local", alias="APP_ENV")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- Structured logging (see app/shared/logging.py) ---
    log_sink: str = Field(default="file", alias="LOG_SINK")  # file | stdout | cloudwatch
    log_json: bool = Field(default=True, alias="LOG_JSON")
    log_dir: str = Field(default="logs", alias="LOG_DIR")
    log_file_name: str = Field(default="app.log", alias="LOG_FILE_NAME")
    # Round H 2.5: rotation is TIMED (dated archives — "what happened last
    # Tuesday" is app.log.2026-08-11, not a guess among numbered files), with
    # the size cap kept as a within-day safety net (app.log.2026-08-11.1).
    log_rotate_when: str = Field(default="midnight", alias="LOG_ROTATE_WHEN")
    log_rotate_utc: bool = Field(default=False, alias="LOG_ROTATE_UTC")
    log_rotate_max_bytes: int = Field(default=10_485_760, alias="LOG_ROTATE_MAX_BYTES")
    log_rotate_backup_count: int = Field(default=30, alias="LOG_ROTATE_BACKUP_COUNT")
    log_cloudwatch_group: str = Field(default="/pce/practice-demo", alias="LOG_CLOUDWATCH_GROUP")
    log_cloudwatch_stream: str | None = Field(default=None, alias="LOG_CLOUDWATCH_STREAM")
    aws_region: str | None = Field(default=None, alias="AWS_REGION")

    # --- Graph client (mock | real | auto | tiered | mcp | local_real) ---
    graph_client_mode: str = Field(default="mock", alias="GRAPH_CLIENT_MODE")

    tigergraph_host: str | None = Field(default=None, alias="TIGERGRAPH_HOST")
    tigergraph_username: str | None = Field(default=None, alias="TIGERGRAPH_USER")
    tigergraph_password: str | None = Field(default=None, alias="TIGERGRAPH_PASS")
    tigergraph_secret: str | None = Field(default=None, alias="TIGERGRAPH_SECRET")
    tigergraph_token: str | None = Field(default=None, alias="TIGERGRAPH_TOKEN")
    tigergraph_graph: str = Field(default="phx_dm_pce_practice_demo", alias="TIGERGRAPH_GRAPH")
    tigergraph_schema_prefix: str = Field(default=SCHEMA_PREFIX, alias="TIGERGRAPH_SCHEMA_PREFIX")
    tigergraph_restpp_url: str = Field(default="http://localhost:14240/restpp", alias="TIGERGRAPH_RESTPP_URL")
    tigergraph_verify_ssl: bool = Field(default=True, alias="TIGERGRAPH_VERIFY_SSL")
    tigergraph_timeout_seconds: int = Field(default=120, alias="TIGERGRAPH_TIMEOUT_SECONDS")
    graph_load_batch_size: int = Field(default=500, alias="GRAPH_LOAD_BATCH_SIZE")

    # --- 4-tier GraphClient adapter (MCP → pyTigerGraph → RESTPP → local store) ---
    # TG_* vars use the official tigergraph-mcp naming so the same env drives both
    # the MCP server subprocess (Tier 1) and the direct pyTigerGraph tier (Tier 2).
    tg_host: str = Field(default="http://127.0.0.1", alias="TG_HOST")
    tg_graphname: str | None = Field(default=None, alias="TG_GRAPHNAME")  # None → TIGERGRAPH_GRAPH
    tg_username: str = Field(default="tigergraph", alias="TG_USERNAME")
    tg_password: str = Field(default="tigergraph", alias="TG_PASSWORD")
    tg_api_token: str | None = Field(default=None, alias="TG_API_TOKEN")
    tg_jwt_token: str | None = Field(default=None, alias="TG_JWT_TOKEN")
    tg_secret: str | None = Field(default=None, alias="TG_SECRET")
    tg_token_lifetime_seconds: int = Field(default=0, alias="TG_TOKEN_LIFETIME_SECONDS")
    tg_restpp_port: int = Field(default=9000, alias="TG_RESTPP_PORT")
    tg_gs_port: int = Field(default=14240, alias="TG_GS_PORT")
    tg_ssl_port: int = Field(default=443, alias="TG_SSL_PORT")
    tg_use_ssl: bool = Field(default=False, alias="TG_USE_SSL")
    tg_verify_ssl: bool = Field(default=True, alias="TG_VERIFY_SSL")
    graph_tier_cooldown_seconds: int = Field(default=60, alias="GRAPH_TIER_COOLDOWN_SECONDS")
    graph_tier_probe_timeout_seconds: int = Field(default=10, alias="GRAPH_TIER_PROBE_TIMEOUT_SECONDS")

    # --- Data set (mock CSVs) ---
    # data/manifest.json + data/vertices/*.csv + data/edges/*.csv are the load set.
    data_dir: str = Field(default="data", alias="DATA_DIR")
    # Checkpoint SQLite for the ingestion pipeline (gitignored).
    sqlite_db_path: str = Field(default="./data/checkpoints/ingestion.db", alias="SQLITE_DB_PATH")

    # --- LLM (mock | claude | real | cdao | cdao_openai | azure) ---
    # BUILD_PLAN .env uses LLM_MODE=cdao; "cdao" normalises to the cdao_openai adapter.
    llm_client_mode: str = Field(default="mock", alias="LLM_MODE")
    # cdao GPT-5 rules: blank api_version → OMIT the argument; temperature=1 only;
    # never send max_tokens. Config is the only signal — never inspect the model name.
    cdao_api_version: str = Field(default="", alias="CDAO_API_VERSION")
    cdao_workspace_id: str | None = Field(default=None, alias="CDAO_WORKSPACE_ID")
    cdao_model: str = Field(default="gpt-5", alias="CDAO_MODEL")
    cdao_temperature: float = Field(default=1.0, alias="CDAO_TEMPERATURE")
    # Round H task 3.3: does the configured provider give us prompt caching?
    # Set false when scripts/check_cache_support.py shows the provider caches
    # nothing — the Generate-button cost projection then prices EVERY input
    # token at the full input rate instead of the historical cached mix.
    assume_prompt_caching: bool = Field(default=True, alias="ASSUME_PROMPT_CACHING")

    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-haiku-4-5-20251001", alias="ANTHROPIC_MODEL")
    anthropic_max_tokens: int = Field(default=8192, alias="ANTHROPIC_MAX_TOKENS")

    azure_openai_endpoint: str | None = Field(default=None, alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_api_key: str | None = Field(default=None, alias="AZURE_OPENAI_API_KEY")
    azure_openai_deployment: str = Field(default="gpt-4o-mini", alias="AZURE_OPENAI_DEPLOYMENT")
    azure_openai_embedding_deployment: str = Field(
        default="text-embedding-3-small", alias="AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
    )
    azure_openai_api_version: str = Field(default="2024-06-01", alias="AZURE_OPENAI_API_VERSION")

    # SmartSDK / Fusion (client env alternate; guarded imports)
    azure_auth_method: str = Field(default="key", alias="AZURE_AUTH_METHOD")
    azure_model_name: str = Field(default="gpt-4o-2024-08-06", alias="AZURE_MODEL_NAME")
    azure_deployment_name: str = Field(default="gpt-4o-2024-08-06", alias="AZURE_DEPLOYMENT_NAME")
    azure_api_key: str | None = Field(default=None, alias="AZURE_API_KEY")
    azure_api_version: str = Field(default="2024-02-01", alias="AZURE_API_VERSION")
    azure_endpoint: str | None = Field(default=None, alias="AZURE_ENDPOINT")
    fusion_base_url: str | None = Field(default=None, alias="FUSION_BASE_URL")
    fusion_workspace_id: str | None = Field(default=None, alias="FUSION_WORKSPACE_ID")
    fusion_env: str = Field(default="prod", alias="FUSION_ENV")
    azure_certificate_path: str | None = Field(default=None, alias="AZURE_CERTIFICATE_PATH")
    azure_tenant_id: str | None = Field(default=None, alias="AZURE_TENANT_ID")
    azure_client_id: str | None = Field(default=None, alias="AZURE_CLIENT_ID")
    azure_embedding_model_name: str = Field(default="text-embedding-3-small", alias="AZURE_EMBEDDING_MODEL_NAME")
    azure_embedding_deployment_name: str = Field(
        default="text-embedding-3-small", alias="AZURE_EMBEDDING_DEPLOYMENT_NAME"
    )

    # --- Embeddings (cdao | cdao_openai | local | azure | azure_openai) ---
    embedding_client_mode: str = Field(default="cdao", alias="EMBEDDING_MODE")
    cdao_embedding_model: str = Field(default="text-embedding-3-large-1", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=3072, alias="EMBEDDING_DIM")
    local_embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2", alias="LOCAL_EMBEDDING_MODEL"
    )

    # --- Knowledge chunking (Round B, spec B2.2) ---
    chunk_max_chars: int = Field(default=1800, alias="CHUNK_MAX_CHARS")
    chunk_overlap_chars: int = Field(default=200, alias="CHUNK_OVERLAP_CHARS")

    # --- Per-agent LLM role config (four PCE agents). All optional; empty = the
    # active LLM_MODE's own defaults, per field — see app/llm/roles.py.
    rule_extractor_mode: str = Field(default="", alias="RULE_EXTRACTOR_MODE")
    rule_extractor_model: str = Field(default="", alias="RULE_EXTRACTOR_MODEL")
    rule_extractor_deployment: str = Field(default="", alias="RULE_EXTRACTOR_DEPLOYMENT")
    rule_extractor_api_version: str = Field(default="", alias="RULE_EXTRACTOR_API_VERSION")
    rule_extractor_temperature: float = Field(default=1.0, alias="RULE_EXTRACTOR_TEMPERATURE")
    rule_compiler_mode: str = Field(default="", alias="RULE_COMPILER_MODE")
    rule_compiler_model: str = Field(default="", alias="RULE_COMPILER_MODEL")
    rule_compiler_deployment: str = Field(default="", alias="RULE_COMPILER_DEPLOYMENT")
    rule_compiler_api_version: str = Field(default="", alias="RULE_COMPILER_API_VERSION")
    rule_compiler_temperature: float = Field(default=1.0, alias="RULE_COMPILER_TEMPERATURE")
    rule_conflict_auditor_mode: str = Field(default="", alias="RULE_CONFLICT_AUDITOR_MODE")
    rule_conflict_auditor_model: str = Field(default="", alias="RULE_CONFLICT_AUDITOR_MODEL")
    rule_conflict_auditor_deployment: str = Field(default="", alias="RULE_CONFLICT_AUDITOR_DEPLOYMENT")
    rule_conflict_auditor_api_version: str = Field(default="", alias="RULE_CONFLICT_AUDITOR_API_VERSION")
    rule_conflict_auditor_temperature: float = Field(default=1.0, alias="RULE_CONFLICT_AUDITOR_TEMPERATURE")
    insights_miner_mode: str = Field(default="", alias="INSIGHTS_MINER_MODE")
    insights_miner_model: str = Field(default="", alias="INSIGHTS_MINER_MODEL")
    insights_miner_deployment: str = Field(default="", alias="INSIGHTS_MINER_DEPLOYMENT")
    insights_miner_api_version: str = Field(default="", alias="INSIGHTS_MINER_API_VERSION")
    insights_miner_temperature: float = Field(default=1.0, alias="INSIGHTS_MINER_TEMPERATURE")
    insights_reporter_mode: str = Field(default="", alias="INSIGHTS_REPORTER_MODE")
    insights_reporter_model: str = Field(default="", alias="INSIGHTS_REPORTER_MODEL")
    insights_reporter_deployment: str = Field(default="", alias="INSIGHTS_REPORTER_DEPLOYMENT")
    insights_reporter_api_version: str = Field(default="", alias="INSIGHTS_REPORTER_API_VERSION")
    insights_reporter_temperature: float = Field(default=1.0, alias="INSIGHTS_REPORTER_TEMPERATURE")
    # Round A2B 6.7 — the Coach agent (Haiku by default; its own role config).
    # The non-empty model default deliberately makes the role "configured", so
    # the coach always runs on Haiku unless the operator overrides COACH_*.
    coach_mode: str = Field(default="", alias="COACH_MODE")
    coach_model: str = Field(default="claude-haiku-4-5-20251001", alias="COACH_MODEL")
    coach_deployment: str = Field(default="", alias="COACH_DEPLOYMENT")
    coach_api_version: str = Field(default="", alias="COACH_API_VERSION")
    coach_temperature: float = Field(default=1.0, alias="COACH_TEMPERATURE")

    # --- Agent loop budgets & limits (Round H task 2: EVERY limit lives here
    # with an env alias — no limit is a module constant, no limit binds
    # silently. Defaults sized for real volume (~60k transactions, 20
    # advisors), not the 1,694-transaction mock set the old values were tuned
    # against. Every one is a default, not a ceiling: override per environment.
    miner_query_budget: int = Field(default=25, alias="MINER_QUERY_BUDGET")
    # Hard ceiling on prompt tokens (input + cache read + cache write) one run
    # may consume. When exceeded the run gets wrap-up turns to commit what it
    # has (never a mid-thought cut), the limit is recorded on the run record,
    # and whatever findings exist are emitted. 60k truncated every run on MOCK
    # data (Round G diagnosis) — 250k is sized for the client cohort.
    max_run_input_tokens: int = Field(default=250_000, alias="MAX_RUN_INPUT_TOKENS")
    # Hard stop on miner LLM turns — must exceed the query budget plus findings
    # plus wrap-up so it never binds before the query budget does.
    miner_max_turns: int = Field(default=35, alias="MINER_MAX_TURNS")
    # Rows echoed into the transcript per query result. A clipped result always
    # tells the model "showing N of M rows" — never a silent sample.
    miner_rows_shown: int = Field(default=40, alias="ROWS_SHOWN_TO_MODEL")
    # Older tool results collapse to code-built one-line factual summaries.
    miner_recent_results_kept: int = Field(default=3, alias="RECENT_RESULTS_KEPT")
    # Per-payload character cap on tool results (40 rows won't fit in 1,500).
    miner_tool_result_char_cap: int = Field(default=4_000, alias="TOOL_RESULT_CHAR_CAP")
    # Query-free turns granted when a budget trips — degrade, never truncate.
    miner_wrapup_turns: int = Field(default=3, alias="MINER_WRAPUP_TURNS")
    # Queries that must remain for free exploration after the opening queries.
    miner_exploration_reserve: int = Field(default=6, alias="MINER_EXPLORATION_RESERVE")
    # Round 3 task 2: EVIDENCE_STORED_CAP and EVIDENCE_DISPLAY_CAP are REMOVED
    # — evidence carries every row behind a finding (sorted by contribution,
    # footer totals reconcile); the UI paginates, storage never truncates.
    # Drill-down budgets (query budget, turn cap) per scope tier — ROUND_G 3.3.
    drilldown_product_query_budget: int = Field(default=8, alias="DRILLDOWN_PRODUCT_QUERY_BUDGET")
    drilldown_product_turn_cap: int = Field(default=12, alias="DRILLDOWN_PRODUCT_TURN_CAP")
    drilldown_sub_query_budget: int = Field(default=6, alias="DRILLDOWN_SUB_QUERY_BUDGET")
    drilldown_sub_turn_cap: int = Field(default=10, alias="DRILLDOWN_SUB_TURN_CAP")
    # Reporter document searches per run; Rule Compiler lookups/repair rounds.
    reporter_max_searches: int = Field(default=4, alias="REPORTER_MAX_SEARCHES")
    # Round A2B 6.7: the Coach's own token budget — prompt tokens (input +
    # cache) one coaching generation may consume; recorded when it binds.
    coach_max_input_tokens: int = Field(default=30_000, alias="COACH_MAX_INPUT_TOKENS")
    coach_max_searches: int = Field(default=4, alias="COACH_MAX_SEARCHES")
    rule_compiler_max_searches: int = Field(default=2, alias="RULE_COMPILER_MAX_SEARCHES")
    rule_compiler_max_repairs: int = Field(default=2, alias="RULE_COMPILER_MAX_REPAIRS")
    # Runaway-loop backstop on ingestion batch calls per entity. Round 2a: the
    # measured client volumes size it — the largest single entity is 12,436,738
    # rows (revenue_transaction and its per-txn edges), which at batch 5000 is
    # 2,488 legitimate batch calls; 500 would abort the real load. 10,000 keeps
    # ~4x headroom while still catching a genuinely stuck resume loop.
    ingestion_max_batch_calls: int = Field(default=10_000, alias="INGESTION_MAX_BATCH_CALLS_PER_ENTITY")
    # Round 2a task 1: MEASURED default write-batch size. Client-environment
    # measurement at batch 500/1000/5000: 3,169 / 5,375 / 7,706 rows/s (54 ms
    # RESTPP round trip — a 500-row batch spends nearly half its wall time on
    # the network). The manifest carries the same value; INGESTION_BATCH_SIZE
    # set in the env overrides the manifest (entity_registry resolves it).
    ingestion_batch_size: int = Field(default=5000, alias="INGESTION_BATCH_SIZE")

    # --- Round E chat (ROUND_E_CHAT_SPEC). The chat agent runs on Opus — the
    # one place a subtle reasoning failure is expensive and hard to spot; the
    # non-empty model default deliberately makes the role "configured" (coach
    # precedent) so it never silently inherits the Haiku default. The guardrail
    # classifier is a cheap, fast tagging pass — Haiku.
    chat_mode: str = Field(default="", alias="CHAT_MODE")
    chat_model: str = Field(default="claude-opus-4-6", alias="CHAT_MODEL")
    chat_deployment: str = Field(default="", alias="CHAT_DEPLOYMENT")
    chat_api_version: str = Field(default="", alias="CHAT_API_VERSION")
    chat_temperature: float = Field(default=1.0, alias="CHAT_TEMPERATURE")
    chat_guardrail_mode: str = Field(default="", alias="CHAT_GUARDRAIL_MODE")
    chat_guardrail_model: str = Field(default="claude-haiku-4-5-20251001",
                                      alias="CHAT_GUARDRAIL_MODEL")
    chat_guardrail_deployment: str = Field(default="", alias="CHAT_GUARDRAIL_DEPLOYMENT")
    chat_guardrail_api_version: str = Field(default="", alias="CHAT_GUARDRAIL_API_VERSION")
    chat_guardrail_temperature: float = Field(default=1.0, alias="CHAT_GUARDRAIL_TEMPERATURE")
    # Chat loop budgets — much tighter than the Miner's 25/35 (spec 3.6: answer
    # from stored insights and catalogued queries first). Round H rule: every
    # limit lives here with an env alias and is surfaced when it binds.
    chat_query_budget: int = Field(default=6, alias="CHAT_QUERY_BUDGET")
    chat_max_turns: int = Field(default=10, alias="CHAT_MAX_TURNS")
    chat_max_searches: int = Field(default=4, alias="CHAT_MAX_SEARCHES")
    chat_rows_shown: int = Field(default=30, alias="CHAT_ROWS_SHOWN")
    chat_max_input_tokens: int = Field(default=80_000, alias="CHAT_MAX_INPUT_TOKENS")
    # Layer 1 blocks ONLY at/above this confidence; ambiguity proceeds because
    # Layer 2 (the tool boundary) contains it — the V2 false-refusal fix.
    chat_guardrail_block_confidence: float = Field(
        default=0.8, alias="CHAT_GUARDRAIL_BLOCK_CONFIDENCE")
    # How many prior messages rehydrate into the agent's context on resume.
    chat_history_rehydrate_messages: int = Field(
        default=40, alias="CHAT_HISTORY_REHYDRATE_MESSAGES")

    # --- Storage paths ---
    chroma_path: str = Field(default="./chroma", alias="CHROMA_PATH")
    uploads_path: str = Field(default="./data/uploads", alias="UPLOADS_PATH")
    documents_path: str = Field(default="./data/documents", alias="DOCUMENTS_PATH")

    # --- API / frontend ---
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8002, alias="API_PORT")
    api_base_url: str = Field(default="http://127.0.0.1:8002", alias="API_BASE_URL")
    frontend_port: int = Field(default=3002, alias="FRONTEND_PORT")

    # --- Resolved absolute paths (single source of truth) ---
    @property
    def resolved_data_dir(self) -> Path:
        return resolve_app_path(self.data_dir)

    @property
    def resolved_manifest_path(self) -> Path:
        return self.resolved_data_dir / "manifest.json"

    @property
    def resolved_sqlite_db_path(self) -> Path:
        return resolve_app_path(self.sqlite_db_path)

    def resolved_paths_report(self) -> dict[str, str]:
        return {
            "app_root": str(APP_ROOT),
            "data_dir": str(self.resolved_data_dir),
            "ingestion_manifest": str(self.resolved_manifest_path),
            "checkpoint_db": str(self.resolved_sqlite_db_path),
            "chroma": str(resolve_app_path(self.chroma_path)),
            "env_file": str(APP_ROOT / ".env"),
            "log_dir": str(resolve_app_path(self.log_dir)),
        }

    def ensure_local_directories(self) -> None:
        for path in [
            self.sqlite_db_path,
            self.chroma_path,
            self.uploads_path,
            self.documents_path,
            self.log_dir,
        ]:
            candidate = resolve_app_path(path)
            if candidate.suffix:
                candidate.parent.mkdir(parents=True, exist_ok=True)
            else:
                candidate.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_local_directories()
    return settings
