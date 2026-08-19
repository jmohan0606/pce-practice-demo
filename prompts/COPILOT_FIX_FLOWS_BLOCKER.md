# Copilot — Fix the Flows Blocker and Resume Extraction

**Root cause found. Do not diagnose further — apply this fix.**

---

## What was wrong

The extraction has **never reached a single transaction chunk.** It has been stuck on
`raw_adv_flows`, which is chunk 21 of 105.

**Why:** `raw_adv_flows.sql` is still listed in `SINGLE_TABLES` in `scripts/extract_chunked.py`, so
`build_plan` generates a chunk with the id **`raw_adv_flows`** — no month suffix.

The operator's two files are named `raw_adv_flows_202604.csv` and `raw_adv_flows_202605.csv`, so that
chunk id has never appeared in the checkpoint. The extractor keeps trying to produce it, and that
query is the known-slow one with a nested loop over `fpic_prm_rr_tb` (EXPLAIN cost ~15 billion). It
times out at 600s, every time.

Round 5 taught the **validator** that per-month flow files are a recognised family. It never taught
the **extractor**.

---

## Flows is complete — it must not be extracted

- **April and May** were extracted manually and are already in `data/real/_raw/`
- **June has no rows in the source table** — confirmed directly
- **Two files is the complete set**, not a partial one

Do not extract, retry, diagnose or split flows.

---

## Step 1 · Apply the fix

```powershell
uv run python -c "
import json
p='data/real/_raw/extract_checkpoint.json'
d=json.load(open(p)); c=d.setdefault('completed',{})
c['raw_adv_flows']={'rows':None,'note':'operator-supplied per-month files; June has no source data'}
json.dump(d,open(p,'w'),indent=2); print('completed:',len(c))
"
```

The key must be exactly **`raw_adv_flows`**, with no month suffix — that is the id `build_plan`
generates from `SINGLE_TABLES`. A key with a month suffix will not match and nothing will change.

---

## Step 2 · Confirm before running anything

```powershell
uv run python scripts\extract_chunked.py --months 202604,202605,202606 `
  --advisors-file data\real\cohort.txt --out data\real\_raw --dry-run
```

**Required result:** `raw_adv_flows` shows as complete, and **only `raw_txn_*` chunks are pending.**

**If flows still shows pending, STOP and report.** Do not run the extraction — it would time out on
the same chunk again.

---

## Step 3 · Run the extraction

```powershell
uv run python -u scripts\extract_chunked.py --months 202604,202605,202606 `
  --advisors-file data\real\cohort.txt --out data\real\_raw
```

### Report after the first 5 chunks — before continuing

Per-chunk wall time and row count for each of the first five.

**The previous extraction ran at about 39 seconds per chunk.**

- **In that range** → continue, and report at **28, 56 and 84** chunks
- **Materially slower** → **stop and report the timings.** Transaction chunks have never actually
  run, so this is the first real measurement of them and it matters

### The IAM token expires every 30 minutes — this is normal

Extraction stops cleanly with a checkpoint saved. Rerun the PCL login from `CONNECTION_DETAILS.md`
section 1, re-export `PCE_PG_DSN`, and rerun the **identical** command — the same `--months` list
every time, or the plan fingerprint check will refuse it.

**Never pass `--restart` or `--fresh`.** Both discard completed work.

---

## Standing rules

1. **Two identical failures = STOP and report.** Never a third attempt.
2. **Never estimate a number** — every figure comes from a command that ran.
3. **All paths repo-relative.** Never search the C: drive.
4. **Never fabricate a file or a row** to make a check pass. In particular, **do not create an empty
   `raw_adv_flows_202606.csv`.**
5. Report only at the points named above.

---

## For the next code round — not now

`raw_adv_flows.sql` should be removed from `SINGLE_TABLES` and become a per-month family like
`raw_balance_<month>`, since that is what it actually is. Otherwise this recurs on any fresh
checkpoint.
