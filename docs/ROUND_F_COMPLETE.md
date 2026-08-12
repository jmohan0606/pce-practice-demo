# Round F — COMPLETE (docs/spec/ROUND_F_SPEC.md)

All six tasks done and verified. Task 1 ran first in the main thread (0b9ef6f);
Tasks 2–5 ran as three concurrent subagents whose claims were re-verified in
the main thread before commit (Tasks 2+3 → 6e1b0b1, Task 4 → 302a939,
Task 5 → 86c1da9); Task 6 ran last in the main thread.

The client's PostgreSQL is unreachable from this Codespace, so per the
operator's instruction the Task 4 extraction scripts were built and proven
against a fabricated raw CSV set matching `RAW_CONTRACT`
(`data/real_test/_raw/`, generated deterministically by
`scripts/make_test_raw_extracts.py`).

---

## Task 6 — the 10 verification checks (actual output)

**1. v0 contains exactly 5 rules; FEE_REDUCTION_SHARING and PARTIAL_PERIOD gone**
```
5 [('NEW_ACCOUNT', 10), ('ACCOUNT_TRANSFERRED_IN', 20), ('ACCOUNT_TRANSFERRED_OUT', 20),
   ('NEW_BILLING', 25), ('LOST_ACCOUNT', 30)]
```
Only remaining references to the deleted codes are historical (docs, DECISIONS).

**2. NEW_BILLING fires on 202605 mock data, empty-with-reason on 202604**
```
NEW_BILLING 202605 matched: 17
NEW_BILLING 202604 matched: 0 | empty_reason: month 202604 is the baseline month —
    no prior month exists, so this rule returns an empty …
```

**3. NEW_BILLING does not double-count a NEW_ACCOUNT-claimed account**
Mechanism: rules may carry `exclude_matched_of: [rule_code,…]`;
`evaluate_rule_set` unions the named earlier rules' matched keys into the
later rule's `exclude_keys` (app/rules/service.py). Overlap probe — account
2997 (NEW_ACCOUNT-claimed on 202605) mutated to also satisfy NEW_BILLING's
population:
```
alone:  matched 18 | includes 2997: True
in set: matched 17 | includes 2997: False   (NEW_ACCOUNT claimed it first)
```
Natural mock data has zero overlap (a just-opened account has prior_end_balance 0).

**4. extractor finds the fee-discount sharing rule from the sample PDF with a page citation**
`GRID_SHARE_DISCOUNT_THRESHOLD_TABLE` — **COMPILED**, cite **p.3
"3 Client Fee Discounts and Grid Sharing > 3.1 The Sharing Threshold"**
(prose + rate table excerpts captured). A second variant that needs a
per-account-month effective rate went NEEDS_DATA honestly (rates exist only
per transaction). The rule now comes from the document, not the seed —
the provenance story Task 2 exists to protect.

**5. the three new provisions extract and compile**
```
EQUITY_PRODUCT_MINIMUM        COMPILED  cite p.2 §2.1 Product Minimums
  plan: monthly_revenue, class_id='EQUITY', sum(credited_amt), trigger < 25
MUTUAL_FUND_PRODUCT_MINIMUM   COMPILED  cite p.2 §2.1 Product Minimums
  plan: monthly_revenue, group_id='MUTUAL_FUND' AND 0 < credited_amt < 10
        (exception-check shape: positive revenue below the minimum flags)
SELECT_ANNIV_THRESHOLD        COMPILED  cite p.5 §6 Select Anniversary Award
  plan: monthly_revenue, sum(credited_amt) per :advisor_sid, trigger >= 1000000
        (19 rows evaluated, 0 matched — no mock advisor reaches $1MM)
```
Full extraction pass: **38 extracted, 22 COMPILED (was 15), 4 NEEDS_INPUT,
12 NEEDS_DATA** (each naming its gap).

**6. no standard-rate 115 bps outside a labelled worked example**
Sample PDF: 145 bps on p.3 as the standard; 115 bps appears only inside
"3.2 Worked Example (Illustrative Only)" which opens "the rates in it are
assumed for arithmetic and are not the standard schedule". The Round B test
PDF's worked example likewise labelled. Mock generator uses `std_bps=145.0`.
Resolution recorded in DECISIONS.md with the citations (145 = the schedule:
FAQ p.13, PCA p.3, SAG p.4; 115 = worked example only: FAQ p.15).

**7. build_real_data.py runs end to end on fabricated raw CSVs, all 12 validations**
```
ALL 12 VALIDATIONS PASSED
wrote …: 46 files, 3481 vertex rows, 12455 edge rows, manifest.json
202604: credited $640,455.61  txns 552
202605: credited $663,183.98  txns 569
202606: credited $688,335.74  txns 582      (inside the ~$33k/advisor sanity band)
trading days 30/31/30, is_partial=false; prior_* zero on 202604, 242 later rows populated;
monthly_revenue re-sum MATCH; unmapped products listed and kept (MISC| 2, ZZZZ| 1)
```
Cohort selection first: 20 SIDs, coverage matrix printed, **9/9 flags covered**,
grid-reduction advisors taken first, 3 no-flag advisors included.
Generated manifest is structurally identical to the mock generator's
(same top keys, same 46 targets, same file-entry keys) — ingestion consumes
it unchanged; `load_real_data`/`verify_real_data` ran clean on the test set
(46 targets, manifest verification ok, 0 mismatches).

**8. ColumnMismatchError raises naming file and column**
```
BUILD FAILED — ColumnMismatchError: raw extract file 'raw_acct_eci_map.csv' is missing
contracted column(s) ['new_exst_adv_clnt_in_cyr'] — found columns ['bus_dt',
'wm_src_sys_cd', 'wm_acct_src_nb', 'eci_nb']
```
No output directory written (never a partial build). Missing-file variant
also demonstrated.

**9. every edge file's to_id resolves, dropped counts printed**
Per-file dropped counts print for all 29 edge files; on the fabricated set
(which carries a deliberately orphaned account) exactly the expected drops
appear — `txn_for_account: 2`, `am_for_account: 3`, 0 everywhere else.

**10. chip tooltips render; the fallback emits no repeated bullets**
`Chip.tsx` has an optional `title` prop; driver chips pass the matched rule's
`statement` first, falling back to the single shared table
`frontend/lib/driverDefinitions.ts` (13 tags + "New Billing" with the exact
spec wording). `npm run build` passes. Fallback probe:
```
one finding → bullets: ["**Fee reductions** — ($18,400). 2 accounts reduced"]  (exactly 1)
zero findings → honest empty state, bullets: []
```
Also in Task 5: "cached" wording replaced by the
`✓ Stored — generated <time> · rule set v<n>` footer; the Trace tab's
prompt-cache metrics deliberately keep saying cache.

## Verify suites (re-run after all commits)

```
verify_round_a.py   25/25
verify_round_b.py   19/19   (B3-13 now pins the exact 5 seed codes)
verify_round_c.py   13/13
verify_round_e.py    8/8
```

## Models and cost

The extraction re-run (Task 3.3) ran on **claude-sonnet-4-5-20250929** — the
`.env` per-role pins `RULE_EXTRACTOR_MODEL`/`RULE_COMPILER_MODEL` from the
Round E model policy override the Haiku default, and were kept so
"COMPILED rises from 15" is a like-for-like comparison with the Round E
baseline. Cost from turn logs (response.usage, never estimated):
full pass $1.3523 + targeted evidence pass $0.3706 = **$1.72 of the $3
Round F ceiling**. No other task spent LLM tokens.
Project running total: **≈ $3.44 of the $15 project ceiling**.

## Deviations / notes

- The Task 1 premise ("Current position still says Round C") was already fixed
  during Round E (54a07d0); Task 1 instead advanced the position to Round F
  and committed the Round F spec files.
- Two extraction passes were needed: the rule store is process-local, so the
  first pass's compiled plans died with the process; a targeted second pass
  captured plans/citations. Extractor naming is nondeterministic across
  passes (e.g. PRODUCT_MIN_EQUITY vs EQUITY_PRODUCT_MINIMUM) — same provisions.
- `insights_miner.py` VALID_TAGS gained "New Billing" (flagged by Subagent A:
  agent-authored findings with the new driver tag would otherwise coerce to
  "Other"); committed with Tasks 2+3.
- Spec said "10 raw filenames"; ROUND_D_EXTRACTION names 12 — `RAW_CONTRACT`
  holds all 12 and the spec was corrected.
- `docs/spec/EXTRACTION_SQL.md` (cited by ROUND_D_EXTRACTION §4) does not
  exist in this repo; SQL templates were authored from
  `prompts/COPILOT_EXTRACTION_COLD_START.md` §§1–4 plus the confirmed
  corrections, and the spec's dangling references now say so.
- `docs/data/extraction/*.sql` currently carry the test cohort SIDs; rerunning
  `generate_extraction_sql.py` with the real `cohort.txt` regenerates them.
- The compiled grid-sharing rule matched 0 rows on mock data (its plan reads
  `eff_disc_pct` as whole percent) — extraction/citation/compile requirements
  are met; whether it should fire on mock data is a next-session look.

## Servers

uvicorn :8001 (healthy) and Next.js :3001 (200) restarted on this round's
code and left running on the forwarded URLs. Making the forwarded ports
public still requires the Ports panel (the gh token lacks the codespace
scope — carried over since Round C).
