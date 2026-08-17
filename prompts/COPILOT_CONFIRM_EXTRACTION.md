# Copilot — Confirm Extraction Completeness

**Stop all extraction work. Do not start any new chunk.** This is a verification pass only.

---

## ⚠ Paths — read this first

**Every path below is relative to the repository root.** Run every command from there:

```powershell
cd C:\Users\R757680\ds\workspace\pce-practice-demo
```

*(Substitute your actual repo path if it differs — confirm with `git rev-parse --show-toplevel`.)*

- `data/real/_raw/` means **`<repo>/data/real/_raw/`** — the folder inside this project
- **Do not search the C: drive.** Do not use `dir /s`, `Get-ChildItem -Recurse` from a drive root, or
  any filesystem-wide search. There is exactly one `data` folder that matters and it is in the repo
- If a path does not exist where expected, **report that** rather than searching elsewhere for
  something similarly named

Confirm you are in the right place before anything else:

```powershell
git rev-parse --show-toplevel
Test-Path data\real\_raw
```

The second must return `True`.

---

## Flows is done — do not touch it

`raw_adv_flows` is **handled and closed**. Do not extract, retry, diagnose or split it.

- **April and May** were extracted manually and are already in `data/real/_raw/`
- **June has no data in the source table** — confirmed directly. Two files is the complete set, not
  a partial one

Any remaining flows entry in the checkpoint should be treated as satisfied. If anything still
attempts flows, stop it.

---

## What to report

### 1 · The checkpoint

```powershell
# from the repo root — the checkpoint is at <repo>/data/real/_raw/extract_checkpoint.json
python -c "import json; d=json.load(open('data/real/_raw/extract_checkpoint.json')); c=d.get('completed', d); print(len(c)); [print(' ', k) for k in sorted(c)]"
```

Report the **count** and the **full list**.

### 2 · The files on disk

```powershell
# from the repo root
(Get-ChildItem data\real\_raw\*.csv).Count
Get-ChildItem data\real\_raw\*.csv | Select-Object -ExpandProperty Name | Sort-Object
```

There are **115 CSV files**, two of which are the manually-extracted flows. Report the full list.

### 3 · Reconcile plan against disk — the important part

For each expected chunk family, report **expected vs present**:

| Family | Expected | Present |
|---|---|---|
| `raw_txn_<month>_b<NNN>` | 87 (3 months × 29 advisor batches) | ? |
| `raw_balance_<month>` | 3 | ? |
| `raw_account_b<NNN>` | 4 | ? |
| `raw_acct_eci_rel_b<NNN>` | 4 | ? |
| `raw_acct_eci_map_b<NNN>` | 4 | ? |
| `raw_advisor`, `raw_advisor_flags`, `raw_product_hierarchy`, `raw_rr_changes`, `raw_month_meta`, `raw_team_agreement` | 1 each | ? |
| `raw_adv_flows_<month>` | **2 — April and May only** | ? |
| `crm_opportunities.csv` | 1 | ? |

**Name every gap explicitly.** A missing bucket in a sequence (b001, b002, b004) is a lost chunk, not
a small extract, and it must be reported by name.

If the file count exceeds the plan, name the extras — duplicates, differently-named files, or
leftovers from an earlier attempt all matter.

### 4 · ⚠ Truncated files — check this carefully

**The extraction process was stopped mid-run**, so the file it was writing may be incomplete. A
truncated CSV can still pass a row count and will silently corrupt everything downstream.

For every CSV:

- confirm the **last line is complete** — a full row, correctly terminated, not cut mid-field
- confirm the **column count on the last line matches the header**
- report any file that fails, by name

The most likely candidate is whichever chunk was in flight when the process was stopped. Check the
most recently modified files first:

```powershell
Get-ChildItem data\real\_raw\*.csv | Sort-Object LastWriteTime -Descending | Select-Object -First 5 Name, Length, LastWriteTime
```

**A truncated file must be deleted and re-extracted**, not repaired.

### 5 · The flat files

```powershell
Get-ChildItem data\real\_raw\*NNM*.txt
Test-Path data\real\_raw\crm_opportunities.csv
```

All four NNM categories — ECNNM, NBNNM, YINNM, FSNNM — must be present. The build refuses to start
otherwise, deliberately: three of four would load silently incomplete.

---

## Then say plainly

**Is the extraction complete?** One of:

- **COMPLETE** — every expected chunk present, no truncation, flats in place. Ready for validation
- **INCOMPLETE** — and name exactly which chunks are missing or truncated, and nothing else

**Do not re-extract anything in this pass.** Report first; the missing set will be decided from that
report.

**Never estimate a count.** Every figure comes from a command that ran.

---

## Standing rules for this repository

These apply to every task, not just this one:

1. **All paths are repo-relative.** `data/`, `scripts/`, `docs/` mean the folders inside this
   project. Never search outside the repository root.
2. **Never run a filesystem-wide search.** If something is not where it should be, say so and stop.
   A file found elsewhere on the drive is not the file this project uses — that is exactly how a
   stale `raw_revenue_transaction.sql` was executed for three diagnostic cycles.
3. **Confirm the working directory before running anything** — `git rev-parse --show-toplevel`.
4. **Report a missing path rather than looking for a substitute.** A similarly-named folder is not
   the same folder.
5. **Never estimate a number.** Every figure reported comes from a command that ran.
