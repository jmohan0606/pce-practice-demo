# Manual Validation — Run These Yourself

Copilot is unavailable. These are the same checks, as commands you run directly.

**Windows PowerShell.** Start every session from the repo root:

```powershell
cd C:\Users\R757680\ds\workspace\pce-practice-demo-main
Test-Path data\real\_raw      # must print True
```

Six steps. Send me the output of each — or all together at the end.

---

## Step 1 · Run the validator

```powershell
python scripts\validate_raw_extracts.py --raw data\real\_raw
```

**Send me every line**, including failures.

**Expect one thing:** June has no flow rows in the source, so the validator may flag
`raw_adv_flows_202606` as a sequence gap. That is the validator working correctly.
**Do not create an empty June file** — send me the message and I will confirm.

If it errors immediately, send the error and stop; the rest depends on it.

---

## Step 2 · Per-month transaction counts

**The most important check.** If these do not match, rows were lost and nothing downstream can be
trusted.

```powershell
foreach ($m in "202604","202605","202606") {
  $n = 0
  Get-ChildItem "data\real\_raw\raw_txn_${m}_b*.csv" | ForEach-Object {
    $n += ((Get-Content $_.FullName | Measure-Object -Line).Lines - 1)
  }
  "{0}  {1:N0}" -f $m, $n
}
```

Expected:

```
202604    4,184,088
202605    4,236,888
202606    4,015,762
```

Slow — it reads 12.4M lines. Give it a few minutes.

---

## Step 3 · Row counts per entity

```powershell
function Rows($pattern) {
  $n = 0
  Get-ChildItem $pattern -ErrorAction SilentlyContinue | ForEach-Object {
    $n += ((Get-Content $_.FullName | Measure-Object -Line).Lines - 1)
  }
  return $n
}

"accounts      {0,12:N0}  expected  2,689,176" -f (Rows "data\real\_raw\raw_account_b*.csv")
"eci_rel       {0,12:N0}  expected  6,971,181" -f (Rows "data\real\_raw\raw_acct_eci_rel_b*.csv")
"eci_map       {0,12:N0}  expected  2,915,901" -f (Rows "data\real\_raw\raw_acct_eci_map_b*.csv")
"balances      {0,12:N0}  expected  8,683,364" -f (Rows "data\real\_raw\raw_balance_*.csv")
"rr_changes    {0,12:N0}  expected    141,054" -f (Rows "data\real\_raw\raw_rr_changes.csv")
"advisor       {0,12:N0}  expected    244,881" -f (Rows "data\real\_raw\raw_advisor.csv")
"team_agree    {0,12:N0}  expected        138" -f (Rows "data\real\_raw\raw_team_agreement.csv")
"products      {0,12:N0}  expected         38" -f (Rows "data\real\_raw\raw_product_hierarchy.csv")
"adv_flows     {0,12:N0}  Apr+May only"        -f (Rows "data\real\_raw\raw_adv_flows_*.csv")
"crm           {0,12:N0}  source total"        -f (Rows "data\real\_raw\crm_opportunities.csv")
```

---

## Step 4 · The sanity anchor

**Roughly $33,000 credited revenue per advisor per month.** An order of magnitude out means
`proc_dt` was used instead of `trade_dt`, or a join fanned out.

```powershell
python -c "
import csv, glob, sys
csv.field_size_limit(10**9)
total = 0.0
for f in sorted(glob.glob('data/real/_raw/raw_txn_202605_b*.csv')):
    with open(f, newline='', encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            if (r.get('reason_cd') or '__NONE__') == '__NONE__':
                try: total += float(r.get('credited_amt') or r.get('post_split_credited_amt') or 0)
                except ValueError: pass
print(f'202605 credited total: \${total:,.2f}')
print(f'per advisor (5,746):   \${total/5746:,.2f}')
"
```

Send me both numbers **whatever they are**. Do not adjust anything to make them fit.

---

## Step 5 · Unmapped products

Product codes in the transaction data that the hierarchy does not map. These are kept and shown in
the app, never dropped — but I want to see the list.

```powershell
python -c "
import csv, glob
csv.field_size_limit(10**9)
mapped = set()
with open('data/real/_raw/raw_product_hierarchy.csv', newline='', encoding='utf-8-sig') as fh:
    for r in csv.DictReader(fh):
        mapped.add((r.get('product_code','').strip(), r.get('sub_product_code','').strip()))
seen = {}
for f in sorted(glob.glob('data/real/_raw/raw_txn_*_b*.csv')):
    with open(f, newline='', encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            k = (r.get('product_cd','').strip(), r.get('product_sub_cd','').strip())
            if k not in mapped:
                seen[k] = seen.get(k, 0) + 1
for k, n in sorted(seen.items(), key=lambda x: -x[1]):
    print(f'{k[0]:8} {k[1]:8} {n:>10,}')
print('unmapped codes:', len(seen))
"
```

Also slow — it reads every transaction file.

---

## Step 6 · Flat files

```powershell
Get-ChildItem data\real\_raw\*NNM*.txt | Select-Object Name, Length
Test-Path data\real\_raw\crm_opportunities.csv
```

All four NNM categories must be present — **ECNNM, NBNNM, YINNM, FSNNM**. The build refuses to start
otherwise, deliberately: three of four would load silently incomplete.

---

## Then stop

**Do not run `build_real_data.py` or `load_real_data.py` yet.**

Send me steps 1–6 and I will confirm before the load. Loading takes about three hours; a problem
found now costs minutes, the same problem found afterwards costs the load and the unpicking.

---

## If a step fails

| Symptom | Do this |
|---|---|
| Step 1 errors out | Send the error and stop — everything else depends on it |
| Steps 2/3 are very slow | Normal, 12.4M lines. Leave it running |
| A count is off by a little | Send it — could be a header-counting difference |
| A count is off by a lot | **Stop.** Send it before anything else |
| Sanity anchor is 10× out | **Stop.** Wrong date column or a fanned-out join |
| `field larger than field limit` | The `field_size_limit` line handles it; if it still fails, send the error |
