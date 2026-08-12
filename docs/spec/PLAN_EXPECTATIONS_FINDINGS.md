# Plan Document Expectations — Copilot Findings (transcribed 2026-08-11)

Extracted from the four client plan documents. Durable text record.
Sources: **PCA** = CWM Private Client Advisor Plan · **SAG** = CWM Select Advisor Group Plan ·
**FAQ** = 2026 Changes FAQ · **FPI** = FPI Advisor Comp Summary (s = slide)

---

## Q1 — Testable expectations (14)

| # | Kind | Check | Source | Field |
|---|---|---|---|---|
| 1 | WINDOW | Only pricing decisions on/after 2026-04-01 are in Discount Sharing scope | PCA p.3 | `trade_dt`/`proc_dt` proxy; **pricing decision date NOT STATED** |
| 2 | TRIGGER | Effective fee reduction above 10% triggers an account-level grid rate point adjustment | PCA p.4 | `eff_disc_pct`, `grid_reduction` |
| 3 | CAP | Discount-sharing adjustment cannot reduce payout below a 10% minimum grid rate | PCA p.4 | **effective grid/payout field NOT STATED** |
| 4 | EXCLUDE | Clients/accounts with fee reduction prior to 2026-04-01 are excluded from Discount Sharing | PCA p.3 | **historical fee-reduction-as-of-2026-03-31 NOT STATED** |
| 5 | TRIGGER | Total Annual NNM must meet/exceed $4MM for NNM Annual Award eligibility | PCA p.4 | `total_net_financial_flows` |
| 6 | CAP | If the NNM award calculation is below $500 but eligibility is met, payout floor is $500 | PCA p.4 | **computed award amount NOT STATED** |
| 7 | TRIGGER | Equity credited revenue below $25 gets 0% payout rate | PCA p.3 | `product_cd`/`product_sub_cd`, `post_split_credited_amt` |
| 8 | TRIGGER | Mutual Fund credited revenue below $10 gets 0% payout rate | PCA p.3 | `product_cd`/`product_sub_cd`, `post_split_credited_amt` |
| 9 | WINDOW | Plan effective date is 2026-01-01 | PCA p.7 | `trade_dt`/`proc_dt` (coverage window control) |
| 10 | WINDOW | Team agreements must start on the first day of a month | SAG p.5 | `team.start_ts` |
| 11 | TRIGGER | Each team member must derive ≥75% of monthly credited revenue from the team rep code to remain mirroring-eligible | SAG p.5 | **monthly revenue by member + team rep code NOT STATED** |
| 12 | WINDOW | If the 75% team-share test fails for two consecutive quarters, team mirroring stops the following quarter | SAG p.5 | **quarterly share metric + status NOT STATED** |
| 13 | TRIGGER | Select Anniversary Award requires ≥$1MM calendar-year credited revenue | SAG p.6 | `post_split_credited_amt` (annual aggregate by `advisor_sid`) |
| 14 | TRIGGER | SAG NNM award requires Total Annual NNM at/above $4MM | SAG p.6 | `total_net_financial_flows` |

**Buildable now (7):** 2, 5, 7, 8, 9, 10, 13 — and 5/14 only in a limited sense (see NNM below).
**Blocked on missing fields (6):** 1, 3, 4, 6, 11, 12.

---

## Q2 — Stated values

| Value | Applies to | Source |
|---|---|---|
| 2026-04-01 | Discount Sharing effective date | PCA p.3 |
| 10% | Discount Sharing threshold for managed-account fee reduction | PCA p.3 / p.4 |
| 10% | Minimum grid rate after discount-sharing adjustment | PCA p.4 |
| $4,000,000 | NNM annual award eligibility threshold | PCA p.4 |
| $500 | Minimum NNM award floor (if otherwise eligible) | PCA p.4 |
| $25.00 | Equity minimum; below this the payout rate is 0% | PCA p.3 |
| $10.00 | Mutual-fund minimum; below this the payout rate is 0% | PCA p.3 |
| 2026-01-01 | PCA plan effective date | PCA p.7 |
| 22% | Effective grid-rate floor used in definitions | PCA p.13 |
| 2026-04-01 | Discount Sharing effective date | SAG p.4 |
| 10% | Discount Sharing threshold | SAG p.4 |
| 10% | Minimum grid rate after discount-sharing adjustment | SAG p.5 |
| 75% | Required monthly revenue share from team rep code per member | SAG p.5 |
| 2 consecutive quarters | Failure duration that removes Team Mirroring | SAG p.5 |
| $4,000,000 | SAG NNM threshold | SAG p.6 |
| $500 | SAG minimum NNM award floor | SAG p.6 |
| $1,000,000 | Select Anniversary Award minimum calendar-year credited revenue | SAG p.6 |
| 2026-01-01 | SAG plan effective date | SAG p.9 |
| 22% | Effective grid-rate floor used in definitions | SAG p.15 |
| 2026-04-01 | Discount Sharing FAQ effective date | FAQ p.13 |

---

## BPS figures — the 145 vs 115 question is RESOLVED

| bps | Attached to | Source |
|---|---|---|
| **145 bps** | **Standard managed fee schedule in Discount Sharing scope** | FAQ p.13 |
| **115 bps** | **Worked example standard fee rate on managed assets** | FAQ p.15 |
| 100 bps | Worked example max rate used to compute effective discount | FAQ p.15 |
| 25 bps | Alternatives revenue trail (Direct/Institutional Evergreen and Municipal Funds) | FAQ p.2 |
| 50/55/60/65/70 bps | PCA NNM award-rate bands (negative / 0–4M / 4–10M / 10–20M / 20M+) | FAQ p.6 |
| 40/50/60/70 bps | SAG NNM award-rate bands (0–4M / 4–15M / 15–30M / 30M+) | FAQ p.7 |
| 65 bps | FAQ example NNM award rate for >$10M existing-client NNM | FAQ p.10 |
| 50 bps | Lending discount breakpoint ("discounted up to 50bps") | FAQ p.18 |
| 195 bps | Lending spread used in worked examples | FAQ p.18 |
| 50/55/60/65/70 bps | PCA plan NNM award-rate bands | PCA p.4 |
| **145 bps** | **Standard managed fee schedule for discount sharing applicability** | PCA p.3 |
| 40/50/60/70 bps | SAG plan NNM award-rate bands | SAG p.6 |
| **145 bps** | **Standard managed fee schedule for discount sharing applicability** | SAG p.4 |
| 25 bps | AGP NNM award calculation rate above $4M | FPI s.9 |
| 50–70 bps | CWM NNM award-rate range summary | FPI s.8 |
| up to 70 bps | CWM Select NNM award-rate summary | FPI s.8 |

**Answer: 145 bps is the real standard managed fee schedule.** It appears three times as the
*schedule* (FAQ p.13, PCA p.3, SAG p.4). The 115 bps figure appears once, only inside a worked
example (FAQ p.15). Both are correct; they are different things. **Rules must use 145 bps as the
standard; 115 bps belongs only in illustrative text.**

---

## Analysis

### 1. NNM is confirmed as a real plan concept — but still not extractable

It appears in five expectations and drives award-rate bands in every document. The threshold is
$4MM annual with a $500 floor.

But: the source field is `total_net_financial_flows`, we hold **three months**, and the measure is
**annual**. The Round E decision to remove NNM stands. What is new is that we can now state
precisely what to ask the client for: **an annual NNM figure per advisor, or twelve months of
flows.**

### 2. Three new rules are buildable immediately, and none needed new data

- **Equity credited revenue below $25 → 0% payout** (PCA p.3)
- **Mutual Fund credited revenue below $10 → 0% payout** (PCA p.3)
- **Select Anniversary Award: ≥$1MM calendar-year credited revenue** (SAG p.6)

All three use `product_cd`/`product_sub_cd` and `post_split_credited_amt`, which we already have.
The first two are also *exception checks*: rows below the minimum that still carry a payout are
findings.

### 3. Six expectations need fields that do not exist — the client conversation list

| Missing field | Blocks |
|---|---|
| Pricing decision date | Discount Sharing scope window (#1) and the pre-2026-04-01 exclusion (#4) |
| Effective grid / payout rate per advisor | The 10% minimum grid floor (#3) |
| Computed NNM award amount | The $500 award floor (#6) |
| Monthly revenue by team member and team rep code | The 75% mirroring test (#11) |
| Quarterly team-share metric and status | The two-quarter mirroring failure (#12) |

This is a precise, citable list to hand the client — each with the plan page that requires it.

### 4. A scope correction

Both plans are effective **2026-01-01** (PCA p.7, SAG p.9), while Discount Sharing starts
**2026-04-01** (PCA p.3, SAG p.4, FAQ p.13). Our data window is Apr–Jun 2026, so it sits entirely
inside both — no conflict, but the app should not imply a rule applies before its own effective
date.
