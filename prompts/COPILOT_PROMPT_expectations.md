# Copilot Task — Testable Expectations from the Plan Documents

You have already parsed these four documents:

```
docs/2026 Changes FAQ_01.20.25.pdf
docs/CWM Private Client Advisor Plan 01-01-2026.pdf
docs/CWM Select Advisor Group Plan 01-01-2026.pdf
docs/FPI - Advisor Comp Summary 2026-04-05 (Plans).pptx
```

Two questions. Answer both, in the exact output format at the bottom.

---

## Q1 — Statements that assert something should be TRUE of the data

I need every provision that could be **checked against a database** and either hold or not hold.
These become automated exception checks: where the plan says X should happen, we test whether X
actually happened in the data.

**Include** a statement if it is one of:

| Kind | Meaning |
|---|---|
| `TRIGGER` | a threshold that, once crossed, requires an action or adjustment |
| `RECORD` | a value that must be present or recorded when a condition holds |
| `EXCLUDE` | a population that must be left out of a calculation |
| `WINDOW` | a timing rule — deadlines, effective dates, suspension periods |
| `CAP` | a stated maximum, minimum or floor |

**Exclude:** definitions, narrative, descriptions of intent, anything with no data consequence, and
anything you cannot express as a check.

For each statement give: the kind, the check in one plain line, the document and page, and the
field or table it would be tested against — using the column names below where they fit.

Available fields to reference (from the tables we extract):

```
trade details : advisor_sid, account_no, trade_dt, proc_dt, product_cd, product_sub_cd,
                post_split_credited_amt, pre_split_credited_amt, split_pct, reason_cd,
                standard_rate_bps, client_rate_bps, discount_amt, eff_disc_pct,
                grid_reduction, rpg, concession_type
accounts      : account_number, account_open_dt, managed_platform_cd, account_class_cd,
                party_primary_eci
transfers     : from_mem_sid, to_mem_sid, from_rr, to_rr, transfer_ts
balances      : acct_id, acct_bal (monthly, Apr/May/Jun)
flows         : total_inflows_am, total_outflows_am, total_net_financial_flows,
                total_cwm_comp_credited_flows_am, departed_advisor_sid,
                departed_advisor_excl_am, lob_trfr_excl_am, oi_pa_referral_cap_adj_am,
                large_flow_cap_adj_am, forced_closure_excl_am
team          : prm_standard_id, prm_share_pct, sec_standard_id, sec_share_pct, start_ts, end_ts
eci           : party_eci_id, enterprise_relationship_code, party_role_name
```

If a statement needs a field that is **not** in that list, still include it and write the field it
would need under `field` — those gaps are as useful to me as the checks themselves.

---

## Q2 — Every stated number

List every threshold, rate, cap, percentage, dollar amount or date the documents state as a
**specific value**. One line each with its page.

This resolves a contradiction I currently have: one section refers to a **145 bps** standard
schedule, while a worked example uses **115 bps** as standard. I need to know whether there are
multiple standard schedules (by product, plan or account type) or whether one of those is a
misreading. **Report every bps figure you find and what it is attached to.**

---

## OUTPUT RULES

- Output ONLY the two tables. No preamble, no plan, no checklist, no summary, no offers.
- Keep the whole response under 60 lines — it will be photographed.
- One line per row. If a check needs more than one line to express, it is too complex — skip it.
- **Never infer a number that is not stated.** If a provision references a threshold that the
  document does not give, write `NOT STATED` in the value column. That is a finding, not a failure.
- Cite the document short name and page for every row: `FAQ p.14`, `PCA p.4`, `SAG p.6`,
  `FPI s.9` (s = slide).

---

## RETURN EXACTLY THIS

```
=== Q1 TESTABLE EXPECTATIONS ===
kind | check (one line) | source | field
TRIGGER | effective fee reduction above 10% must produce a grid point reduction | PCA p.4 | eff_disc_pct, grid_reduction
...

=== Q2 STATED VALUES ===
value | what it applies to | source
10% | fee reduction sharing threshold | PCA p.4
...

=== BPS FIGURES (all of them) ===
bps | attached to | source
```
