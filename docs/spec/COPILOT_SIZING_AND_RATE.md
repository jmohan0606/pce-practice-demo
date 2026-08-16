# Sizing and Rate Measurement — Apr–Jul 2026 Load

Two independent things. **Part A** is row counts from PostgreSQL. **Part B** measures the actual
ingestion rate into live TigerGraph, because we have never measured it and any estimate without it
is a guess.

## OUTPUT RULES

1. Output ONLY the filled templates at the bottom. No preamble, no plan, no checklist, no summary.
2. Keep it under 50 lines — this will be photographed.
3. A query that fails gets `FAILED: <one-line reason>`. **Never estimate a number you did not
   measure.** `NOT RUN` if you skipped it.
4. If a column or table does not exist, write `NO SUCH COLUMN` / `NO SUCH TABLE` and list the
   closest actual names. Do not substitute.

Raise the timeout first: `SET statement_timeout = '900s';`

---

# PART A — Row counts, Apr–Jul 2026

Scope everywhere: `>= DATE '2026-04-01' AND < DATE '2026-08-01'`.

```sql
-- A1 trades — the largest table
SELECT count(*) AS rows,
       count(DISTINCT advisor_sid)  AS advisors,
       count(DISTINCT account_no)   AS accounts,
       count(DISTINCT rpg)          AS rpgs,
       min(trade_dt), max(trade_dt),
       count(DISTINCT date_trunc('month', trade_dt)) AS months
FROM pcr.fpic_daily_trade_details_tb_prod
WHERE trade_dt >= DATE '2026-04-01' AND trade_dt < DATE '2026-08-01';

-- A2 trades per month, to see if July is complete
SELECT to_char(trade_dt,'YYYY-MM') AS mth, count(*) AS rows,
       count(DISTINCT trade_dt) AS distinct_days
FROM pcr.fpic_daily_trade_details_tb_prod
WHERE trade_dt >= DATE '2026-04-01' AND trade_dt < DATE '2026-08-01'
GROUP BY 1 ORDER BY 1;

-- A3 advisor flows — multi-million, feeds NNM and net flows
SELECT to_char(bus_dt,'YYYY-MM') AS mth, count(*) AS rows,
       count(DISTINCT pri_rep_cd) AS reps,
       count(DISTINCT wm_acct_src_nb) AS accounts
FROM pcr.fpic_daily_adv_flows_tb_pm
WHERE bus_dt >= DATE '2026-04-01' AND bus_dt < DATE '2026-08-01'
GROUP BY 1 ORDER BY 1;

-- A4 RR changes — drives inherited / transferred-out rules
SELECT to_char(transfer_ts,'YYYY-MM') AS mth, count(*) AS rows,
       count(DISTINCT account_no) AS accounts,
       count(DISTINCT from_mem_sid) AS from_advisors,
       count(DISTINCT to_mem_sid) AS to_advisors
FROM pcr.fpic_rr_changes_from_nacs_logs
WHERE transfer_ts >= DATE '2026-04-01' AND transfer_ts < DATE '2026-08-01'
GROUP BY 1 ORDER BY 1;

-- A5 monthly balances — one row per account per month
SELECT 'april' AS m, count(*) FROM pcr.fpic_monthly_acct_balance_tb_april
UNION ALL SELECT 'may',  count(*) FROM pcr.fpic_monthly_acct_balance_tb_may
UNION ALL SELECT 'june', count(*) FROM pcr.fpic_monthly_acct_balance_tb_june;
-- if a july table exists, add it; if not, say so

-- A6 accounts, ECI relationships, ECI map — restricted to in-scope accounts
WITH acct AS (
  SELECT DISTINCT ltrim(trim(account_no),'0') AS k
  FROM pcr.fpic_daily_trade_details_tb_prod
  WHERE trade_dt >= DATE '2026-04-01' AND trade_dt < DATE '2026-08-01')
SELECT (SELECT count(*) FROM pcr.fpic_acct_tb_pm a
          JOIN acct ON acct.k = ltrim(trim(a.account_number),'0'))      AS accounts,
       (SELECT count(*) FROM pcr.fpic_acct_eci_rel_tb_pm r
          JOIN acct ON acct.k = ltrim(trim(r.account_number),'0'))      AS eci_rel_rows,
       (SELECT count(DISTINCT party_eci_id) FROM pcr.fpic_acct_eci_rel_tb_pm r
          JOIN acct ON acct.k = ltrim(trim(r.account_number),'0'))      AS households;

-- A7 team agreements in the window
SELECT count(*) FROM pcr.fpic_team_agreement_tb
WHERE start_ts < TIMESTAMP '2026-08-01' AND end_ts >= TIMESTAMP '2026-04-01';

-- A8 Managed Accounts specifically — how many advisors would the drill-down list?
SELECT count(DISTINCT t.advisor_sid) AS managed_advisors,
       count(DISTINCT t.account_no)  AS managed_accounts,
       count(*)                      AS managed_rows
FROM pcr.fpic_daily_trade_details_tb_prod t
JOIN pcr.product_hierarchy p
  ON p.product_code = t.product_cd AND p.grid_type = 'PRODUCT_TYPE'
WHERE t.trade_dt >= DATE '2026-04-01' AND t.trade_dt < DATE '2026-08-01'
  AND t.product_cd IN ('OISC','OIS1','JPMC','MAP');

-- A9 job code — does it exist?
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema='pcr'
  AND table_name IN ('fpic_employee_tb','fpic_prm_rr_tb')
ORDER BY table_name, ordinal_position;
```

---

# PART B — Measure the real ingestion rate into TigerGraph

**This is the number that matters and we have never measured it.** Everything so far has been the
local store in a Codespace; the client environment writes over RESTPP or pyTigerGraph across a
network, and per-batch latency dominates.

**Do not estimate. Run it.**

Write `scripts/measure_ingest_rate.py` that:

1. Connects to the client's TigerGraph the same way the app's ingestion does
   (`app/ingestion/tigergraph_upsert.py`) — same client, same batching, same auth
2. Generates **synthetic rows matching `phx_dm_pce_revenue_transaction`'s real column set**, so
   payload size is realistic. Do not use a trivial 3-column vertex — payload size drives the rate.
3. Upserts in batches at three sizes: **500, 1000, 5000**
4. For each size, upserts **20 batches** and reports per-batch wall time: min, median, p95, max
5. Cleans up afterwards (`DELETE` the synthetic vertices), or writes to a throwaway vertex type
6. Prints rows/second at each batch size

Then extrapolate honestly: `total_rows / measured_rows_per_second`, stated as a range from the p95
rather than the median, and add 20% for orchestration, validation and retries.

Also report:
- round-trip latency of a single trivial RESTPP call, 10 samples
- whether the connection is direct or through a proxy/NLB
- whether `pyTigerGraph` or RESTPP is the tier actually serving

---

## RETURN EXACTLY THIS

```
=== A · ROW COUNTS Apr–Jul 2026 ===
A1 trades: rows=        advisors=      accounts=       rpgs=      months=
   min_dt=            max_dt=
A2 by month:  2026-04 rows=      days=    | 2026-05 rows=      days=
              2026-06 rows=      days=    | 2026-07 rows=      days=
A3 flows:     2026-04 rows=      | 05 rows=      | 06 rows=      | 07 rows=
              reps=        accounts=
A4 rr_changes: 04=       05=       06=       07=       accounts=      advisors=
A5 balances:  april=        may=         june=        july=
A6 accounts=        eci_rel_rows=        households=
A7 team_agreements=
A8 managed: advisors=       accounts=        rows=
A9 job code column:  <name + table, or NONE FOUND>

=== B · MEASURED INGESTION RATE (live TigerGraph) ===
single RESTPP round trip: min=    ms  median=    ms  p95=    ms
connection path: direct | NLB | proxy        serving tier: pyTigerGraph | RESTPP
batch 500:   median=   s/batch  p95=   s   -> rows/sec=
batch 1000:  median=   s/batch  p95=   s   -> rows/sec=
batch 5000:  median=   s/batch  p95=   s   -> rows/sec=
best batch size:
projected total rows to load (from Part A):
projected wall time at p95 + 20% overhead:        hours
```
