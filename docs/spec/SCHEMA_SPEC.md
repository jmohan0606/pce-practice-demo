# pce-practice-demo — TigerGraph Schema Specification

**Graph:** `phx_dm_pce_practice_demo` · **Vertex prefix:** `phx_dm_pce_` · **GSQL Syntax V1**

This document is the contract between two parallel workstreams. Claude Code builds the application
against it; Copilot extracts and loads data against it. **Neither may deviate.** If something here
is wrong, change this document first, then both sides.

---

## 0. Rules that apply everywhere

**Account key normalisation.** Account identifiers are zero-padded to different widths per source
table (10 / 15 / 8 / 25 chars). Every account key stored in the graph is normalised:

```sql
ltrim(trim(account_no), '0')     -- '0000001590' -> '1590'
```

Apply this to **every** account column at extraction: `account_no`, `account_number`,
`wm_acct_src_nb`. Store the raw value alongside as `account_no_raw` for evidence display.

**Credited revenue.**
```sql
credited_amt = post_split_credited_amt WHERE reason_cd IS NULL OR trim(reason_cd) = ''
```
Rows with a populated reason code are **still loaded** (as `non_credited_amt`) so the agent can
investigate eligibility movement. They are excluded from credited totals.

**Month.** Derived from `trade_dt`, never `proc_dt`. `month_id = to_char(trade_dt,'YYYYMM')`.

**Team agreements are reference data only.** `post_split_credited_amt` already carries the team
share (verified: `split_pct == prm_share_pct`). Never re-apply a share percentage. Never join
trade rows to `fpic_team_agreement_tb` when summing revenue — it fans out one row per secondary
member.

**Households.** Load **every** account-to-party relationship, all codes. Filter to ownership roles
— `enterprise_relationship_code IN ('001','151','201')`, flagged as `is_owner_role` — **at query
time, when rolling up revenue**. Beneficiary (802) is 7.5M rows and does not own the account, so
including it in a rollup double-counts; but the rows stay in the graph because future CRM
opportunity and lead data attaches to the same households and will need the full relationship set.
Extraction must not delete what a later use case needs.

**PII is never extracted.** Exclude `tax_id`, `tax_id_type`, `mail_addr_line_1..6`,
`mail_addr_zip_cd`, `account_name`, `cust_full_nm`, `prty_shrt_nm`. None is needed by any driver.

**Scope.** `trade_dt >= '2026-04-01' AND trade_dt < '2026-07-01'`, cohort of 10–20 advisor SIDs.
April is the **baseline month** — no prior month exists, so lost-account detection starts at May.

---

## 1. Source-loaded vertices (18) — Copilot extracts these

### V1 · `phx_dm_pce_month`
```sql
CREATE VERTEX phx_dm_pce_month (PRIMARY_ID month_id STRING, month_name STRING,
  start_dt DATETIME, end_dt DATETIME, trading_days INT, is_baseline BOOL, is_partial BOOL)
WITH primary_id_as_attribute="true";
```
CSV `month_id,month_name,start_dt,end_dt,trading_days,is_baseline,is_partial`

Three rows, hand-written:
```
202604,Apr 2026,2026-04-01,2026-04-30,30,true,false
202605,May 2026,2026-05-01,2026-05-31,31,false,false
202606,Jun 2026,2026-06-01,2026-06-30,30,false,false
```
`trading_days` = `count(DISTINCT trade_dt)` per month. Phase 0 in the client environment
confirmed June is COMPLETE (`min_trade_dt=2026-06-01`, `max_trade_dt=2026-06-30`, 30 distinct
dates) — the source table accrues daily, so every calendar day has rows and the counts are the
calendar-day counts 30 / 31 / 30. `is_partial=false` on all three months.

### V2 · `phx_dm_pce_revenue_class`
```sql
CREATE VERTEX phx_dm_pce_revenue_class (PRIMARY_ID class_id STRING, class_name STRING)
WITH primary_id_as_attribute="true";
```
Two rows: `RECURRING,Recurring` · `NON_RECURRING,Non-Recurring`

### V3 · `phx_dm_pce_product_group` — the display row in the product table
```sql
CREATE VERTEX phx_dm_pce_product_group (PRIMARY_ID group_id STRING, group_name STRING,
  display_prefix STRING, class_id STRING, sort_order INT, is_aggregated BOOL)
WITH primary_id_as_attribute="true";
```
Seeded from §4 (24 rows). `display_prefix` is `TWHS` where applicable, else empty.

### V4 · `phx_dm_pce_product`
```sql
CREATE VERTEX phx_dm_pce_product (PRIMARY_ID product_id STRING, product_cd STRING,
  product_sub_cd STRING, product_name STRING, sor STRING, file_key STRING,
  group_id STRING, grid_type STRING) WITH primary_id_as_attribute="true";
```
`product_id = product_cd || '|' || product_sub_cd`. Source `pcr.product_hierarchy` filtered to
`grid_type = 'PRODUCT_TYPE'`. Products not in the §4 mapping keep their `level_two_product` name
and map to group `unmapped`.

### V5 · `phx_dm_pce_advisor`
```sql
CREATE VERTEX phx_dm_pce_advisor (PRIMARY_ID advisor_sid STRING, rep_code STRING,
  advisor_name STRING, branch_cd STRING, employee_id STRING, in_cohort BOOL,
  job_code STRING)
WITH primary_id_as_attribute="true";
```
Source `pcr.fpic_prm_rr_tb` (`standard_id`, `prm_rr_no`, `cwm_branch_cd`) joined to
`pcr.fpic_employee_tb` (`em_standard_id` → `em_name_txt`, `job_cd` → `job_code`).
Blank name → leave blank, never invent. `job_code` (Round 1b, confirmed
`fpic_employee_tb.job_cd varchar(30) not null`) is CARRIED, not used: plan
applicability by job code (SAG p.9 — HK0176/HK0186/HK0187/HK0188 → CWM Select
Advisor) waits for the client to confirm the job-code→plan mapping. A blank
job_code stays blank.
Load cohort advisors **plus** any advisor appearing as a transfer counterparty, with
`in_cohort=false` for the latter.

*No region/market — confirmed absent from the source. Deferred.*

### V6 · `phx_dm_pce_account`
```sql
CREATE VERTEX phx_dm_pce_account (PRIMARY_ID acct_key STRING, account_no_raw STRING,
  account_class_cd STRING, account_class_nm STRING, account_lob_cd STRING,
  account_purpose_cd STRING, managed_platform_cd STRING, service_channel_cd STRING,
  account_open_dt DATETIME, is_managed BOOL, opened_in_scope BOOL, primary_eci_id STRING)
WITH primary_id_as_attribute="true";
```
Source `pcr.fpic_acct_tb_pm`. `account_open_dt` is **text in `MM/DD/YYYY HH:MI:SS AM`** and may be
blank — parse with `to_timestamp(account_open_dt,'MM/DD/YYYY HH12:MI:SS AM')`, NULL on blank.
`is_managed = managed_platform_cd IS NOT NULL`. `primary_eci_id` from `party_primary_eci` — the
simplest account-to-household path, alongside the fuller role detail in V7b.
`opened_in_scope = account_open_dt >= '2026-04-01' AND < '2026-07-01'` — this is the new-account
signal.

⚠ This table is a **current-state snapshot** with no date column. Do **not** load
`financial_advisor_cd` — advisor attribution comes from transactions and transfers, never from here.

### V7 · `phx_dm_pce_household`
```sql
CREATE VERTEX phx_dm_pce_household (PRIMARY_ID eci_id STRING, account_count INT)
WITH primary_id_as_attribute="true";
```
Distinct `party_eci_id` from `pcr.fpic_acct_eci_rel_tb_pm`, **all relationship codes** — do not
filter at extraction. Households are also the attachment point for future CRM opportunity and lead
data, so the full relationship set is preserved in the graph and narrowed at query time instead.

### V7b · `phx_dm_pce_account_eci_rel` — account-to-party relationship, roles preserved
```sql
CREATE VERTEX phx_dm_pce_account_eci_rel (PRIMARY_ID rel_id STRING, acct_key STRING,
  eci_id STRING, enterprise_relationship_code STRING, party_role_name STRING,
  client_employee_ind STRING, is_owner_role BOOL) WITH primary_id_as_attribute="true";
```
`rel_id = acct_key ||'|'|| eci_id ||'|'|| enterprise_relationship_code` — the full source PK.
Source `pcr.fpic_acct_eci_rel_tb_pm`. Load **every** row.

`is_owner_role = enterprise_relationship_code IN ('001','151','201')` — Sole Owner, Primary Joint
Owner, Sec Joint Owner. **Revenue rollups filter on `is_owner_role = true`.** Beneficiary (802) is
7.5M rows and does not own the account; including it in a rollup double-counts revenue. But the
beneficiary rows are still loaded, because a future CRM join will need them.

### V7c · `phx_dm_pce_account_eci_map` — cross-system bridge
```sql
CREATE VERTEX phx_dm_pce_account_eci_map (PRIMARY_ID map_id STRING, acct_src_key STRING,
  acct_src_raw STRING, wm_src_sys_cd STRING, eci_id STRING, bus_dt DATETIME,
  new_exst_adv_clnt_in STRING) WITH primary_id_as_attribute="true";
```
`map_id = bus_dt ||'|'|| wm_src_sys_cd ||'|'|| acct_src_key`. Source `pcr.fpic_acct_eci_map_tb`
(`bus_dt` is varchar — cast it). `acct_src_key = ltrim(trim(wm_acct_src_nb),'0')`.

This is the **only** table carrying both account key families, so it is the bridge between
trade-side `account_no` and flow-side `wm_acct_src_nb`. Load the latest `bus_dt` per account only —
it is a daily snapshot and older rows add nothing. Also the join path CRM records would use to
reach an account.

### V7d · `phx_dm_pce_rpg` — related party group
```sql
CREATE VERTEX phx_dm_pce_rpg (PRIMARY_ID rpg_id STRING, account_count INT)
WITH primary_id_as_attribute="true";
```
Distinct non-blank `rpg` from `pcr.fpic_daily_trade_details_tb_prod` within scope.

**Why this is a vertex and not just an attribute:** the discount-sharing rule applies *at RPG
level*, not per account. Deciding whether a group crosses the 10% threshold requires walking from
an account to its siblings in the same RPG — a traversal, not a filter. This is the one grouping in
the comp plans that works this way.

Note RPG and ECI are **different groupings** from different sources; do not assume they collapse
one-to-one until the data says so.

### V8 · `phx_dm_pce_team_agreement`
```sql
CREATE VERTEX phx_dm_pce_team_agreement (PRIMARY_ID agreement_key STRING, agreement_id INT,
  team_rep_cd STRING, agreement_type STRING, status_cd STRING, prm_advisor_sid STRING,
  prm_share_pct DOUBLE, sec_advisor_sid STRING, sec_share_pct DOUBLE,
  start_ts DATETIME, end_ts DATETIME) WITH primary_id_as_attribute="true";
```
`agreement_key = agreement_id ||'|'|| team_rep_cd ||'|'|| prm_standard_id ||'|'|| sec_standard_id
||'|'|| to_char(start_ts,'YYYYMMDD')` — the full source PK, or rows collide.
Shares are **fractions** (0.0–1.0), stored as-is. Reference only.

### V9 · `phx_dm_pce_revenue_transaction`
```sql
CREATE VERTEX phx_dm_pce_revenue_transaction (PRIMARY_ID txn_id STRING, trade_ref_no STRING,
  split_seq_no STRING, advisor_sid STRING, acct_key STRING, product_id STRING,
  month_id STRING, trade_dt DATETIME, proc_dt DATETIME, days_to_process INT,
  credited_amt DOUBLE, non_credited_amt DOUBLE, pre_split_amt DOUBLE, split_pct DOUBLE,
  reason_cd STRING, is_credited BOOL, standard_rate_bps DOUBLE, client_rate_bps DOUBLE,
  discount_amt DOUBLE, eff_disc_pct DOUBLE, grid_reduction DOUBLE, rpg STRING,
  concession_type STRING, file_key STRING, trade_description STRING)
WITH primary_id_as_attribute="true";
```
`txn_id = trade_ref_no ||'|'|| split_seq_no ||'|'|| advisor_sid`.
`reason_cd` blank/null → store `__NONE__`. `is_credited = (reason_cd = '__NONE__')`.
`credited_amt` = post-split amount when credited, else 0. `non_credited_amt` = the mirror.
Estimated ~60k rows for 20 advisors over 3 months.

### V10 · `phx_dm_pce_monthly_revenue` — drives the chart and product table
```sql
CREATE VERTEX phx_dm_pce_monthly_revenue (PRIMARY_ID mr_id STRING, advisor_sid STRING,
  month_id STRING, product_id STRING, group_id STRING, class_id STRING,
  credited_amt DOUBLE, non_credited_amt DOUBLE, txn_count INT, distinct_accounts INT)
WITH primary_id_as_attribute="true";
```
`mr_id = advisor_sid ||'|'|| month_id ||'|'|| product_id` — **advisor-scoped, per the R16 lesson.**
Aggregate of V9. Totals for "All Advisors" are summed at query time, not pre-aggregated.

### V11 · `phx_dm_pce_account_month`
```sql
CREATE VERTEX phx_dm_pce_account_month (PRIMARY_ID am_id STRING, acct_key STRING,
  advisor_sid STRING, month_id STRING, end_balance DOUBLE, credited_amt DOUBLE,
  txn_count INT, is_zero_balance BOOL, present_prior_month BOOL,
  prior_end_balance DOUBLE, prior_credited_amt DOUBLE)
WITH primary_id_as_attribute="true";
```
`am_id = acct_key ||'|'|| advisor_sid ||'|'|| month_id`.
Balance from `pcr.fpic_monthly_acct_balance_tb_april / _may / _june`; revenue from V9.
`is_zero_balance = end_balance = 0`. `present_prior_month` is false for all April rows (baseline).
`prior_end_balance` / `prior_credited_amt` carry the previous month's balance and credited
revenue onto the row (0 for the baseline month) — a lost account is one that is zero NOW but
had revenue in the PRIOR month, and a same-vertex rule cannot otherwise see across months.
This vertex answers new / lost / moved.

### V12 · `phx_dm_pce_account_transfer`
```sql
CREATE VERTEX phx_dm_pce_account_transfer (PRIMARY_ID transfer_id STRING, acct_key STRING,
  from_advisor_sid STRING, to_advisor_sid STRING, from_rr STRING, to_rr STRING,
  transfer_ts DATETIME, month_id STRING, is_intra_team BOOL, occd_cd STRING)
WITH primary_id_as_attribute="true";
```
`transfer_id = occd_cd ||'|'|| acct_key ||'|'|| from_rr ||'|'|| seq_no ||'|'||
to_char(transfer_ts,'YYYYMMDDHH24MISS')` — the full source PK.
`from_advisor_sid = from_mem_sid`, `to_advisor_sid = to_mem_sid`.
`is_intra_team = (from_rr = to_rr)` — measured at zero in Q2, but keep the flag.
Filter to transfers touching a cohort account.

### V13 · `phx_dm_pce_advisor_flow_month`
```sql
CREATE VERTEX phx_dm_pce_advisor_flow_month (PRIMARY_ID afm_id STRING, advisor_sid STRING,
  month_id STRING, flow_product_cd STRING, flow_product_desc STRING, comp_group_type STRING,
  total_inflows DOUBLE, total_outflows DOUBLE, total_net_flows DOUBLE, credited_flows DOUBLE,
  departed_advisor_sid STRING, departed_advisor_excl_am DOUBLE, lob_trfr_excl_am DOUBLE,
  oi_pa_referral_cap_adj_am DOUBLE, large_flow_cap_adj_am DOUBLE, forced_closure_excl_am DOUBLE)
WITH primary_id_as_attribute="true";
```
`afm_id = advisor_sid ||'|'|| month_id ||'|'|| flow_product_cd`.
Source `pcr.fpic_daily_adv_flows_tb_pm`, aggregated by `bus_dt` month. **Flatten the
`other_attributes` JSONB into the named columns above** — those keys map directly onto comp-plan
mechanics and are far more useful as attributes than as a blob.

**Grain is advisor × month × flow product — no account join required.** `pri_rep_cd` /
`rep_wrkr_sid` belong to the rep-code family, which reaches `advisor_sid` through
`pcr.fpic_prm_rr_tb`. This is why the unresolved account-key question does not block this vertex.

**April and May only** — June has no flow rows. Flows carry their own product taxonomy
(`cwm_flow_comp_prod_cd`), which does not match `product_hierarchy`; no crosswalk exists yet, so
flow figures are reported at advisor grain and not merged into the product table.

Required, not optional: inflows, outflows and net flows are the only source for the NNM award rule
(`Total Annual NNM >= $4MM x Award Rate x Effective Grid Rate`), which is one of the two central
formulas in the comp plans.

### V14 · `phx_dm_pce_opportunity` — CRM pipeline (real Salesforce extract shape, Round F2)
```sql
CREATE VERTEX phx_dm_pce_opportunity (PRIMARY_ID opportunity_id STRING, eci_id STRING,
  advisor_sid STRING, advisor_sid_raw STRING, advisor_valid BOOL,
  account_record_type STRING, product_service_type STRING, stage_name STRING,
  stage_group STRING, amount DOUBLE, actual_assets DOUBLE,
  anticipated_investment_dt DATETIME, created_dt DATETIME,
  last_modified_dt DATETIME, date_of_last_contact DATETIME, days_to_close INT,
  is_stalled BOOL, comments STRING, ai_read STRING, ai_read_confidence DOUBLE,
  ai_read_evidence STRING, ai_read_model STRING, data_source STRING)
WITH primary_id_as_attribute="true";
```
CSV `opportunity_id,eci_id,advisor_sid,advisor_sid_raw,advisor_valid,account_record_type,product_service_type,stage_name,stage_group,amount,actual_assets,anticipated_investment_dt,created_dt,last_modified_dt,date_of_last_contact,days_to_close,is_stalled,comments,ai_read,ai_read_confidence,ai_read_evidence,ai_read_model,data_source`

CRM pipeline matching the REAL extract (`45f440b6…csv`, 308,534 rows firm-wide; filtered to the
cohort at build — see `docs/spec/CRM_AND_PLAN_FINDINGS.md` §1). Joined through ECI
(`eci_id` = `eci__c` → `phx_dm_pce_household`); `advisor_sid` = `ownersid__c` with any
`_CWM_INVALID`-style suffix stripped — the original stays in `advisor_sid_raw` and
`advisor_valid=false` marks it (counted and reported at validation, never dropped, never silently
joined). `amount` is the Salesforce standard Amount — the **forecast pipeline value**;
`actual_assets` (`actual_assets__c`, a custom field) is the **assets that landed**; the two are
NEVER summed (working interpretation, DECISIONS.md 2026-08-16). `stage_name` carries the source's
15 stages; `stage_group` is derived `EARLY | MID | LATE | CLOSING`. **The source has NO Won/Lost
stage and none is invented** — outcome hints live only in free text. `days_to_close` is often
negative (past the anticipated close) → `is_stalled = days_to_close < 0`. `comments` is the raw
free text kept verbatim; `ai_read` / `ai_read_confidence` / `ai_read_evidence` / `ai_read_model`
are the ONE-TIME ingestion LLM interpretation of it — descriptive only, never drives any figure,
rule, filter or total; `ai_read_evidence` is the exact substring the reading came from; "no
signal" rows leave `ai_read` empty. `data_source = 'CRM'`.
Edges: `phx_dm_pce_opportunity_for_household → household`,
`phx_dm_pce_opportunity_by_advisor → advisor`.

### V15s · `phx_dm_pce_advisor_nnm` — NNM by category (Round F2)
```sql
CREATE VERTEX phx_dm_pce_advisor_nnm (PRIMARY_ID nnm_id STRING,
  advisor_sid STRING, month_id STRING, category STRING, category_source STRING,
  mtd_nnm DOUBLE, ytd_nnm DOUBLE, entry_dt DATETIME, as_of_dt DATETIME)
WITH primary_id_as_attribute="true";
```
CSV `nnm_id,advisor_sid,month_id,category,category_source,mtd_nnm,ytd_nnm,entry_dt,as_of_dt`

`nnm_id = advisor_sid ||'|'|| month_id ||'|'|| category`. Loaded from the four pipe-delimited NNM
files (`ECNNM_*/NBNNM_*/YINNM_*/FSNNM_*.txt`): an `H<date>` header carries the as-of date, the `D`
column-header line names `Entry_Dt|StandardID|Month_Year|MTD_NNM|YTD_NNM`, and data rows prefix the
entry date with `D` (parser: `scripts/parse_nnm.py`). `category` ∈ `EC | NB | YI | FS`;
`category_source` keeps the raw file prefix because **only EC is confirmed by the plan document**
("Existing Client Annual NNM Flows" — PCA p.4); NB/YI/FS are inferred from filenames and
correctable without re-parsing. Values can be NEGATIVE in both NNM columns — real, not an error.
The YTD position for an advisor is the LATEST month's `ytd_nnm`, never a sum of MTD rows, and is
never annualised or extrapolated.
Edges: `phx_dm_pce_nnm_by_advisor → advisor`, `phx_dm_pce_nnm_in_month → month`.

---

## 2. App-written vertices (8) — Claude Code creates these, empty at load

```sql
CREATE VERTEX phx_dm_pce_document (PRIMARY_ID document_id STRING, document_name STRING,
  document_type STRING, page_count INT, content_hash STRING, status STRING,
  uploaded_at DATETIME) WITH primary_id_as_attribute="true";

CREATE VERTEX phx_dm_pce_document_chunk (PRIMARY_ID chunk_id STRING, document_id STRING,
  chunk_index INT, page_no INT, section_path STRING, chunk_text STRING,
  has_table BOOL, chroma_collection STRING) WITH primary_id_as_attribute="true";

CREATE VERTEX phx_dm_pce_rule_set_version (PRIMARY_ID version_id STRING, version_no INT,
  status STRING, rule_count INT, approved_by STRING, approved_at DATETIME, notes STRING)
WITH primary_id_as_attribute="true";

-- Round E (V15): the four *_expr grammar columns are replaced by the
-- plain-English statement + the Rule Compiler's plan_json / explanation;
-- missing_note carries a NEEDS_INPUT/NEEDS_DATA reason. kind is
-- TRIGGER|RECORD|EXCLUDE|WINDOW|CAP|CALCULATION.
-- Round 1 (schema freeze): eight exception-configuration attributes. The two
-- toggles are INDEPENDENT (a rule can be a good driver and a poor exception);
-- exception_denominator makes the exception a rate, not a count;
-- exception_floor (+_unit: accounts|revenue) suppresses small-book noise;
-- exception_sensitivity is a multiple of the cohort median — the threshold
-- comes from the data, never invented; product_scope is a comma-separated
-- group_id list ("" = all products) EXTRACTED from the plan document,
-- product_scope_source its citation or "NOT STATED". Evaluation using these
-- fields is Round 2; the edit UI is Round 3 — the schema is final now.
CREATE VERTEX phx_dm_pce_rule (PRIMARY_ID rule_key STRING, version_id STRING, rule_code STRING,
  rule_name STRING, statement STRING, worked_example STRING, kind STRING,
  plan_json STRING, explanation STRING, missing_note STRING, grain STRING,
  provenance STRING, confidence DOUBLE, status STRING,
  driver_enabled BOOL, exception_enabled BOOL, exception_denominator STRING,
  exception_floor DOUBLE, exception_floor_unit STRING, exception_sensitivity DOUBLE,
  product_scope STRING, product_scope_source STRING) WITH primary_id_as_attribute="true";

CREATE VERTEX phx_dm_pce_insight_run (PRIMARY_ID run_id STRING, advisor_sid STRING,
  from_month_id STRING, to_month_id STRING, version_id STRING, status STRING,
  query_count INT, budget_hit BOOL, budget_hit_tokens BOOL, started_at DATETIME,
  completed_at DATETIME, narrative STRING, bullets_json STRING,
  total_input_tokens INT, total_output_tokens INT, total_cache_read_tokens INT,
  est_cost_usd DOUBLE, wall_ms INT) WITH primary_id_as_attribute="true";

-- Round A1: driver_tag (display string) renamed driver_code (stable identity
-- slug, e.g. NEW_BILLING). The display label lives on the rule and resolves at
-- read time, so a driver rename reaches historical findings without rewrites.
CREATE VERTEX phx_dm_pce_finding (PRIMARY_ID finding_id STRING, run_id STRING, title STRING,
  summary STRING, impact_amt DOUBLE, driver_code STRING, product_id STRING,
  provenance STRING, rule_key STRING, rank_order INT) WITH primary_id_as_attribute="true";

CREATE VERTEX phx_dm_pce_evidence_row (PRIMARY_ID evidence_id STRING, finding_id STRING,
  row_index INT, row_json STRING) WITH primary_id_as_attribute="true";

CREATE VERTEX phx_dm_pce_agent_query_log (PRIMARY_ID query_id STRING, run_id STRING,
  seq_no INT, agent_name STRING, query_name STRING, params_json STRING,
  row_count INT, latency_ms INT) WITH primary_id_as_attribute="true";

-- One row per LLM turn (miner, reporter, extractor, conflict auditor). All four
-- token fields come from the provider's response.usage — never estimated.
CREATE VERTEX phx_dm_pce_agent_turn_log (PRIMARY_ID turn_id STRING, run_id STRING,
  seq_no INT, agent_name STRING, model STRING, input_tokens INT, output_tokens INT,
  cache_read_tokens INT, cache_write_tokens INT, latency_ms INT, action_kind STRING,
  query_name STRING, est_cost_usd DOUBLE) WITH primary_id_as_attribute="true";

-- Round A2B task 7 — feature-flag state (app-written; the FlagStore's runtime
-- upsert is its loading job). Current state only; the change history lives in
-- the app's durable SQLite (data/runtime/feature_flags.db).
CREATE VERTEX phx_dm_pce_feature_flag (PRIMARY_ID flag_key STRING, enabled BOOL,
  updated_at STRING, updated_by STRING, note_reason STRING, note_at STRING)
  WITH primary_id_as_attribute="true";

-- Round E chat (Tasks 4–5) — conversations and messages (app-written; the
-- ChatStore's runtime upsert is its loading job — precedent
-- phx_dm_pce_agent_turn_log). Global persistence for now: every user sees
-- every conversation (demo simplification, DECISIONS.md). Durable copy lives
-- in the app's SQLite (data/runtime/chat.db); the graph carries the
-- schema-catalogued subset (guardrail_json / extra_json are SQLite-only).
CREATE VERTEX phx_dm_pce_conversation (PRIMARY_ID conversation_id STRING, title STRING,
  created_at DATETIME, updated_at DATETIME, message_count INT)
  WITH primary_id_as_attribute="true";

CREATE VERTEX phx_dm_pce_chat_message (PRIMARY_ID message_id STRING, conversation_id STRING,
  seq_no INT, role STRING, text STRING, tool_calls_json STRING, guardrail_tag STRING,
  guardrail_confidence DOUBLE, reasoning_steps_json STRING, latency_ms INT,
  tokens_in INT, tokens_out INT, est_cost_usd DOUBLE, created_at DATETIME)
  WITH primary_id_as_attribute="true";

-- Round 1 (schema freeze) — resumable long-running work (app-written; the
-- JobStore's runtime upsert is its loading job, data/runtime/jobs.db durable).
-- Each stage writes its output before the next begins; an interrupted job
-- resumes at its recorded stage without repeating earlier ones. resume_token
-- is opaque JSON: enough to restart the CURRENT stage (per-item within
-- extract and investigate_residual — the slow stages; per-stage elsewhere).
-- Resume is EXPLICIT (a Resume action; never automatic — auto-resume could
-- double-spend). kind: document_ingest | insight_generation | data_load;
-- status: RUNNING | INTERRUPTED | COMPLETE | FAILED.
CREATE VERTEX phx_dm_pce_job (PRIMARY_ID job_id STRING, kind STRING,
  scope_key STRING, stage STRING, stage_index INT, stage_total INT,
  items_done INT, items_total INT, status STRING, resume_token STRING,
  error STRING, started_at DATETIME, updated_at DATETIME,
  completed_at DATETIME) WITH primary_id_as_attribute="true";
```

Job stages per kind: `document_ingest` = parse → chunk → embed → extract →
compile → audit; `insight_generation` = evaluate_rules → investigate_residual
→ narrate → persist; `data_load` = one stage per entity.

`rule_key = version_id ||'|'|| rule_code`. `run_id = advisor_sid ||'|'|| from_month_id ||'|'||
to_month_id ||'|'|| version_id`. `turn_id = run_id ||'|'|| seq_no` (extractor / conflict-auditor
turns use the synthetic run ids `doc_extract|<document_id>` / `conflict_audit|<scope>` — no
`phx_dm_pce_turn_in_run` edge instance exists for those). `message_id =
conversation_id ||'|'|| seq_no`. Every per-entity key embeds its
scope — R16, applied at design time.

---

## 3. Edges

```sql
-- product chain
CREATE DIRECTED EDGE phx_dm_pce_product_in_group (FROM phx_dm_pce_product, TO phx_dm_pce_product_group) WITH REVERSE_EDGE="phx_dm_pce_group_has_product";
CREATE DIRECTED EDGE phx_dm_pce_group_in_class (FROM phx_dm_pce_product_group, TO phx_dm_pce_revenue_class) WITH REVERSE_EDGE="phx_dm_pce_class_has_group";

-- transactions
CREATE DIRECTED EDGE phx_dm_pce_txn_by_advisor (FROM phx_dm_pce_revenue_transaction, TO phx_dm_pce_advisor) WITH REVERSE_EDGE="phx_dm_pce_advisor_has_txn";
CREATE DIRECTED EDGE phx_dm_pce_txn_for_account (FROM phx_dm_pce_revenue_transaction, TO phx_dm_pce_account) WITH REVERSE_EDGE="phx_dm_pce_account_has_txn";
CREATE DIRECTED EDGE phx_dm_pce_txn_of_product (FROM phx_dm_pce_revenue_transaction, TO phx_dm_pce_product) WITH REVERSE_EDGE="phx_dm_pce_product_has_txn";
CREATE DIRECTED EDGE phx_dm_pce_txn_in_month (FROM phx_dm_pce_revenue_transaction, TO phx_dm_pce_month) WITH REVERSE_EDGE="phx_dm_pce_month_has_txn";

-- monthly aggregates
CREATE DIRECTED EDGE phx_dm_pce_mr_by_advisor (FROM phx_dm_pce_monthly_revenue, TO phx_dm_pce_advisor) WITH REVERSE_EDGE="phx_dm_pce_advisor_has_mr";
CREATE DIRECTED EDGE phx_dm_pce_mr_in_month (FROM phx_dm_pce_monthly_revenue, TO phx_dm_pce_month) WITH REVERSE_EDGE="phx_dm_pce_month_has_mr";
CREATE DIRECTED EDGE phx_dm_pce_mr_of_product (FROM phx_dm_pce_monthly_revenue, TO phx_dm_pce_product) WITH REVERSE_EDGE="phx_dm_pce_product_has_mr";
CREATE DIRECTED EDGE phx_dm_pce_mr_in_group (FROM phx_dm_pce_monthly_revenue, TO phx_dm_pce_product_group) WITH REVERSE_EDGE="phx_dm_pce_group_has_mr";

-- account month
CREATE DIRECTED EDGE phx_dm_pce_am_for_account (FROM phx_dm_pce_account_month, TO phx_dm_pce_account) WITH REVERSE_EDGE="phx_dm_pce_account_has_am";
CREATE DIRECTED EDGE phx_dm_pce_am_by_advisor (FROM phx_dm_pce_account_month, TO phx_dm_pce_advisor) WITH REVERSE_EDGE="phx_dm_pce_advisor_has_am";
CREATE DIRECTED EDGE phx_dm_pce_am_in_month (FROM phx_dm_pce_account_month, TO phx_dm_pce_month) WITH REVERSE_EDGE="phx_dm_pce_month_has_am";

-- household / eci
CREATE DIRECTED EDGE phx_dm_pce_account_in_household (FROM phx_dm_pce_account, TO phx_dm_pce_household) WITH REVERSE_EDGE="phx_dm_pce_household_has_account";
CREATE DIRECTED EDGE phx_dm_pce_rel_of_account (FROM phx_dm_pce_account_eci_rel, TO phx_dm_pce_account) WITH REVERSE_EDGE="phx_dm_pce_account_has_rel";
CREATE DIRECTED EDGE phx_dm_pce_rel_to_household (FROM phx_dm_pce_account_eci_rel, TO phx_dm_pce_household) WITH REVERSE_EDGE="phx_dm_pce_household_has_rel";
CREATE DIRECTED EDGE phx_dm_pce_map_of_account (FROM phx_dm_pce_account_eci_map, TO phx_dm_pce_account) WITH REVERSE_EDGE="phx_dm_pce_account_has_map";
CREATE DIRECTED EDGE phx_dm_pce_map_to_household (FROM phx_dm_pce_account_eci_map, TO phx_dm_pce_household) WITH REVERSE_EDGE="phx_dm_pce_household_has_map";

-- rpg
CREATE DIRECTED EDGE phx_dm_pce_account_in_rpg (FROM phx_dm_pce_account, TO phx_dm_pce_rpg) WITH REVERSE_EDGE="phx_dm_pce_rpg_has_account";
CREATE DIRECTED EDGE phx_dm_pce_txn_in_rpg (FROM phx_dm_pce_revenue_transaction, TO phx_dm_pce_rpg) WITH REVERSE_EDGE="phx_dm_pce_rpg_has_txn";

-- transfers
CREATE DIRECTED EDGE phx_dm_pce_transfer_of_account (FROM phx_dm_pce_account_transfer, TO phx_dm_pce_account) WITH REVERSE_EDGE="phx_dm_pce_account_has_transfer";
CREATE DIRECTED EDGE phx_dm_pce_transfer_from (FROM phx_dm_pce_account_transfer, TO phx_dm_pce_advisor) WITH REVERSE_EDGE="phx_dm_pce_advisor_transferred_out";
CREATE DIRECTED EDGE phx_dm_pce_transfer_to (FROM phx_dm_pce_account_transfer, TO phx_dm_pce_advisor) WITH REVERSE_EDGE="phx_dm_pce_advisor_transferred_in";

-- team
CREATE DIRECTED EDGE phx_dm_pce_team_primary (FROM phx_dm_pce_team_agreement, TO phx_dm_pce_advisor) WITH REVERSE_EDGE="phx_dm_pce_advisor_primary_on";
CREATE DIRECTED EDGE phx_dm_pce_team_secondary (FROM phx_dm_pce_team_agreement, TO phx_dm_pce_advisor) WITH REVERSE_EDGE="phx_dm_pce_advisor_secondary_on";

-- flows
CREATE DIRECTED EDGE phx_dm_pce_flow_by_advisor (FROM phx_dm_pce_advisor_flow_month, TO phx_dm_pce_advisor) WITH REVERSE_EDGE="phx_dm_pce_advisor_has_flow";
CREATE DIRECTED EDGE phx_dm_pce_flow_in_month (FROM phx_dm_pce_advisor_flow_month, TO phx_dm_pce_month) WITH REVERSE_EDGE="phx_dm_pce_month_has_flow";

-- opportunity (CRM pipeline — real extract shape since Round F2, joined through ECI)
CREATE DIRECTED EDGE phx_dm_pce_opportunity_for_household (FROM phx_dm_pce_opportunity, TO phx_dm_pce_household) WITH REVERSE_EDGE="phx_dm_pce_household_has_opportunity";
CREATE DIRECTED EDGE phx_dm_pce_opportunity_by_advisor (FROM phx_dm_pce_opportunity, TO phx_dm_pce_advisor) WITH REVERSE_EDGE="phx_dm_pce_advisor_has_opportunity";

-- advisor NNM (Round F2)
CREATE DIRECTED EDGE phx_dm_pce_nnm_by_advisor (FROM phx_dm_pce_advisor_nnm, TO phx_dm_pce_advisor) WITH REVERSE_EDGE="phx_dm_pce_advisor_has_nnm";
CREATE DIRECTED EDGE phx_dm_pce_nnm_in_month (FROM phx_dm_pce_advisor_nnm, TO phx_dm_pce_month) WITH REVERSE_EDGE="phx_dm_pce_month_has_nnm";

-- rules & insights (app-written)
CREATE DIRECTED EDGE phx_dm_pce_chunk_of_document (FROM phx_dm_pce_document_chunk, TO phx_dm_pce_document) WITH REVERSE_EDGE="phx_dm_pce_document_has_chunk";
CREATE DIRECTED EDGE phx_dm_pce_rule_in_version (FROM phx_dm_pce_rule, TO phx_dm_pce_rule_set_version) WITH REVERSE_EDGE="phx_dm_pce_version_has_rule";
CREATE DIRECTED EDGE phx_dm_pce_rule_cites_chunk (FROM phx_dm_pce_rule, TO phx_dm_pce_document_chunk) WITH REVERSE_EDGE="phx_dm_pce_chunk_supports_rule";
CREATE DIRECTED EDGE phx_dm_pce_run_uses_version (FROM phx_dm_pce_insight_run, TO phx_dm_pce_rule_set_version) WITH REVERSE_EDGE="phx_dm_pce_version_used_by_run";
CREATE DIRECTED EDGE phx_dm_pce_run_for_advisor (FROM phx_dm_pce_insight_run, TO phx_dm_pce_advisor) WITH REVERSE_EDGE="phx_dm_pce_advisor_has_run";
CREATE DIRECTED EDGE phx_dm_pce_finding_in_run (FROM phx_dm_pce_finding, TO phx_dm_pce_insight_run) WITH REVERSE_EDGE="phx_dm_pce_run_has_finding";
CREATE DIRECTED EDGE phx_dm_pce_finding_matched_rule (FROM phx_dm_pce_finding, TO phx_dm_pce_rule) WITH REVERSE_EDGE="phx_dm_pce_rule_produced_finding";
CREATE DIRECTED EDGE phx_dm_pce_evidence_of_finding (FROM phx_dm_pce_evidence_row, TO phx_dm_pce_finding) WITH REVERSE_EDGE="phx_dm_pce_finding_has_evidence";
CREATE DIRECTED EDGE phx_dm_pce_query_in_run (FROM phx_dm_pce_agent_query_log, TO phx_dm_pce_insight_run) WITH REVERSE_EDGE="phx_dm_pce_run_has_query";
CREATE DIRECTED EDGE phx_dm_pce_turn_in_run (FROM phx_dm_pce_agent_turn_log, TO phx_dm_pce_insight_run) WITH REVERSE_EDGE="phx_dm_pce_run_has_turn";

-- chat (Round E, app-written)
CREATE DIRECTED EDGE phx_dm_pce_message_in_conversation (FROM phx_dm_pce_chat_message, TO phx_dm_pce_conversation) WITH REVERSE_EDGE="phx_dm_pce_conversation_has_message";

-- jobs (Round 1 schema freeze, app-written)
CREATE DIRECTED EDGE phx_dm_pce_job_for_document (FROM phx_dm_pce_job, TO phx_dm_pce_document) WITH REVERSE_EDGE="phx_dm_pce_document_has_job";
CREATE DIRECTED EDGE phx_dm_pce_job_for_run (FROM phx_dm_pce_job, TO phx_dm_pce_insight_run) WITH REVERSE_EDGE="phx_dm_pce_run_has_job";
```

**31 vertices (18 source-loaded + 13 app-written) · 44 edge types.** Drop order is the reverse of create order.

---

## 4. Product group seed (24 rows)

| sort | group_id | group_name | prefix | class | product_cd |
|---|---|---|---|---|---|
| 1 | managed_accounts | Managed Accounts | | RECURRING | OISC, OIS1, JPMC, MAP |
| 2 | managed_uma | Managed – Unified Managed Accounts | | RECURRING | UMA |
| 3 | trails_mutual_funds | Trails – Mutual Funds | | RECURRING | ATMF |
| 4 | trails_life_annuities | Trails – Life & Annuities | | RECURRING | ITMF, ADVA |
| 5 | cash_mgmt_mmkt | Cash Management – Money Market Funds | | RECURRING | MMKT |
| 6 | cash_mgmt_prdp | Cash Management – Premium Deposits | | RECURRING | PRDP |
| 7 | referrals_sit_partnership | Referrals & Revenue Share – Situational Partnership | | RECURRING | PCS |
| 8 | plans_529 | 529 Plans | | RECURRING | 529T |
| 9 | donor_advised_funds | Donor Advised Funds | | RECURRING | DAF |
| 10 | twhs_structured | Structured Products | TWHS | NON_RECURRING | STRT |
| 11 | twhs_equities | Equities | TWHS | NON_RECURRING | ELIS/EQ |
| 12 | twhs_options | Options | TWHS | NON_RECURRING | ELIS/OP |
| 13 | twhs_mutual_funds | Mutual Funds | TWHS | NON_RECURRING | MUFD |
| 14 | twhs_fi_corporate | Fixed Income – Corporate Bonds | TWHS | NON_RECURRING | FCXX |
| 15 | twhs_fi_municipal | Fixed Income – Municipal Bonds | TWHS | NON_RECURRING | FMXX |
| 16 | twhs_fi_government | Fixed Income – Government Bonds | TWHS | NON_RECURRING | FGXX |
| 17 | twhs_fi_other | Fixed Income – Other | TWHS | NON_RECURRING | FCOT |
| 18 | twhs_cash_mgmt_cds | Cash Management – Brokered CDs | TWHS | NON_RECURRING | FCCD |
| 19 | life_annuities | Life & Annuities | | NON_RECURRING | FIX, VARI, LIFE |
| 20 | alternative_investments | Alternative Investments | | NON_RECURRING | ALTI |
| 21 | defined_contribution_advisory | Defined Contribution Advisory | | NON_RECURRING | DCCR |
| 22 | lending_sbl | Lending – Security Based Lending | | NON_RECURRING | LEND/SBL |
| 23 | lending_margin | Lending – Margin | | NON_RECURRING | LEND/MGN |
| 24 | referrals_everyday_401k | Referrals & Revenue Share – Everyday 401K | | NON_RECURRING | EDK |
| 99 | unmapped | Unmapped Products | | NON_RECURRING | *(everything else)* |

Rows 11/12 and 22/23 split on `product_sub_cd` — the only two groups where `product_cd` alone is
insufficient. Everything else maps on `product_cd`.

Alternative Investments is **assumed** NON_RECURRING, unconfirmed by the client since V2 R11.

---

## 5. Extraction order and CSV contract

One CSV per vertex and per edge, named exactly for the type, header row required,
`QUOTE="double"` in the loading job (without it, JSON columns shear at the first comma).

```
1  cohort selection      -> docs/data/cohort_advisors.csv   (advisor_sid + scenario flags)
2  phx_dm_pce_month
3  phx_dm_pce_revenue_class
4  phx_dm_pce_product_group
5  phx_dm_pce_product
6  phx_dm_pce_advisor
7  phx_dm_pce_account
8  phx_dm_pce_household
9  phx_dm_pce_account_eci_rel        <- all relationship codes, not just owners
10 phx_dm_pce_account_eci_map        <- latest bus_dt per account only
11 phx_dm_pce_rpg
12 phx_dm_pce_team_agreement
13 phx_dm_pce_revenue_transaction    <- largest, ~60k rows
14 phx_dm_pce_monthly_revenue
15 phx_dm_pce_account_month
16 phx_dm_pce_account_transfer
17 phx_dm_pce_advisor_flow_month     <- Apr + May only
18 all edge files, derived from the vertex files
```

Ship a `manifest.json` with a row count per file. Ingestion verifies loaded counts against it and
fails loudly on mismatch.

**Cohort selection** — pick 10–20 advisors for scenario coverage, not just revenue. Required
coverage: accounts with fee reduction above 10%; at least one with a **recorded** `grid_reduction`
(only ~99 exist firmwide — select for this first); inbound and outbound transfers; accounts opened
in Q2; accounts zeroed between months; team agreements; and two or three advisors with nothing
dramatic, so not every insight reads as an alarm.

**Timeouts:** every extraction query must filter to the cohort and date range *before* aggregating,
and `SET statement_timeout = '600s'` at session start.
