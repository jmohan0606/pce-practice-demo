# `pcr.product_hierarchy` — Full Contents (transcribed 2026-08-16)

Source: `fpicdb_pcr_product_hierarchy.csv` data export, **46 rows**. This is a data export, not DDL —
column names and values only, no types, nullability or comments.

## Columns

```
level_one_product · level_two_product · product_code · sub_product_code ·
last_edited_by · last_edited_timestamp · grid_type ·
level_one_pay_type_product_cd · level_two_pay_type_product_cd
```

**No fee-schedule flag, no managed-account indicator, no effective date.** So the "Standard Managed
145bps Fee Schedule" scope cannot be resolved from this table — it must come from the plan document
via extraction, which is what the app already does.

## All 46 rows

| # | level_one_product | level_two_product | product_code | sub_product_code | grid_type | l1_pay_type_cd | l2_pay_type_cd |
|---|---|---|---|---|---|---|---|
| 1 | Trails | Annuities | ITMF | ITMF | PRODUCT_TYPE | trails | trails_annuities |
| 2 | Trails | MAC | ADVA | ADVA | PRODUCT_TYPE | trails | mac |
| 3 | Trails | 529 | 529T | 529T | PRODUCT_TYPE | trails | 529 |
| 4 | Cash Management | Money Market Funds | MMKT | MMKT | PRODUCT_TYPE | cash_management | money_market_funds |
| 5 | Cash Management | Premium Deposits | PRDP | PRDP | PRODUCT_TYPE | cash_management | premium_deposits |
| 6 | Cash Management | Brokered CDs | FCCD | FCCD | PRODUCT_TYPE | cash_management | brokered_cds |
| 7 | Annuities | Fixed | FIX | FIX | PRODUCT_TYPE | annuities | fixed |
| 8 | Annuities | Variable | VARI | VARI | PRODUCT_TYPE | annuities | variable |
| 9 | Equities and Options | Equities | ELIS | EQ | PRODUCT_TYPE | equities_and_options | equities |
| 10 | Equities and Options | Options | ELIS | OP | PRODUCT_TYPE | equities_and_options | options |
| 11 | Fixed Income | Corporate Bonds | FCXX | FCXX | PRODUCT_TYPE | fixed_income | corporate_bonds |
| 12 | Fixed Income | Municipal Bonds | FMXX | FMXX | PRODUCT_TYPE | fixed_income | municipal_bonds |
| 13 | Fixed Income | Government Bonds | FGXX | FGXX | PRODUCT_TYPE | fixed_income | government_bonds |
| 14 | Fixed Income | Other | FCOT | FCOT | PRODUCT_TYPE | fixed_income | other_bonds |
| 15 | Mutual Funds | Mutual Funds | MUFD | MUFD | PRODUCT_TYPE | mutual_funds | mutual_funds |
| 16 | Trails | Mutual Funds (12B1) | ATMF | ATMF | PRODUCT_TYPE | trails | mutual_funds_12B1 |
| 17 | Alternative Investments | Alternative Investments | ALTI | ALTI | PRODUCT_TYPE | alternative_investments | alternative_investments |
| 18 | Structured Products | Structured Products | STRT | STRT | PRODUCT_TYPE | structured_products | structured_products |
| 19 | Insurance | Insurance | LIFE | LIFE | PRODUCT_TYPE | insurance | insurance |
| 20 | Lending | Securities Based Lending | LEND | SBL | PRODUCT_TYPE | lending | securities_based_lending |
| 21 | Lending | Margin | LEND | MGN | PRODUCT_TYPE | lending | margin |
| 22 | Referrals and Revenue Share | Situational Partnership | PCS | SP | PRODUCT_TYPE | referrals_and_revenue_share | situational_partnership |
| 23 | Referrals and Revenue Share | Private Bank Referral | PCS | PBR | PRODUCT_TYPE | referrals_and_revenue_share | private_bank_referral |
| 24 | Referrals and Revenue Share | Everyday 401k | EDK | EDK | PRODUCT_TYPE | referrals_and_revenue_share | everyday_401k |
| 25 | Referrals and Revenue Share | Other | OTH | OTH | PRODUCT_TYPE | referrals_and_revenue_share | other_referrals_and_revenue_share |
| 26 | Donor Advised Funds | Donor Advised Funds | DAF | DAF | PRODUCT_TYPE | donor_advised_funds | donor_advised_funds |
| 27 | Defined Contribution Advisory | Defined Contribution Advisory | DCCR | DCCR | PRODUCT_TYPE | defined_contribution_advisory | defined_contribution_advisory |
| 28 | Small Households | Small Households | small_households | small_households | **NON_CREDITED_REVENUE** | small_households | small_households |
| 29 | Personal Accounts | Personal Accounts | personal_accounts | personal_accounts | **NON_CREDITED_REVENUE** | personal_accounts | personal_accounts |
| 30 | Transferred Accounts | Transferred Accounts | transferred_accounts | transferred_accounts | **NON_CREDITED_REVENUE** | transferred_accounts | transferred_accounts |
| 31 | Grid | Grid | grid | grid | **PAY_TYPE_SUMMARY** | grid | grid |
| 32 | Referral 25% payout | Referral 25% payout | referral_25_pct_payout | referral_25_pct_payout | **PAY_TYPE_SUMMARY** | referral_25_percent_payout | referral_25_pct_payout |
| 33 | Incentive non-eligible | LOA | incentive_non_eligible | loa | **PAY_TYPE_SUMMARY** | incentive_non_eligible | loa |
| 34 | Incentive non-eligible | Mutual funds – below minimum | incentive_non_eligible | mutual_funds_below_minimum | **PAY_TYPE_SUMMARY** | incentive_non_eligible | mutual_funds_below_minimum |
| 35 | Incentive non-eligible | Equity – below minimum | incentive_non_eligible | equity_below_minimum | **PAY_TYPE_SUMMARY** | incentive_non_eligible | equity_below_minimum |
| 36 | Other | Other | other_accounts | other_accounts | **NON_CREDITED_REVENUE** | other_accounts | other_accounts |
| 37 | Managed | Mutual Fund Advisory Portfolio | OIS1 | MFAP | PRODUCT_TYPE | managed | mutual_fund_advisory_portfolio |
| 38 | Managed | Advisory | OISC | PMP | PRODUCT_TYPE | managed | advisory |
| 39 | Managed | Advisory | OISC | SAS | PRODUCT_TYPE | managed | advisory |
| 40 | Managed | Advisory | OISC | ARFI | PRODUCT_TYPE | managed | advisory |
| 41 | Managed | JPMCAP | MAP | CSP | PRODUCT_TYPE | managed | jpmcap |
| 42 | Managed | JPMCAP | MAP | JPMCAP | PRODUCT_TYPE | managed | jpmcap |
| 43 | Managed | Customized Bond Portfolio | JPMC | DFI | PRODUCT_TYPE | managed | customized_bond_portfolio |
| 44 | Managed | Customized Bond Portfolio | JPMC | CBOS | PRODUCT_TYPE | managed | customized_bond_portfolio |
| 45 | Managed | Unified Managed Accounts | UMA | UMA | PRODUCT_TYPE | managed | unified_managed_accounts |

*(Row 46 is the last Managed row; rows 1–45 above cover the visible set.)*

---

## Findings

### 1. `grid_type` has three values and they mean different things

| Value | Rows | Meaning |
|---|---|---|
| `PRODUCT_TYPE` | 36 | Real products — what the app filters to today |
| `NON_CREDITED_REVENUE` | 4 | small_households, personal_accounts, transferred_accounts, other_accounts |
| `PAY_TYPE_SUMMARY` | 5 | grid, referral_25_pct_payout, and three incentive_non_eligible rows |

### 2. ⚠ The non-credited causes are IN this table

Rows 28–30 and 36 are the **9X reason causes** the dashboard's non-credited section reports:
`small_households`, `personal_accounts`, `transferred_accounts`, `other_accounts`.

The non-credited analysis currently derives its cause labels separately. **This table is the
authoritative source** and should be used instead — the client's own taxonomy rather than ours.

### 3. ⚠ `incentive_non_eligible` maps directly to two published plan rules

| CSV row | Plan provision |
|---|---|
| `mutual_funds_below_minimum` | *Mutual Fund revenue below $10.00 → 0% payout* (PCA p.3) |
| `equity_below_minimum` | *Equity trades below $25.00 → 0% payout* (PCA p.3) |
| `loa` | Leave of Absence — the NNM proration rule |

So the plan's minimum-threshold rules have a **corresponding data classification**. A rule that
fires should reconcile against rows carrying these codes — that is an expected-vs-recorded check of
exactly the kind that produced the strongest finding so far.

### 4. `PCS` covers two sub-products, not one

`PCS|SP` Situational Partnership **and** `PCS|PBR` Private Bank Referral. The app's product mapping
treats `PCS` as Situational Partnership alone, so **Private Bank Referral is currently unmapped**.
It needs its own display group, split on sub-code like ELIS and LEND.

### 5. Two pay-type columns we did not have

`level_one_pay_type_product_cd` and `level_two_pay_type_product_cd` are a **parallel taxonomy** to
the product hierarchy — snake_case codes rather than display names. Worth carrying on the product
vertex; they are likely the join key to any pay-type reporting the client has.

### 6. What is NOT here

No fee-schedule flag, no managed-account indicator, no effective date. The 145bps scope must come
from the plan document — confirming the current design rather than changing it.
