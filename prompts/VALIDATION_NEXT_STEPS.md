# Validation Results — What To Do Next

The validator ran and worked. **4 failures. Two are benign, one is a real bug, one needs settling
before anything is loaded.**

Read section A first — it decides whether the extract is usable at all.

---

# A · The advisor count — settle this before anything else

```
PASS  V-10 sanity anchor — $14,988/advisor/month over 27,084 cohort advisors x 3 months
```

It passed the range check, but **two numbers are wrong for what we intended**:

| | Expected | Reported |
|---|---|---|
| Advisors | **5,746** | **27,084** |
| Per advisor / month | ~$33,000 | **$14,988** |

Both are explained by the same thing: **the extract may contain every advisor, not the cohort.**
Spread the same revenue across 4.7× more advisors and the per-advisor figure falls by roughly that
factor — which is close to what happened.

## A1 · Count the advisors actually in the extract

```powershell
cd C:\Users\R757680\ds\workspace\pce-practice-demo-main

python -c "
import csv, glob
csv.field_size_limit(10**9)
s = set()
for f in glob.glob('data/real/_raw/raw_txn_*_b*.csv'):
    with open(f, newline='', encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            s.add(r['advisor_sid'])
print('distinct advisors in extract:', len(s))
"
```

## A2 · Count the transaction rows per month

**This is the definitive check.** Part A measured these directly from PostgreSQL.

```powershell
foreach ($m in "202604","202605","202606") {
  $n = 0
  Get-ChildItem "data\real\_raw\raw_txn_${m}_b*.csv" | ForEach-Object {
    $n += ((Get-Content $_.FullName | Measure-Object -Line).Lines - 1)
  }
  "{0}  {1:N0}" -f $m, $n
}
```

Expected: **4,184,088 / 4,236,888 / 4,015,762** — total **12,436,738**.

## How to read the two results

| A1 | A2 | Meaning |
|---|---|---|
| **5,746** | matches | Extract is correct. V-10's advisor count comes from somewhere else — a validator bug, not a data one. Proceed |
| **27,084** | matches | The 12.4M rows are right, so **5,746 was never the real number of advisors with trades** — Part A's figure was narrower than reality. The data is fine; the expectation was wrong |
| 27,084 | **higher** than expected | The cohort filter did not apply. **Stop** — the extract has more than intended and must be redone |
| either | **lower** than expected | Rows were lost. **Stop** — nothing downstream can be trusted |

**Send me both numbers before running anything else.**

---

# B · V-4 — NNM parse error *(a real bug, small fix)*

```
FAIL  V-4  NnmParseError: ECNNM_...txt:20769: expected a D-prefixed line, got 'T20766'
```

A **trailer line**. Mainframe extracts commonly end with `T` followed by the record count — here
`T20766`, and line 20769 is consistent with header + column header + 20,766 data rows.

The parser handles `H` and `D` and treats anything else as an error.

**Fix in `scripts/parse_nnm.py`** — skip the trailer, and use its count as a check rather than
ignoring it:

- a line starting with `T` is the trailer; parse the number after it
- **assert the parsed data-row count equals the trailer count** and fail loudly if not
- anything else that is neither `H`, `D` nor `T` remains an error

That turns a crash into a verification — the file tells us how many rows it should have, so we can
confirm we read them all.

---

# C · V-5 — CRM columns *(naming, not missing data)*

```
FAIL  V-5  missing columns ['opportunity_id','eci_id','ownersid','account_record_type',
           'product_service_type','stage_name','actual_assets','anticipated_investment_dt',
           'created_dt','last_modified_dt','date_of_last_contact','days_to_close','comments']
```

**The columns exist.** The export carries Salesforce names; the contract expects ours:

| Contract expects | Export has |
|---|---|
| `eci_id` | `eci__c` |
| `ownersid` | `ownersid__c` |
| `stage_name` | `stagename` |
| `actual_assets` | `actual_assets__c` |
| `account_record_type` | `account_record_type_name__c` |
| `product_service_type` | `product_service_type__c` |
| `anticipated_investment_dt` | `anticipated_investment_date__c` |
| `date_of_last_contact` | `date_of_last_contact__c` |
| `comments` | `additional_comments__c` |
| `created_dt` | `createddate` |
| `last_modified_dt` | `lastmodifieddate` |
| `days_to_close` | `days_to_close` |
| `opportunity_id` | **check the actual header** — may be `id` or absent |

**Fix:** add a source→target column map for the CRM file in `build_real_data.py`'s contract, exactly
as `new_exst_adv_clnt_in_cyr` → `new_exst_adv_clnt_in` is already handled.

**First, print the real header** so the map is built from fact rather than my reading of a
screenshot:

```powershell
Get-Content data\real\_raw\crm_opportunities.csv -TotalCount 1
```

If `opportunity_id` has no counterpart, the row identifier needs deciding — Salesforce usually
exposes `id`.

---

# D · V-2 and V-8 — both about flows, both expected

```
FAIL  V-2  chunk files not in the checkpoint: ['raw_adv_flows_202604','raw_adv_flows_202605']
FAIL  V-8  flow chunk month mismatch missing=['202606']
```

**Neither is a data problem.**

- **V-2** — you extracted those two files manually, so the script's checkpoint has no record of them.
  The files are correct; the bookkeeping does not know about them.
- **V-8** — June has no flow rows in the source table. Two months is the complete set.

**Fix:** teach the validator that flows may be operator-supplied and that its month coverage is
whatever the source holds.

- accept flow chunk files that are present on disk but absent from the checkpoint, noting them as
  operator-supplied rather than failing
- treat the flow month set as **informational**, not required to match the transaction months —
  report which months are present rather than demanding all three

**Do not create an empty `raw_adv_flows_202606.csv`.** Fabricating a file to satisfy a check is the
one thing that must never happen here.

---

# E · The unmapped products — worth a look, not a blocker

```
PASS  V-9  2 distinct unmapped codes:  ELIS/EQS: 6,358   PCS/PCS: 169
```

Both are genuine gaps in the product mapping, and both are small.

**`ELIS/EQS`** — `ELIS` splits on sub-code into `EQ` → Equities and `OP` → Options. `EQS` is a third
sub-code nobody knew about. 6,358 rows.

**`PCS/PCS`** — `PCS` splits into `SP` → Situational Partnership and `PBR` → Private Bank Referral
(added in Round 1b). `PCS/PCS` is the bare code with itself as sub-code. 169 rows.

These load as `unmapped` and are visible in the app, so **nothing is lost**. But 6,358 rows sitting
in "Unmapped Products" on a client demo is worth ten minutes:

```sql
SELECT level_one_product, level_two_product, product_code, sub_product_code
FROM pcr.product_hierarchy
WHERE product_code IN ('ELIS','PCS');
```

That says what `EQS` actually is, and whether `PCS/PCS` is a real product or a data artefact.

---

# Order of work

1. **A1 and A2** — send me both numbers. Nothing else proceeds until the advisor count is settled
2. **B** — the NNM trailer fix
3. **C** — print the CRM header, then add the column map
4. **D** — relax the two flow checks
5. **E** — optional, the product hierarchy query
6. Re-run the validator, send the output
7. Then build and load

**Do not run `build_real_data.py` or `load_real_data.py` until the validator passes.**

---

## Also noted, for the next code round

`scripts/build_real_data.py` imports `resource`, which is **Unix-only** and breaks on Windows. Guard
the import and fall back to `psutil` for peak memory. Without it the 4 GB memory guard cannot
enforce during a 12.4M-row build.
