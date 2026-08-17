# Copilot — Unblock `raw_adv_flows` and Continue

**Stop retrying `raw_adv_flows`.** It is not a token problem. The query cannot finish in 900 seconds
and retrying with a fresh token will fail identically every time.

---

## 1 · Continue the other 102 chunks now — do not wait

`raw_adv_flows` is **one chunk of 109**. The checkpoint already records the six completed. Skip it
and keep going:

```bash
python3 scripts/extract_chunked.py --months 202604,202605,202606 \
  --advisors-file data/real/cohort.txt --out data/real/_raw \
  --skip raw_adv_flows.sql
```

If `--skip` does not exist, add it — a flag that excludes named chunks from the plan while leaving
their checkpoint entries untouched. **Do not pass `--restart`.**

The remaining 102 chunks are unaffected by this problem. Get them extracted while the flows query is
fixed.

---

## 2 · Why it fails

```sql
JOIN pcr.fpic_prm_rr_tb r
  ON r.standard_id = f.rep_wrkr_sid OR r.prm_rr_no = f.pri_rep_cd
```

**An `OR` in a join condition cannot use an index.** PostgreSQL falls back to a nested-loop or hash
join across 19.4M flow rows × 244,881 advisor rows, with five JSONB extractions and nine aggregates
per row on top. Raising the timeout will not help — the plan is wrong, not slow.

The `OR` exists because we did not know which column reliably identifies the advisor. Settle that and
the join becomes a single indexed equality.

---

## 3 · Run this diagnostic — it decides the fix

```sql
SET statement_timeout = '300s';

SELECT count(*)                                                          AS total,
       count(*) FILTER (WHERE rep_wrkr_sid IS NOT NULL AND rep_wrkr_sid <> '') AS has_wrkr_sid,
       count(*) FILTER (WHERE pri_rep_cd  IS NOT NULL AND pri_rep_cd  <> '')   AS has_rep_cd,
       count(*) FILTER (WHERE (rep_wrkr_sid IS NULL OR rep_wrkr_sid = '')
                          AND (pri_rep_cd  IS NULL OR pri_rep_cd  = ''))       AS has_neither
FROM pcr.fpic_daily_adv_flows_tb_pm
WHERE bus_dt >= DATE '2026-04-01' AND bus_dt < DATE '2026-07-01';
```

**Report these four numbers.** Then:

| Result | Fix |
|---|---|
| `has_wrkr_sid` = total | Join on `r.standard_id = f.rep_wrkr_sid` only. Drop the `OR` entirely |
| `has_rep_cd` = total | Join on `r.prm_rr_no = f.pri_rep_cd` only |
| Both partial, `has_neither` = 0 | **Two separate queries UNIONed** — one per join column, each a clean indexed equality. Never an `OR` |
| `has_neither` > 0 | Those rows cannot be attributed to an advisor. Report the count; they are excluded and that exclusion is a finding, not a silent drop |

---

## 4 · Also chunk flows by month

Even with the join fixed, 19.4M rows aggregating in one statement is close to the limit. Split it
three ways, exactly as monthly balances already are:

```
raw_adv_flows_202604.csv
raw_adv_flows_202605.csv
raw_adv_flows_202606.csv
```

Roughly 6.5M input rows each, aggregating to ~55k output rows per month. `build_real_data.py`
already handles chunk families — add `raw_adv_flows_<month>.csv` alongside the balance family, with
the same sequence check and both-forms refusal.

**The aggregate is what extracts.** The 19.4M daily rows must never cross the wire; total expected
output across the three files is **166,985 rows**.

---

## 5 · Verify before rerunning

```sql
EXPLAIN (ANALYZE false)
<the corrected single-month query>;
```

If the plan still shows a nested loop over both tables, the join is still wrong. Fix it before
spending another 900 seconds finding out.

---

# General rule — when something blocks, work around it

You are running a 109-chunk extraction against a slow database on a 30-minute token. **A single
blocked chunk must never stop the other 108.**

When a step fails and a retry fails the same way:

**1 · Distinguish transient from structural.**
A token expiry, a dropped connection, a lock wait — retry. A statement timeout that recurs at the
same point with a fresh token is **structural**: the query is wrong, not unlucky. Retrying it is
wasted time.

**2 · Isolate and continue.** Skip the failing unit and keep the rest moving. Report what was
skipped. Ten minutes of unblocked progress beats an hour of retries.

**3 · Reduce the unit before reducing the scope.** A query that will not finish should be split —
by month, by bucket, by advisor batch — before anyone considers dropping data. The chunking patterns
already exist in `extract_chunked.py`; reuse them rather than inventing something.

**4 · Diagnose with a cheap query, not an expensive retry.** A `count(*)` with a short timeout, or
an `EXPLAIN`, costs seconds and tells you what a 900-second retry would not.

**5 · Never silently drop data to make something pass.** If rows cannot be extracted, **report the
count and the reason**. A silent drop produces figures that are wrong and look right — the worst
outcome available here.

**6 · Never estimate a number.** Every figure reported comes from a run.

**7 · Report rather than stall.** If a workaround is not obvious after two attempts, say what failed,
what you tried, and what you propose — and keep the unaffected work moving meanwhile.

---

## What to send back

1. The four diagnostic numbers from section 3
2. Which fix applies and the corrected join
3. Progress on the other 102 chunks — completed, remaining, any other failures

**Do not proceed to step 4 validation until all 109 chunks are extracted**, including the three
flows month chunks.
