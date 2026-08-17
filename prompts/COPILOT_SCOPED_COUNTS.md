# Copilot Task — Scoped Row Counts

One thing only: **how many rows actually load into TigerGraph.**

Part A gave full table sizes. Those are not what loads — the reference tables filter down to accounts
that appear in in-scope trades. This measures the real volume.

**Scope, fixed:** `trade_dt >= DATE '2026-04-01' AND trade_dt < DATE '2026-07-01'` — April, May,
June. July is excluded (2.2M rows against a ~4.1M monthly average, i.e. a partial extract).

**Cohort, fixed:** all **5,746** advisors in `data/real/cohort.txt`. No sampling.

**Already known:** transactions Apr–Jun = **12,436,738**.

---

## OUTPUT RULES

1. Output ONLY the filled template at the bottom. No preamble, no plan, no summary.
2. Under 30 lines — this will be photographed.
3. A query that fails gets `FAILED: <one-line reason>`. **Never estimate a number you did not
   measure.**
4. If a table or column does not exist, write `NO SUCH TABLE` / `NO SUCH COLUMN` and name the
   closest actual identifier. Do not substitute.

Run first: `SET statement_timeout = '900s';`

---

## The queries

```sql
-- The in-scope account set — everything below reuses it.
CREATE TEMP TABLE scoped_acct AS
SELECT DISTINCT ltrim(trim(account_no),'0') AS k
FROM pcr.fpic_daily_trade_details_tb_prod
WHERE trade_dt >= DATE '2026-04-01' AND trade_dt < DATE '2026-07-01';

SELECT count(*) AS scoped_accounts FROM scoped_acct;

-- C1 accounts
SELECT count(*) FROM pcr.fpic_acct_tb_pm a
JOIN scoped_acct s ON s.k = ltrim(trim(a.account_number),'0');

-- C2 ECI relationships — ALL relationship codes, no role filter at extraction
SELECT count(*) FROM pcr.fpic_acct_eci_rel_tb_pm r
JOIN scoped_acct s ON s.k = ltrim(trim(r.account_number),'0');

-- C3 ECI map — latest bus_dt per (wm_src_sys_cd, wm_acct_src_nb) ONLY
SELECT count(*) FROM (
  SELECT ROW_NUMBER() OVER (PARTITION BY m.wm_src_sys_cd, m.wm_acct_src_nb
                            ORDER BY m.bus_dt DESC) rn
  FROM pcr.fpic_acct_eci_map_tb m
  JOIN scoped_acct s ON s.k = ltrim(trim(m.wm_acct_src_nb),'0')) t
WHERE rn = 1;

-- C4 advisor flows in scope
SELECT count(*) FROM pcr.fpic_daily_adv_flows_tb_pm
WHERE bus_dt >= DATE '2026-04-01' AND bus_dt < DATE '2026-07-01';

-- C5 RR changes in scope
SELECT count(*) FROM pcr.fpic_rr_changes_from_nacs_logs
WHERE transfer_ts >= DATE '2026-04-01' AND transfer_ts < DATE '2026-07-01';

-- C6 monthly balances, scoped
SELECT 'april' m, count(*) FROM pcr.fpic_monthly_acct_balance_tb_april b
  JOIN scoped_acct s ON s.k = ltrim(trim(b.acct_id),'0')
UNION ALL SELECT 'may', count(*) FROM pcr.fpic_monthly_acct_balance_tb_may b
  JOIN scoped_acct s ON s.k = ltrim(trim(b.acct_id),'0')
UNION ALL SELECT 'june', count(*) FROM pcr.fpic_monthly_acct_balance_tb_june b
  JOIN scoped_acct s ON s.k = ltrim(trim(b.acct_id),'0');

-- C7 advisors and team agreements
SELECT count(*) FROM pcr.fpic_prm_rr_tb;
SELECT count(*) FROM pcr.fpic_team_agreement_tb
WHERE start_ts < TIMESTAMP '2026-07-01' AND end_ts >= TIMESTAMP '2026-04-01';

-- C8 products
SELECT count(*) FROM pcr.product_hierarchy WHERE grid_type = 'PRODUCT_TYPE';
```

---

## RETURN EXACTLY THIS

```
=== SCOPED ROW COUNTS · Apr–Jun 2026 · 5,746 advisors ===
scoped accounts:              (   % of 9,949,639 firm-wide)
C1 accounts:                  (full 9,949,639)
C2 eci_rel:                   (full 20,459,642)
C3 eci_map latest-only:       (full 12,654,220)
C4 adv_flows in scope:        (full 19,482,441)
C5 rr_changes in scope:       (full 2,795,350)
C6 balances  april=      may=       june=        (full ~10.5M each)
C7 advisors=        team_agreements=
C8 products=
TRANSACTIONS (known):  12,436,738
TOTAL ROWS TO LOAD:
```
