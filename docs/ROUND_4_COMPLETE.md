# Round 4 — COMPLETE (docs/spec/ROUND_4_SPEC.md)

Part A (the Round 3 items found still wrong on screen) then Part B (the four
CLI generation scripts). Sequential, no subagents. **Session app-LLM spend
≈ $2.88 of the $8 ceiling** ($1.73 practice regenerations + $1.15 topbottom
run; the account then hit its monthly usage cap — see Part B).

## PART A

### 1 — AI Insights renders the narrative ONLY ✓ (observed)

The duplication was exactly where the spec said: `InsightsSection` mapped
`findings` into bullets — the same findings `DriversSection` renders. It now
renders the reporter's cross-cutting paragraphs + its own narrative bullets
and a one-line pointer; the ranked finding cards appear once, in Revenue
Drivers. **Observed in a browser**: AI Insights card contains 0 `.finding`
elements and no "View evidence" link; Revenue Drivers contains 8.

### 2 — the served practice narrative is cross-cutting ✓ (pasted verbatim)

Both transitions regenerated (practice run only, ~$0.20 each) and read back
from `GET /api/insights/all/...`. What the dashboard serves:

**202604 → 202605** (generation 12, RSV_v12, limits none):

> Practice revenue rose $34,166 in May — a 3.99% gain — but **growth came
> entirely from the existing book**, not new business. The 177 retained
> accounts delivered $804,787, while new accounts and new billing combined
> contributed only $85,341. That imbalance means the practice is running in
> place: **one advisor, F. Hansen, lost 10 accounts totalling $54,978** —
> more than the combined revenue from all new accounts ($37,334) — and
> concentration remains acute, with 187 accounts flagged and a single
> relationship generating $63,993.
>
> The rule-based drivers sum to $945,105, yet actual revenue moved only
> $34,166, a $106,153 discrepancy that points to either overlapping
> classifications … Meanwhile, **13 accounts triggered the discount-sharing
> threshold** … and the largest cohort of six sits with a single advisor. …
>
> * **F. Hansen's book lost all 10 accounts** that closed in May … three of
>   them accounted for $25,791, or 47% of the total loss.
> * **New business contributed $85,341** … together they replaced less than
>   two-thirds of the revenue Hansen's book shed.
> * **187 accounts exceeded the concentration threshold** … M. Okafor holds
>   15 of them …
> * **13 accounts carry discounts above the threshold** … six of the 13
>   belong to A. Mehta …

**202605 → 202606** (generation 2, RSV_v12, limits none):

> June revenue fell $61,140.66, but **the decline masks a structural
> event**: a single account (1597) reclassified its structured-products fees
> mid-month, dropping from $57,012.40 in May to $2,491.91 in June … The
> account retained its $2.39M balance and remained active; the revenue
> simply moved to an unmapped product class. …
> The **concentration picture sharpened** … Fifteen of the concentration
> accounts belong to one advisor (A. Mehta), as do six of the thirteen
> discount flags. …

Connections across drivers, concentration, what the headline masks — not a
driver-list restatement.

**Three material fixes the regeneration exposed** (each found by running,
not reading):

1. **The numeric gate fought the cross-cutting mandate.** Four consecutive
   real-LLM attempts on 202604→202605 fell back to the template — first on
   whole-dollar roundings of allowed figures ("$34,166" for 34,165.52), then
   on CORRECT sums of headline impacts ($85,341 = 37,334 + 48,007) that the
   mandate itself asks for. The gate now accepts a whole-dollar rounding of
   an allowed figure and a token it can REPRODUCE as a sum/difference of two
   headline figures or a percentage of one over another — checked
   arithmetic, not trust; invented figures still fall (unit-proven: an
   unreproducible $30,363 is still rejected). Measured: rejections 10 → 0.
2. **The repair round contradicted the contract** ("do not sum…"), dropped
   the cross_cutting system prompt, and stood silently on the old rejection
   list when the rewrite was unusable. All three fixed.
3. **A confidently-wrong "-$911K residual" reached a served narrative**:
   RETAINED_ACCOUNT's $804,787 is a stock measure and was being summed into
   the change residual. NON_CHANGE_DRIVERS now leave the residual arithmetic
   (the Round A1 dominant-driver precedent); the residual became an honest
   −$106,153, which the narrative then explained as overlapping
   classifications.

### 3 — New To Product read "false" ON SCREEN — the operator was right ✓

After a clean `.next` rebuild the drill-down still showed it. **The bug was
not the table cell** (`AdvisorRows` renders Yes/No) — it was the
**advisor-accounts level's METRIC STRIP**: that level's metrics carry
`is_new_to_product`, and `metricValue()` only formats numbers, so the
boolean fell through raw as `false` in the "NEW TO PRODUCT" tile.
`metricValue` now routes boolean-ish values through `yesNo()`. **Observed
fixed in a browser**: the tile reads "No"; no `true`/`false` anywhere at
drill levels 1–3 (screenshots r4_drill_l2 before, r4_drill_l2_fixed after).

### 4 — §C/§D/§F sweep, each item observed on a clean rebuild

- C1 headers one font/size; C2 product names bold; C3 "Accounts" (no
  "Accts" anywhere in the page text); C4 "Managed – Unified Managed
  Accounts", "TWHS – …" en-dash prefixes — observed on the product table.
- D1 bold metric labels; D2 "AUM (MANAGED ACCOUNTS ONLY)" tile only on the
  managed group; D3 coloured/arrowed prior comparisons on tiles; D4 bold
  section headers; D5 "M. Okafor (V000003)"-style links in Contribution by
  advisor; D6 bold blue New tag; D7 Yes/No (task 3); D8 lifecycle strip at
  every level; D9 the transaction-volume tile — observed in the drill-down.
- F1 "Revenue Drivers"; F2 By Product shows real group names ("Managed
  Accounts", "Structured Products"); F3 evidence collapsed with the
  opens-on-click note; F4 labelized headers (Account/Value); F5 paginated
  ("1–5 of 177"); F6 shrinks to content; F7 highlighted names; F8 "Source /
  Citation:" prefixes; F9 driver tags bold, unwrapped, no REAL/DUMMY —
  observed with an evidence table open.
- **Still-wrong list: two items found and fixed during the sweep** —
  (a) By Product led with "No product attribution"; attributed groups now
  sort first (observed: Managed Accounts before No-attribution).
  (b) nothing else; one cosmetic nit remains OPEN and is listed as such:
  `NarrativeText` colours a parenthetical positive red when the reporter
  writes "($48,007)" as apposition rather than negation — the pre-existing
  paren heuristic (A2B carried observation #2), visible in one narrative
  bullet. Not fixed this round: the heuristic change risks re-breaking the
  negative-in-parens convention everywhere else.

### 5 — CRLF churn ✓

112 files were committed with CRLF (`git ls-files --eol`: 433 lf / 112
crlf). `.gitattributes` added exactly as specced; `git add --renormalize .`;
one labelled commit (113 files, 44,739+/44,734−, same lines re-terminated).
Data suites re-run green afterwards (a 25/25, b 19/19, round_1 12/12,
round_1b 8/8) — the committed CSVs parse identically. `git status` is clean.

## PART B — the four generation scripts

`scripts/_generate_insights_common.py` + `generate_practice_insights.py` /
`generate_topbottom_insights.py` / `generate_advisor_insights.py` /
`generate_insights.py` (dispatcher — pure delegation; the three stay
independently runnable). One backend addition: `practice_only` on
POST /api/insights/generate, so the practice script's unit is ONE aggregate
run per transition (the UI button keeps the Round C cohort fan-out).

### Script 2 run FOR REAL — managed_accounts, 202604 → 202605 (actual output)

```
top/bottom 10 advisors in managed_accounts, 202604 -> 202605
  TOP     V000003  +$8,643   V000002  +$7,169   V000009  +$7,044   V000011  +$6,094   V000006  +$2,184   V000018  +$2,056   V000007  +$1,187   V000001  +$1,052   V000019  +$272   V000004  +$252
  BOTTOM  V000013  -$7,311   V000008  -$3,350   V000005  -$2,791   V000014  -$2,297   V000012  -$1,896   V000020  -$1,692   V000017  -$1,057   V000010  -$378   V000016  +$1   V000004  +$252
  19 advisors selected (product has 19, fewer than 2 x 10)
estimated: ~$3.24 and ~25 min (from 51 runs' actuals)
  SKIP  V000003 (M. Okafor)                run already stored for this key (generation 4, RSV_v12) — --regenerate supersedes
  … (8 SKIPs — advisors whose RSV_v12 runs already exist)
  DONE  V000002 (A. Mehta)                 turns   28 · queries  25 · tokens   400,530 · cost  $0.1873 · wall   75s · findings 6
  DONE  V000009 (C. Fournier)              turns   29 · queries  25 · tokens   408,954 · cost  $0.1963 · wall   70s · findings 6
  DONE  V000011 (R. Nguyen)                turns   30 · queries  25 · tokens   429,800 · cost  $0.2014 · wall   84s · findings 6
  DONE  V000006 (T. Rossi)                 turns   30 · queries  25 · tokens   419,470 · cost  $0.1892 · wall   66s · findings 5
  DONE  V000018 (H. Byrne)                 turns   29 · queries  25 · tokens   422,466 · cost  $0.1843 · wall   75s · findings 4
  DONE  V000019 (Z. Sato)                  turns   28 · queries  24 · tokens   404,826 · cost  $0.1866 · wall   76s · findings 5
  FAIL  V000012 (B. Silva)                 BadRequestError: … 'You have reached your specified API usage limits. You will regain access on 2026-09-01 at 00:00 UTC.'
  … (5 FAILs, all the monthly usage cap)

total: 6 generated · 8 skipped · 5 failed · $1.1451 · 475s
failures: (all five listed with the full server reason)
exit=1
```

Mid-run **the Anthropic account hit its configured MONTHLY usage cap**
(distinct from the earlier balance top-up; resets 2026-09-01). Failure
isolation held: the five failures were recorded and listed, the run
completed, exit code 1. The **rerun resumed**: 14 SKIPs (6 from the plan
checkpoint + 8 as stored runs), re-attempted only the five failures (each
rejected by the API at $0.0000), exit 1.

### The verify list

- **6** each script generates and the result is retrievable — V000002 /
  V000011 / V000019 read back COMPLETE gen 3 RSV_v12 with 6/6/5 findings
  and zero limits.
- **7** rerunning skips (8 stored-run SKIPs + 2 practice SKIPs shown);
  `--regenerate` supersedes via the same POST whose supersede semantics this
  round demonstrated repeatedly (practice generations 5→12) — a fresh
  `--regenerate` demonstration is **blocked on the usage cap** and is the
  one un-executed check.
- **8** interrupted run resumes — the rerun's 14 SKIP lines above.
- **9** projection from real trace history ("from 51 runs' actuals", and it
  moved to "57 runs' actuals" on the rerun); `--yes` skips the prompt; the
  no-history branch prints per-run cost unknown.
- **10** selection IS the dashboard modal's ranking (the script calls the
  modal's own endpoint /api/dashboard/product/{id}/ranking →
  product_advisor_ranking, same params — no second list to drift).
- **11** default managed_accounts; invalid `--product` prints the live valid
  list and exits 2 (shown).
- **12** the comment block is generated from app/revenue/products.py and
  includes referrals_private_bank; runtime validation imports the live list
  so it can never silently drift.
- **13** one target's failure never stopped the rest (6 DONE around 5 FAIL).
- **14** exit 1 with failures, 0 for the all-skip run (shown).
- **15** unknown SID: "unknown advisor SID 'V999999' — no LLM call was
  made", exit 2.
- **16** prerequisite messages: unreachable backend names API_BASE and the
  uvicorn command; mock mode prints the loud warning (fatal under
  `--require-real`); no-published-rule-set and flag-off messages implemented
  the same way.

## Regression

```
verify_round_3 10/10 · a 25/25 · b 19/19 · c 13/13 · e 8/8 · h 9/9 ·
a1 17/17 · round_1 12/12 · round_1b 8/8 · round_2a 16/16 (check 11 SKIP by
design) · flags 8/8 · manual 17/17 · nnm 19/19 · parity 31V/44E ·
npm run build clean (10/10 routes)
```

## Carried / open

- The five capped advisors (V000010/12/16/17/20) generate with one
  `generate_topbottom_insights.py --from 202604 --to 202605 --yes` once the
  monthly cap resets (2026-09-01) — the checkpoint will skip everything else.
- A live `--regenerate` supersede demonstration, same trigger.
- The NarrativeText parenthetical-positive nit (Part A task 4).
- Port visibility for 8002/3002 still needs the Ports panel (carried).

Servers left running: uvicorn :8002 (healthy, serving the regenerated
practice narratives) · next :3002 (200).
