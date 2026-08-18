# Copilot Task — Extract Data for the PCE Practice Demo (cold start)

You have no prior context. Everything you need is in this document.

---

## 0 · Context

We are building a **Practice Management Dashboard** for wealth-management advisors. It shows
month-over-month credited revenue by product for a cohort of advisors, and explains what drove the
change. The data layer is **TigerGraph**; PostgreSQL is the source.

**Your job:** extract from PostgreSQL and write CSV files that a graph loader will consume. You are
not building the application. You are producing 16 vertex files, 27 edge files and a manifest.

**Column names and order in the output must match this document exactly.** The loader raises
`ColumnMismatchError` and refuses to load on any deviation. Do not add columns, rename them, or
reorder them.

### Database

```
Host    nlb1b016e39-glbdep-v1-71d8d3fdc76fc824.elb.us-east-1.amazonaws.com
Port    6160
DB      fpicdb
User    fpicdbAuroraAppAdmin
Schema  pcr          (379 tables — only the ones below matter)
Auth    AWS IAM token. If you hit PAM/auth errors, the token has expired:
        run `aws sts get-caller-identity`, refresh SSO if it fails, then retry.
```

Always run first:
```sql
SET statement_timeout = '600s';
```

`pcr.fpic_daily_trade_details_tb_prod` is very large. **Every query against it must filter to the
cohort advisors and the date range before aggregating**, or it will time out.

**Scope:** `trade_dt >= DATE '2026-04-01' AND trade_dt < DATE '2026-07-01'` (Apr, May, Jun 2026).

### Deliverable

One re-runnable script, `scripts/extract_pce_data.py`, with a `--cohort-only` flag that stops after
phase 1. Output to `out/vertices/*.csv`, `out/edges/*.csv`, `out/manifest.json`.
Do not hand-run 43 separate queries.

---

## 1 · Phase 0 — Verify the source tables exist

Before anything else, confirm each table and its key columns. **Report anything missing and stop** —
do not substitute a similarly-named table or column.

| Table | Purpose | Key columns |
|---|---|---|
| `pcr.fpic_daily_trade_details_tb_prod` | Trades / revenue. One row per trade split per advisor. | `trade_ref_no`, `split_seq_no`, `advisor_sid`, `rep_code`, `account_no`, `trade_dt`, `proc_dt`, `product_cd`, `product_sub_cd`, `post_split_credited_amt`, `pre_split_credited_amt`, `split_pct`, `reason_cd`, `standard_rate_bps`, `client_rate_bps`, `discount_amt`, `eff_disc_pct`, `grid_reduction`, `rpg`, `concession_type`, `file_key`, `trade_description` |
| `pcr.product_hierarchy` | Product taxonomy | `product_code`, `sub_product_code`, `level_one_product`, `level_two_product`, `grid_type` |
| `pcr.fpic_prm_rr_tb` | Advisor master | `standard_id`, `prm_rr_no`, `cwm_branch_cd` |
| `pcr.fpic_employee_tb` | Advisor names | `em_standard_id`, `em_name_txt` |
| `pcr.fpic_acct_tb_pm` | Account master (current snapshot) | `account_number`, `account_class_cd`, `account_class_nm`, `account_lob_cd`, `account_purpose_cd`, `managed_platform_cd`, `service_channel_cd`, `account_open_dt` (TEXT), `party_primary_eci` |
| `pcr.fpic_rr_changes_from_nacs_logs` | Account transfers between advisors | `occd_cd`, `account_no`, `transfer_ts`, `seq_no`, `from_rr`, `from_mem_sid`, `to_rr`, `to_mem_sid` |
| `pcr.fpic_monthly_acct_balance_tb_april` / `_may` / `_june` | Month-end balances | account id + balance columns — **discover the exact names and report them** |
| `pcr.fpic_acct_eci_rel_tb_pm` | Account ↔ household party, with roles | `account_number`, `party_eci_id`, `enterprise_relationship_code`, `party_role_name`, `client_employee_ind` |
| `pcr.fpic_acct_eci_map_tb` | Cross-system account ↔ ECI map (daily snapshot) | `bus_dt` (varchar), `wm_src_sys_cd`, `wm_acct_src_nb`, `eci_nb`, `new_exst_adv_clnt_in` |
| `pcr.fpic_team_agreement_tb` | Team splits (reference only) | `agreement_id`, `team_rep_cd`, `team_agreement_typ`, `team_agreement_status_cd`, `prm_standard_id`, `prm_share_pct`, `sec_standard_id`, `sec_share_pct`, `start_ts`, `end_ts` |
| `pcr.fpic_daily_adv_flows_tb_pm` | Advisor cash flows | `bus_dt`, `pri_rep_cd`, `rep_wrkr_sid`, `wm_acct_src_nb`, `cwm_flow_comp_prod_cd`, `cwm_flow_comp_prod_desc_tx`, `cwm_comp_group_type`, `total_inflows_am`, `total_outflows_am`, `total_net_financial_flows`, `total_cwm_comp_credited_flows_am`, `other_attributes` (jsonb) |

Also report, before proceeding:
- `count(DISTINCT trade_dt)` per month for 202604 / 202605 / 202606
- `min(trade_dt)`, `max(trade_dt)` within June — June may be a partial month
- distinct `grid_type` values in `product_hierarchy`
- which months have rows in `fpic_daily_adv_flows_tb_pm`

---

## 2 · Phase 1 — Select the advisor cohort (20 advisors), then STOP

Revenue alone is the wrong criterion. The demo needs **scenario coverage**.

Score every candidate advisor with in-scope trades on these flags:

| Flag | Definition |
|---|---|
| `has_fee_reduction_gt10` | ≥1 account where `(standard_rate_bps - client_rate_bps)/standard_rate_bps*100 > 10` |
| `has_recorded_grid_reduction` | ≥1 row with `grid_reduction` non-zero. **SCARCE — roughly 99 accounts firmwide. Select for this FIRST.** |
| `has_transfer_in` | appears as `to_mem_sid` in `fpic_rr_changes_from_nacs_logs` in scope |
| `has_transfer_out` | appears as `from_mem_sid` in scope |
| `has_new_account` | ≥1 account whose `account_open_dt` falls inside the window |
| `has_zeroed_account` | ≥1 account whose monthly balance drops to 0 between Apr/May or May/Jun |
| `has_team_agreement` | appears in `fpic_team_agreement_tb` as primary or secondary, active |
| `has_flows` | appears in `fpic_daily_adv_flows_tb_pm` |
| `has_non_credited` | ≥1 in-scope row with a populated `reason_cd` |

**Selection order:** take every advisor with `has_recorded_grid_reduction` (up to 5) → greedily add
advisors covering the most still-uncovered flags → fill to 20 by highest
`sum(post_split_credited_amt)`. **Deliberately include 2–3 advisors with none of the flags** — a
cohort where every advisor has a dramatic story does not read as real data.

Write `out/cohort_advisors.csv`:
```
advisor_sid,rep_code,advisor_name,total_credited_amt,has_fee_reduction_gt10,has_recorded_grid_reduction,has_transfer_in,has_transfer_out,has_new_account,has_zeroed_account,has_team_agreement,has_flows,has_non_credited
```

Print the coverage matrix and **stop for review.** Do not start phase 2 unprompted.

---

## 3 · Transformation rules — apply everywhere

Getting any of these wrong corrupts the whole dataset silently.

**Account key normalisation.** Account numbers are zero-padded to different widths per table (10 /
15 / 8 / 25 chars). Normalise every account column with `ltrim(trim(x),'0')` — `account_no`,
`account_number`, `wm_acct_src_nb`. Keep the raw value in the matching `*_raw` column. A key that
normalises to empty stays empty; never invent one.

**Credited revenue.**
```sql
reason_cd_out    = COALESCE(NULLIF(trim(reason_cd),''), '__NONE__')
credited_amt     = CASE WHEN reason_cd_out = '__NONE__' THEN post_split_credited_amt ELSE 0 END
non_credited_amt = CASE WHEN reason_cd_out = '__NONE__' THEN 0 ELSE post_split_credited_amt END
is_credited      = (reason_cd_out = '__NONE__')
```
Rows with a populated reason code are **still extracted** — they are excluded from credited totals
but must exist in the graph.

**Never join trades to `fpic_team_agreement_tb`.** `post_split_credited_amt` already carries the
team share (verified: `split_pct = prm_share_pct`). Joining also fans out one row per secondary
team member, multiplying revenue. Team agreements are extracted as standalone reference data only.

**Month** = `to_char(proc_dt,'YYYYMM')` — **CORRECTED (Round 5, client-confirmed 17 Aug 2026):** month and scope derive from `proc_dt` — the client's authoritative PCE report is dated by it (`proc_dt` reconciles to 0.36%; `trade_dt` is 1.7% off and never reconciles). `trade_dt` is still extracted and stored as the business date. *(Original, superseded text said never `proc_dt` because it runs after month end and
will mis-assign rows across month boundaries.

**Never extract PII:** `tax_id`, `tax_id_type`, `mail_addr_line_1..6`, `mail_addr_zip_cd`,
`account_name`, `cust_full_nm`, `prty_shrt_nm`.

**Formatting.** Booleans as lowercase `true`/`false`. Timestamps `YYYY-MM-DD HH:MM:SS`. Dates
`YYYY-MM-DD`. Empty string for null strings, `0` for null numerics. CSV with `QUOTE_MINIMAL`,
UTF-8, **LF line endings** (`open(..., newline='')` and `\n`).

---

## 4 · Phase 2 — Vertex files (16)

Headers exact and ordered.

### `phx_dm_pce_month.csv` — 3 rows
```
month_id,month_name,start_dt,end_dt,trading_days,is_baseline,is_partial
```
`month_name` = `Apr 2026`, `May 2026`, `Jun 2026`. `trading_days` = `count(DISTINCT trade_dt)` per
month. `is_baseline=true` for 202604 only (no prior month exists). `is_partial=true` for 202606 only.

### `phx_dm_pce_revenue_class.csv` — literal
```
class_id,class_name
RECURRING,Recurring
NON_RECURRING,Non-Recurring
```

### `phx_dm_pce_product_group.csv` — literal, 25 rows, copy exactly
```
group_id,group_name,display_prefix,class_id,sort_order,is_aggregated
managed_accounts,Managed Accounts,,RECURRING,1,true
managed_uma,Managed – Unified Managed Accounts,,RECURRING,2,false
trails_mutual_funds,Trails – Mutual Funds,,RECURRING,3,false
trails_life_annuities,Trails – Life & Annuities,,RECURRING,4,true
cash_mgmt_mmkt,Cash Management – Money Market Funds,,RECURRING,5,false
cash_mgmt_prdp,Cash Management – Premium Deposits,,RECURRING,6,false
referrals_sit_partnership,Referrals & Revenue Share – Situational Partnership,,RECURRING,7,false
plans_529,529 Plans,,RECURRING,8,false
donor_advised_funds,Donor Advised Funds,,RECURRING,9,false
twhs_structured,Structured Products,TWHS,NON_RECURRING,10,false
twhs_equities,Equities,TWHS,NON_RECURRING,11,false
twhs_options,Options,TWHS,NON_RECURRING,12,false
twhs_mutual_funds,Mutual Funds,TWHS,NON_RECURRING,13,false
twhs_fi_corporate,Fixed Income – Corporate Bonds,TWHS,NON_RECURRING,14,false
twhs_fi_municipal,Fixed Income – Municipal Bonds,TWHS,NON_RECURRING,15,false
twhs_fi_government,Fixed Income – Government Bonds,TWHS,NON_RECURRING,16,false
twhs_fi_other,Fixed Income – Other,TWHS,NON_RECURRING,17,false
twhs_cash_mgmt_cds,Cash Management – Brokered CDs,TWHS,NON_RECURRING,18,false
life_annuities,Life & Annuities,,NON_RECURRING,19,true
alternative_investments,Alternative Investments,,NON_RECURRING,20,false
defined_contribution_advisory,Defined Contribution Advisory,,NON_RECURRING,21,false
lending_sbl,Lending – Security Based Lending,,NON_RECURRING,22,false
lending_margin,Lending – Margin,,NON_RECURRING,23,false
referrals_everyday_401k,Referrals & Revenue Share – Everyday 401K,,NON_RECURRING,24,false
unmapped,Unmapped Products,,NON_RECURRING,99,false
```

### `phx_dm_pce_product.csv`
```
product_id,product_cd,product_sub_cd,product_name,sor,file_key,group_id,grid_type
```
From `pcr.product_hierarchy` where `grid_type = 'PRODUCT_TYPE'`.
`product_id = product_code || '|' || sub_product_code`. `product_name` = `level_two_product`.
`sor` and `file_key` — use `level_one_product` and empty string if no such column exists.

**Group mapping**, by `product_cd` except two sub-code splits:
```
OISC, OIS1, JPMC, MAP     -> managed_accounts
UMA                       -> managed_uma
ATMF                      -> trails_mutual_funds
ITMF, ADVA                -> trails_life_annuities
MMKT                      -> cash_mgmt_mmkt
PRDP                      -> cash_mgmt_prdp
PCS                       -> referrals_sit_partnership
529T                      -> plans_529
DAF                       -> donor_advised_funds
STRT                      -> twhs_structured
MUFD                      -> twhs_mutual_funds
FCXX                      -> twhs_fi_corporate
FMXX                      -> twhs_fi_municipal
FGXX                      -> twhs_fi_government
FCOT                      -> twhs_fi_other
FCCD                      -> twhs_cash_mgmt_cds
FIX, VARI, LIFE           -> life_annuities
ALTI                      -> alternative_investments
DCCR                      -> defined_contribution_advisory
EDK                       -> referrals_everyday_401k
ELIS + sub_cd EQ          -> twhs_equities
ELIS + sub_cd OP          -> twhs_options
LEND + sub_cd SBL         -> lending_sbl
LEND + sub_cd MGN         -> lending_margin
anything else             -> unmapped
```
**Print every product that lands in `unmapped`, with its row count.** Unmapped products are kept and
displayed, never dropped.

### `phx_dm_pce_advisor.csv`
```
advisor_sid,rep_code,advisor_name,branch_cd,employee_id,in_cohort
```
`fpic_prm_rr_tb.standard_id` → `advisor_sid`, `prm_rr_no` → `rep_code`, `cwm_branch_cd` →
`branch_cd`. LEFT JOIN `fpic_employee_tb` on `em_standard_id = standard_id` for `em_name_txt` →
`advisor_name`. **A blank name stays blank — never invent one.**
Include the 20 cohort advisors with `in_cohort=true`, **plus** every transfer counterparty advisor
appearing in the transfer file, with `in_cohort=false`.

### `phx_dm_pce_account.csv`
```
acct_key,account_no_raw,account_class_cd,account_class_nm,account_lob_cd,account_purpose_cd,managed_platform_cd,service_channel_cd,account_open_dt,is_managed,opened_in_scope,primary_eci_id
```
From `fpic_acct_tb_pm`, restricted to accounts with in-scope cohort trades.
`account_open_dt` is TEXT formatted `MM/DD/YYYY HH:MI:SS AM` and may be blank —
`to_timestamp(NULLIF(trim(account_open_dt),''), 'MM/DD/YYYY HH12:MI:SS AM')`, empty string on
failure.
`is_managed` = `managed_platform_cd IS NOT NULL AND trim(managed_platform_cd) <> ''`.
`opened_in_scope` = parsed open date within Apr–Jun 2026.
`primary_eci_id` = `party_primary_eci`.
**Do not extract `financial_advisor_cd`.** This table is a current snapshot with no date column;
using it for historical attribution mis-assigns any account that has since moved.

### `phx_dm_pce_household.csv`
```
eci_id,account_count
```
Distinct `party_eci_id` from `fpic_acct_eci_rel_tb_pm` for cohort accounts, **all relationship
codes**. `account_count` = distinct accounts per ECI.

### `phx_dm_pce_account_eci_rel.csv`
```
rel_id,acct_key,eci_id,enterprise_relationship_code,party_role_name,client_employee_ind,is_owner_role
```
`rel_id = acct_key || '|' || eci_id || '|' || enterprise_relationship_code`.
**Load every row, all codes**, including 802 Beneficiary (~7.5M firmwide, but only cohort accounts
here). `is_owner_role = enterprise_relationship_code IN ('001','151','201')`.

### `phx_dm_pce_account_eci_map.csv`
```
map_id,acct_src_key,acct_src_raw,wm_src_sys_cd,eci_id,bus_dt,new_exst_adv_clnt_in
```
From `fpic_acct_eci_map_tb`. **Latest `bus_dt` per `(wm_src_sys_cd, wm_acct_src_nb)` only** — it is
a daily snapshot. `bus_dt` is varchar; cast it.
`map_id = bus_dt || '|' || wm_src_sys_cd || '|' || acct_src_key`.

### `phx_dm_pce_rpg.csv`
```
rpg_id,account_count
```
Distinct non-blank `rpg` from the scoped cohort trades. `account_count` = distinct accounts per RPG.

### `phx_dm_pce_team_agreement.csv`
```
agreement_key,agreement_id,team_rep_cd,agreement_type,status_cd,prm_advisor_sid,prm_share_pct,sec_advisor_sid,sec_share_pct,start_ts,end_ts
```
`agreement_key = agreement_id||'|'||team_rep_cd||'|'||prm_standard_id||'|'||sec_standard_id||'|'||to_char(start_ts,'YYYYMMDD')` — the full source primary key, or rows collide.
Filter to agreements touching a cohort advisor and overlapping the window. Shares stay as fractions
(0.0–1.0) — do not multiply by 100.

### `phx_dm_pce_revenue_transaction.csv` — the largest file
```
txn_id,trade_ref_no,split_seq_no,advisor_sid,acct_key,product_id,month_id,trade_dt,proc_dt,days_to_process,credited_amt,non_credited_amt,pre_split_amt,split_pct,reason_cd,is_credited,standard_rate_bps,client_rate_bps,discount_amt,eff_disc_pct,grid_reduction,rpg,concession_type,file_key,trade_description
```
From `fpic_daily_trade_details_tb_prod`, cohort advisors, in-scope `trade_dt`.
`txn_id = trade_ref_no || '|' || split_seq_no || '|' || advisor_sid`.
`product_id = product_cd || '|' || product_sub_cd`.
`days_to_process` = `proc_dt - trade_dt` in whole days.
`pre_split_amt` = `pre_split_credited_amt`.
Apply the credited-revenue rules from §3.

### `phx_dm_pce_monthly_revenue.csv` — derived from the transaction file, do not re-query
```
mr_id,advisor_sid,month_id,product_id,group_id,class_id,credited_amt,non_credited_amt,txn_count,distinct_accounts
```
Group by `(advisor_sid, month_id, product_id)`.
`mr_id = advisor_sid || '|' || month_id || '|' || product_id`.
`group_id` and `class_id` from the product mapping.

### `phx_dm_pce_account_month.csv`
```
am_id,acct_key,advisor_sid,month_id,end_balance,credited_amt,txn_count,is_zero_balance,present_prior_month
```
`am_id = acct_key || '|' || advisor_sid || '|' || month_id`.
`end_balance` from `fpic_monthly_acct_balance_tb_april/_may/_june` (report the actual column names
you found in phase 0); `0` when the account is absent.
`credited_amt` and `txn_count` from the transaction file.
`is_zero_balance = (end_balance = 0)`.
`present_prior_month` — **false for every 202604 row** (April is the baseline month); otherwise true
when the same `(acct_key, advisor_sid)` exists in the previous month.

### `phx_dm_pce_account_transfer.csv`
```
transfer_id,acct_key,from_advisor_sid,to_advisor_sid,from_rr,to_rr,transfer_ts,month_id,is_intra_team,occd_cd
```
From `fpic_rr_changes_from_nacs_logs`, in-scope `transfer_ts`, touching a cohort account or advisor.
`transfer_id = occd_cd||'|'||acct_key||'|'||from_rr||'|'||seq_no||'|'||to_char(transfer_ts,'YYYYMMDDHH24MISS')`.
`from_advisor_sid = from_mem_sid`, `to_advisor_sid = to_mem_sid`.
`month_id = to_char(transfer_ts,'YYYYMM')`.
`is_intra_team = (from_rr = to_rr)`.

### `phx_dm_pce_advisor_flow_month.csv`
```
afm_id,advisor_sid,month_id,flow_product_cd,flow_product_desc,comp_group_type,total_inflows,total_outflows,total_net_flows,credited_flows,departed_advisor_sid,departed_advisor_excl_am,lob_trfr_excl_am,oi_pa_referral_cap_adj_am,large_flow_cap_adj_am,forced_closure_excl_am
```
From `fpic_daily_adv_flows_tb_pm`, aggregated by `to_char(bus_dt,'YYYYMM')` and
`cwm_flow_comp_prod_cd`.
`afm_id = advisor_sid || '|' || month_id || '|' || flow_product_cd`.
Resolve `advisor_sid` from `pri_rep_cd` or `rep_wrkr_sid` via `fpic_prm_rr_tb` → `standard_id`.
**Flatten the `other_attributes` JSONB** into the named columns:
`other_attributes->>'departed_advisor_sid'`, `->>'departed_advisor_excl_am'`,
`->>'lob_trfr_excl_am'`, `->>'oi_pa_referral_cap_adj_am'`, `->>'large_flow_cap_adj_am'`,
`->>'forced_closure_excl_am'` — `0` or empty where absent.
Expect April and May only.

---

## 5 · Phase 3 — Edge files (27)

Every edge file has exactly two columns: `from_id,to_id`. All are **derived from the vertex files
already written** — no further SQL.

| File | from_id | to_id |
|---|---|---|
| `phx_dm_pce_product_in_group` | product.product_id | product.group_id |
| `phx_dm_pce_group_in_class` | product_group.group_id | product_group.class_id |
| `phx_dm_pce_txn_by_advisor` | txn.txn_id | txn.advisor_sid |
| `phx_dm_pce_txn_for_account` | txn.txn_id | txn.acct_key |
| `phx_dm_pce_txn_of_product` | txn.txn_id | txn.product_id |
| `phx_dm_pce_txn_in_month` | txn.txn_id | txn.month_id |
| `phx_dm_pce_txn_in_rpg` | txn.txn_id | txn.rpg *(skip blank rpg)* |
| `phx_dm_pce_mr_by_advisor` | mr.mr_id | mr.advisor_sid |
| `phx_dm_pce_mr_in_month` | mr.mr_id | mr.month_id |
| `phx_dm_pce_mr_of_product` | mr.mr_id | mr.product_id |
| `phx_dm_pce_mr_in_group` | mr.mr_id | mr.group_id |
| `phx_dm_pce_am_for_account` | am.am_id | am.acct_key |
| `phx_dm_pce_am_by_advisor` | am.am_id | am.advisor_sid |
| `phx_dm_pce_am_in_month` | am.am_id | am.month_id |
| `phx_dm_pce_account_in_household` | account.acct_key | account.primary_eci_id *(skip blanks)* |
| `phx_dm_pce_account_in_rpg` | account.acct_key | rpg_id *(distinct pairs, via transactions)* |
| `phx_dm_pce_rel_of_account` | rel.rel_id | rel.acct_key |
| `phx_dm_pce_rel_to_household` | rel.rel_id | rel.eci_id |
| `phx_dm_pce_map_of_account` | map.map_id | map.acct_src_key *(only where the account exists)* |
| `phx_dm_pce_map_to_household` | map.map_id | map.eci_id *(skip blanks)* |
| `phx_dm_pce_transfer_of_account` | transfer.transfer_id | transfer.acct_key |
| `phx_dm_pce_transfer_from` | transfer.transfer_id | transfer.from_advisor_sid |
| `phx_dm_pce_transfer_to` | transfer.transfer_id | transfer.to_advisor_sid |
| `phx_dm_pce_team_primary` | team.agreement_key | team.prm_advisor_sid |
| `phx_dm_pce_team_secondary` | team.agreement_key | team.sec_advisor_sid |
| `phx_dm_pce_flow_by_advisor` | flow.afm_id | flow.advisor_sid |
| `phx_dm_pce_flow_in_month` | flow.afm_id | flow.month_id |

**Referential integrity:** every `to_id` must exist as a primary key in its target vertex file.
Drop edges whose target is missing and **print the dropped count per file**. A silently dropped
edge is how an entire product disappears from a dashboard with no error anywhere.

---

## 6 · Phase 4 — Manifest and validation

`out/manifest.json`:
```json
{"generated_at":"2026-08-11T12:00:00Z",
 "scope":{"from":"2026-04-01","to":"2026-07-01","advisor_count":20},
 "entities":[{"name":"phx_dm_pce_revenue_transaction","kind":"vertex",
              "file":"vertices/phx_dm_pce_revenue_transaction.csv","row_count":58432}]}
```

Then print every line of this report:

```
 1. row count per file (43 files)
 2. primary key uniqueness per vertex file — 0 duplicates required
 3. acct_key values with leading zeros — must be 0
 4. reason_cd empty strings — must be 0 (blank becomes '__NONE__')
 5. rows where reason_cd != '__NONE__' AND credited_amt != 0 — must be 0
 6. product_ids not in the mapping — list them with row counts
 7. monthly_revenue totals vs an independent re-sum of the transaction file — must match
 8. dropped edges per file (referential integrity)
 9. scenario coverage:
      accounts with fee reduction >10%, and how many of those have a recorded grid_reduction
      transfers in / transfers out
      accounts opened in scope
      accounts zeroed between months
      team agreements
      advisors with flows, and the maximum annual NNM
10. per-month credited_amt and txn_count for 202604 / 202605 / 202606
11. trading days per month
```

**Sanity anchor for line 10.** A published reference figure implies roughly $363M per month across
10,899 advisors — about $33k per advisor per month. A 20-advisor cohort selected for high revenue
should land in the high hundreds of thousands to low millions per month. An order of magnitude out
almost certainly means either the `proc_dt` scope bounds are wrong (Round 5: `proc_dt` is the correct basis), or the team-agreement join
fanned out and multiplied revenue.

**Do not proceed past a failing validation line. Report it and stop.**

---

## 7 · Reporting

Keep output compact — it will be read and possibly screenshotted. No preamble, no plan narration,
no offers to do more. If a query fails, say `FAILED: <one-line reason>`. **Never estimate a number
you did not query, and never substitute a different table or column for one that is missing.**
