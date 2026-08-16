# Copilot Task — Sizing (Part A) and Ingestion Rate (Part B)

You have no prior context. Everything you need is in this document. Run Part A
BEFORE any schema install or extraction — chunk sizing and the load-window
projection depend on its numbers. Part B runs later, after the TigerGraph
schema is installed (CLIENT_ENV_RUNBOOK.md Phase 2 tells you when).

### Database (Part A)

```
Host    nlb1b016e39-glbdep-v1-71d8d3fdc76fc824.elb.us-east-1.amazonaws.com
Port    6160
DB      fpicdb
User    fpicdbAuroraAppAdmin
Schema  pcr
Auth    AWS IAM token. On PAM/auth errors the token expired:
        run `aws sts get-caller-identity`, refresh SSO if it fails, retry.
```

Always run first:
```sql
SET statement_timeout = '600s';
```

---

## Part A — row counts (pure SQL, no TigerGraph needed)

Why: a single query over four months of `fpic_daily_trade_details_tb_prod`
could be 3M rows or 15M+. The extraction chunk plan (month × advisor batch)
and the projected load window both hinge on which it is. **Count first, never
assume.**

Run each query and paste the results back verbatim.

```sql
-- A1. transaction rows per month in scope (drives extract_chunked chunk sizing)
SELECT to_char(trade_dt, 'YYYYMM') AS month_id, count(*) AS txn_rows
FROM   pcr.fpic_daily_trade_details_tb_prod
WHERE  trade_dt >= DATE '2026-04-01' AND trade_dt < DATE '2026-08-01'
GROUP  BY 1 ORDER BY 1;

-- A2. distinct advisors with in-scope trades (drives the advisor batch count)
SELECT count(DISTINCT advisor_sid) AS advisors_with_trades
FROM   pcr.fpic_daily_trade_details_tb_prod
WHERE  trade_dt >= DATE '2026-04-01' AND trade_dt < DATE '2026-08-01';

-- A3. the advisor list itself — save as data/real/cohort.txt (one sid per
-- line, no header) for extract_chunked.py --advisors-file
SELECT DISTINCT advisor_sid
FROM   pcr.fpic_daily_trade_details_tb_prod
WHERE  trade_dt >= DATE '2026-04-01' AND trade_dt < DATE '2026-08-01'
ORDER  BY 1;

-- A4. row counts of every other in-scope table (small tables, one query each)
SELECT 'fpic_prm_rr_tb' AS tbl, count(*) FROM pcr.fpic_prm_rr_tb
UNION ALL SELECT 'fpic_employee_tb', count(*) FROM pcr.fpic_employee_tb
UNION ALL SELECT 'fpic_acct_tb_pm', count(*) FROM pcr.fpic_acct_tb_pm
UNION ALL SELECT 'fpic_rr_changes_from_nacs_logs', count(*) FROM pcr.fpic_rr_changes_from_nacs_logs
UNION ALL SELECT 'fpic_acct_eci_rel_tb_pm', count(*) FROM pcr.fpic_acct_eci_rel_tb_pm
UNION ALL SELECT 'fpic_acct_eci_map_tb', count(*) FROM pcr.fpic_acct_eci_map_tb
UNION ALL SELECT 'fpic_team_agreement_tb', count(*) FROM pcr.fpic_team_agreement_tb
UNION ALL SELECT 'fpic_daily_adv_flows_tb_pm', count(*) FROM pcr.fpic_daily_adv_flows_tb_pm;

-- A5. monthly balance tables (they are per-month tables)
SELECT 'april' AS m, count(*) FROM pcr.fpic_monthly_acct_balance_tb_april
UNION ALL SELECT 'may', count(*) FROM pcr.fpic_monthly_acct_balance_tb_may
UNION ALL SELECT 'june', count(*) FROM pcr.fpic_monthly_acct_balance_tb_june;
```

**How to read Part A:** A1 sets expectations per transaction chunk — with B
advisors per batch (default 200) and A advisors total, each month splits into
ceil(A/200) chunks averaging `txn_rows × 200 / A` rows. If any single chunk
projects above ~2M rows, lower `--batch-size` (100, then 50) until it does
not. A3's file is a required input to `extract_chunked.py`.

---

## Part B — measure the real ingestion rate (after schema install)

Why: every rate measured so far was the local store in a Codespace. The
client writes over RESTPP across a network where per-batch latency dominates.
**Do not estimate it — measure it.**

1. Make sure the schema is installed (runbook Phase 1) and `.env` points at
   the live TigerGraph.
2. Time a bounded, representative load — the account entity (tens of
   thousands of rows, plain vertex upserts):

```bash
cd <repo> && time python3 - <<'EOF'
from app.ingestion.ingestion_service import IngestionService
from app.ingestion.models import IngestionRunRequest
import time
svc = IngestionService()
t0 = time.time()
resp = svc.run_entity_ingestion(IngestionRunRequest(entity_name="phx_dm_pce_account"))
batch = resp.batch_status
secs = time.time() - t0
print(f"status={batch.status} processed={batch.processed_records} in {secs:.1f}s "
      f"= {batch.processed_records/max(secs,0.001):,.0f} rows/s")
EOF
```

3. Repeat once for one edge entity (edges are the volume driver):
   rerun with `entity_name="phx_dm_pce_txn_by_advisor"` after the transaction
   vertices exist (or accept the vertex-rate proxy if edges are not loadable
   yet and say so).
4. Paste both rates back. **The projection:** total rows (Part A) ÷ measured
   p95 rows/s × 1.2 (20% overhead) = the load window. If that window is
   longer than an overnight run, plan the load in entity groups.
