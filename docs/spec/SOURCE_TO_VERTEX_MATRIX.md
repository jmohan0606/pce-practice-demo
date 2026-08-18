# Source-to-Vertex Traceability Matrix

Round 1 (schema freeze) task 4. Every vertex in the frozen schema (31 types)
traces to exactly one of four origins: a PostgreSQL table, a flat file, a
seeded constant, or the application itself. **There are THREE source kinds,
not one** — an extraction plan that covers only PostgreSQL is incomplete: the
four NNM `.txt` files and the CRM opportunity `.csv` never touch PostgreSQL
and are easy to forget.

All raw inputs land in ONE directory — `data/real/_raw/` — and
`scripts/build_real_data.py` detects each source kind by filename pattern
(`raw_*.csv` = PostgreSQL extracts; `ECNNM_*/NBNNM_*/YINNM_*/FSNNM_*.txt` =
the NNM files under their ORIGINAL names, preserving the category prefix;
`crm_opportunities.csv` = the CRM export). `scripts/validate_raw_extracts.py`
checks all three kinds before anything loads.

## 1. Source-loaded vertices (18)

| Source | Kind | Raw file (data/real/_raw/) | Vertex |
|---|---|---|---|
| `fpic_daily_trade_details_tb_prod` | PostgreSQL | `raw_txn_<month>_b<batch>.csv` chunks (or a single `raw_revenue_transaction.csv`) | `phx_dm_pce_revenue_transaction`; `phx_dm_pce_monthly_revenue` and `phx_dm_pce_rpg` **derived from it** by build_real_data.py |
| `product_hierarchy` | PostgreSQL | `raw_product_hierarchy.csv` | `phx_dm_pce_product` |
| `fpic_prm_rr_tb` + `fpic_employee_tb` | PostgreSQL | `raw_advisor.csv` (Round 5: `raw_advisor_flags.csv` retired — the client defines the cohort via `scripts/build_cohort.py`) | `phx_dm_pce_advisor` |
| `fpic_acct_tb_pm` | PostgreSQL | `raw_account.csv` | `phx_dm_pce_account` |
| `fpic_rr_changes_from_nacs_logs` | PostgreSQL | `raw_rr_changes.csv` | `phx_dm_pce_account_transfer` |
| `fpic_monthly_acct_balance_tb_april/_may/_june` | PostgreSQL | `raw_monthly_balance.csv` | `phx_dm_pce_account_month` |
| `fpic_acct_eci_rel_tb_pm` | PostgreSQL | `raw_acct_eci_rel.csv` | `phx_dm_pce_account_eci_rel`; `phx_dm_pce_household` **derived** |
| `fpic_acct_eci_map_tb` | PostgreSQL | `raw_acct_eci_map.csv` | `phx_dm_pce_account_eci_map` |
| `fpic_team_agreement_tb` | PostgreSQL | `raw_team_agreement.csv` | `phx_dm_pce_team_agreement` |
| `fpic_daily_adv_flows_tb_pm` | PostgreSQL | `raw_adv_flows.csv` | `phx_dm_pce_advisor_flow_month` |
| (operator-authored month metadata) | PostgreSQL-derived | `raw_month_meta.csv` | `phx_dm_pce_month` |
| **ECNNM / NBNNM / YINNM / FSNNM monthly files** | **flat files (.txt)** | `ECNNM_*.txt`, `NBNNM_*.txt`, `YINNM_*.txt`, `FSNNM_*.txt` — original names kept; **all four categories required or the build fails loudly** | `phx_dm_pce_advisor_nnm` |
| **CRM opportunity export** | **flat file (.csv)** | `crm_opportunities.csv` | `phx_dm_pce_opportunity` |
| seeded constants | none (shipped in code/build) | — | `phx_dm_pce_product_group` (25 rows + unmapped — Round 1b added `referrals_private_bank` for PCS/PBR), `phx_dm_pce_revenue_class` (2 rows) |

Notes:
- `phx_dm_pce_month` row content (trading days, baseline/partial flags) is
  operator-confirmed metadata over the extract's month range — the extraction
  SQL templates in `docs/data/extraction/` produce `raw_month_meta.csv`.
- Derived vertices (`monthly_revenue`, `rpg`, `household`) are computed by
  `build_real_data.py` — they have raw-file inputs but no raw file of their
  own; nothing loads them directly.

## 2. App-written vertices (13) — never extracted

Created empty at install; each store's runtime upsert is its loading job.

| Vertex | Written by |
|---|---|
| `phx_dm_pce_document` | document upload (KnowledgeManagementService) |
| `phx_dm_pce_document_chunk` | document upload |
| `phx_dm_pce_rule` | RuleStore (seed, extraction, manual authoring) |
| `phx_dm_pce_rule_set_version` | RuleStore publish |
| `phx_dm_pce_insight_run` | InsightStore |
| `phx_dm_pce_finding` | InsightStore |
| `phx_dm_pce_evidence_row` | InsightStore |
| `phx_dm_pce_agent_query_log` | MinerTools query logging |
| `phx_dm_pce_agent_turn_log` | TurnLoggingLLM (every LLM call) |
| `phx_dm_pce_feature_flag` | FlagStore |
| `phx_dm_pce_conversation` | ChatStore |
| `phx_dm_pce_chat_message` | ChatStore |
| `phx_dm_pce_job` | JobStore (Round 1 — document ingest, insight generation, data load) |

## 3. Edges

Every edge derives from its endpoint vertices' raw rows during
`build_real_data.py` (source-loaded) or from the owning store's runtime write
(app-written: `chunk_of_document`, `rule_in_version`, `rule_cites_chunk`,
`run_*`, `finding_*`, `evidence_of_finding`, `query_in_run`, `turn_in_run`,
`message_in_conversation`, `job_for_document`, `job_for_run`). No edge has an
independent source.
