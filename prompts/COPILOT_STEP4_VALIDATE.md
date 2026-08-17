# Copilot — Step 4: Validate, then STOP at the Review Gate

Extraction is confirmed complete: **111 files, no gaps, no extras, no truncation.**

This step validates that data. **It does not build and does not load.** Stop after producing the
report and wait for an explicit go-ahead.

---

## Paths

Every path is relative to the repository root. Run from there:

```powershell
cd C:\Users\R757680\ds\workspace\pce-practice-demo-main
Test-Path data\real\_raw     # must return True
```

**Do not search outside the repository.** If a path is missing, report it rather than looking
elsewhere for something similarly named.

---

## Run the validator

```powershell
python scripts\validate_raw_extracts.py --raw data\real\_raw
```

Capture the **complete output**, every line.

### One thing to expect — flows has two months, not three

June has no rows in the source table; April and May are the complete set. The validator checks chunk
sequences for gaps, so it may flag `raw_adv_flows_202606` as missing.

**If it does, that is the validator working correctly — not a fault.** Report the exact message and
**do not create an empty June file** to satisfy it. Fabricating a file to make a check pass is the
one thing that must never happen here.

---

## Then produce this report

Fill every field from a command that ran. **Never estimate a number.** If something cannot be
determined, write `NOT DETERMINED` and say why.

```
=== VALIDATION REPORT ===

1 · VALIDATOR OUTPUT
<paste every line, verbatim>

2 · PER-MONTH TRANSACTION COUNTS
   Sum the data rows (excluding headers) across each month's 29 chunk files.

   202604   extracted: ______        expected: 4,184,088     match: Y/N
   202605   extracted: ______        expected: 4,236,888     match: Y/N
   202606   extracted: ______        expected: 4,015,762     match: Y/N
   TOTAL    extracted: ______        expected: 12,436,738    match: Y/N

3 · ROW COUNTS PER ENTITY  (data rows, excluding headers)
   accounts        (4 buckets)  ______   expected 2,689,176
   eci_rel         (4 buckets)  ______   expected 6,971,181
   eci_map         (4 buckets)  ______   expected 2,915,901
   balances        (3 months)   ______   expected 8,683,364
   rr_changes                   ______   expected   141,054
   advisor                      ______   expected   244,881
   team_agreement               ______   expected       138
   product_hierarchy            ______   expected        38
   adv_flows       (2 months)   ______   ~111,000 for Apr+May
   crm_opportunities            ______   source file total
   NNM  (4 .txt files)          ______   data lines, H and header excluded

4 · SANITY ANCHOR
   Total credited revenue for one month, and per advisor.
   Sum the credited amount where the reason code is blank, for 202605 only.

   202605 credited total:      $__________
   ÷ 5,746 advisors:           $__________ per advisor per month

   The published firm-wide reference implies about $33,000 per advisor per month.
   An order of magnitude out means proc_dt was used instead of trade_dt, or a join
   fanned out. Report the number either way — do not adjust anything to make it fit.

5 · UNMAPPED PRODUCTS
   Product codes present in the transaction data that the product hierarchy does
   not map. List each with its row count.

   <code|sub_code>   <rows>
   ...
   (or: none)

6 · ANY VALIDATION FAILURE
   Every V-* line that did not pass, with its exact message.
   (or: none)
```

---

## Then stop

**Do not run `build_real_data.py`. Do not run `load_real_data.py`.**

Send the report and wait for a go-ahead.

Loading takes about three hours. A problem found now costs minutes; the same problem found after the
load costs the load and the time to unpick it. Section 2 is the one that matters most — if the
per-month counts do not match, rows were lost during extraction and nothing downstream can be
trusted.

---

## Standing rules

1. All paths are repo-relative. Never search outside the repository root.
2. Never fabricate a file, a row, or a number to make a check pass.
3. Never estimate a figure — every number comes from a command that ran.
4. Report a discrepancy rather than working around it.
