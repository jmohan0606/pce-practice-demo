# Copilot — Fix Two Dead CRM Columns

**Scope: two column mappings and a rebuild of three CRM files only.** Do not touch anything else in
`data/real/`. Do not re-run the full build. Do not start the graph load.

Working directory:

```powershell
cd C:\Users\R757680\ds\workspace\pce-practice-demo-main
```

---

## The problem, confirmed in the built CSV

`data/real/vertices/phx_dm_pce_opportunity.csv` has 296,731 rows, and two columns are dead:

| Column | State | Consequence |
|---|---|---|
| `eci_id` | **empty on every row** | `opportunity_for_household` produced **0 edges** — no opportunity appears in any household view |
| `days_to_close` | **`0` on every row** | `is_stalled` is `FALSE` throughout; `stalled_opportunities` returns nothing |

The build reported `CRM header: days_to_close: no source column — 0`, and the source header is
**`days_to_close__c`**.

`eci_id` is different — `CRM_COLUMN_MAP` in `scripts/build_real_data.py` **already lists `eci__c`** as
a candidate, yet the output is empty. So that one is not a missing candidate; find the actual cause.

---

## Step 1 · Read the real header first

```powershell
Get-Content data\real\_raw\crm_opportunities.csv -TotalCount 1
```

**Report it verbatim.** Every fix below must be built from this header, not from any table in this
document.

Note the exact spelling of the ECI column and the days-to-close column, including case, leading or
trailing spaces, and any BOM on the first column name.

---

## Step 2 · Fix `days_to_close`

In `scripts/build_real_data.py`, `CRM_COLUMN_MAP` currently reads:

```python
"days_to_close": ("days_to_close",),
```

Add the Salesforce spelling **as it actually appears in the header**:

```python
"days_to_close": ("days_to_close", "days_to_close__c"),
```

---

## Step 3 · Diagnose `eci_id` — do not guess

The candidate `eci__c` is already present, so one of these is true. **Determine which, and report it:**

1. The header spells it differently — trailing space, different case, or a BOM on the first column
2. `resolve_crm_header()` resolves it but the transform writes a different variable
3. The column exists in the header but is **empty in the source data**

Check 3 first, since it costs one command and would mean nothing needs fixing:

```powershell
uv run python -c "
import csv
csv.field_size_limit(10**9)
with open('data/real/_raw/crm_opportunities.csv', newline='', encoding='utf-8-sig') as fh:
    r = csv.DictReader(fh)
    hdr = r.fieldnames
    eci = [h for h in hdr if 'eci' in h.lower()]
    print('ECI-like headers:', eci)
    n = pop = 0
    for row in r:
        n += 1
        if eci and (row.get(eci[0]) or '').strip(): pop += 1
        if n >= 50000: break
    print(f'first {n} rows: {pop} populated')
"
```

**If the source column is populated but our output is empty, the bug is ours** — fix it.
**If the source column is empty, that is the answer** — report it and change nothing. An empty source
column is a client data question, not a code defect.

---

## Step 4 · Rebuild ONLY the three CRM files

Do **not** re-run `build_real_data.py` in full — the other 46 files are correct and a full rebuild
costs 90 minutes.

Rewrite only:

```
data/real/vertices/phx_dm_pce_opportunity.csv
data/real/edges/phx_dm_pce_opportunity_by_advisor.csv
data/real/edges/phx_dm_pce_opportunity_for_household.csv
```

Reuse the existing CRM transform in `build_real_data.py` — **do not write a new one.** Import the
same functions so the output is byte-identical to a full build except for the two fixed columns.

**The vertex column order must be exactly:**

```
opportunity_id, eci_id, advisor_sid, advisor_sid_raw, advisor_valid,
account_record_type, product_service_type, stage_name, stage_group,
amount, actual_assets, anticipated_investment_dt, created_dt,
last_modified_dt, date_of_last_contact, days_to_close, is_stalled,
comments, ai_read, ai_read_confidence, ai_read_evidence,
ai_read_model, data_source
```

Preserve every existing behaviour: the same in-scope filter (296,731 of 308,534 kept), the derived
`opportunity_id` as `CRM|<eci_id>|<created_dt>`, `advisor_sid_raw` with `_CWM_INVALID` kept and
`advisor_valid=false`, and `stage_group` from the same mapping.

**Then update `data/real/manifest.json`** so the `expected_rows` for those three entities match the
new files. A manifest that disagrees with a file fails the load.

---

## Step 5 · Verify — paste this output

```powershell
uv run python -c "
import csv
csv.field_size_limit(10**9)
r = list(csv.DictReader(open('data/real/vertices/phx_dm_pce_opportunity.csv', newline='', encoding='utf-8-sig')))
print('rows:', len(r), '(expect 296,731)')
print('eci_id populated:', sum(1 for x in r if x['eci_id'].strip()))
print('days_to_close non-zero:', sum(1 for x in r if (x['days_to_close'] or '0') not in ('0','')))
print('days_to_close negative:', sum(1 for x in r if (x['days_to_close'] or '0').lstrip().startswith('-')))
print('is_stalled TRUE:', sum(1 for x in r if x['is_stalled'].upper()=='TRUE'))
print('advisor_valid FALSE:', sum(1 for x in r if x['advisor_valid'].upper()=='FALSE'), '(expect 25)')
"
```

```powershell
(Get-Content data\real\edges\phx_dm_pce_opportunity_for_household.csv).Count
(Get-Content data\real\edges\phx_dm_pce_opportunity_by_advisor.csv).Count
```

### What good looks like

- **rows: 296,731** — unchanged
- **`eci_id` populated: close to 296,731** (or a reported reason if the source is empty)
- **`days_to_close` non-zero: substantial**, with **negatives present** — those are the stalled ones
- **`is_stalled` TRUE: non-zero**
- **`advisor_valid` FALSE: 25** — unchanged, proving nothing else shifted
- **`opportunity_for_household` line count: near 296,732** (rows + header), no longer 1

**If `eci_id` is still empty and step 3 showed the source populated, stop and report** — do not
work around it.

---

## Rules

1. **Do not re-run the full build.** Three files only.
2. **Do not start the graph load.** That is the next task, after this is verified.
3. **Never fabricate a value** to make a check pass. An empty source column gets reported, not filled.
4. **Never estimate a number** — every figure comes from a command that ran.
5. If anything outside these three files changes, say so explicitly.
