# Requirements Traceability

Every decision made during the requirements conversation, and where it is specified. Use this to
verify nothing was lost between discussion and build.

Legend — **✅** specified · **⚠** partially specified, see note · **⛔** deliberately deferred

---

## Data model and revenue

| # | Decision | Where | |
|---|---|---|---|
| 1 | Credited revenue = `SUM(post_split_credited_amt)` where reason code is null/none/empty | SCHEMA_SPEC §0, BUILD_PLAN §3.1 | ✅ |
| 2 | Non-credited rows still ingested with `reason_cd`, excluded from totals, visible to agents | SCHEMA_SPEC §0, ROUND_C_SPEC C1 (`non_credited_summary`) | ✅ |
| 3 | `post_split_credited_amt` already carries the team split — never re-apply | SCHEMA_SPEC §0, V8 | ✅ |
| 4 | Never join trades to team agreements when summing — fans out per secondary member | SCHEMA_SPEC §0 | ✅ |
| 5 | Team shares are fractions (0.0–1.0), not percents | SCHEMA_SPEC V8 | ✅ |
| 6 | Month from `proc_dt` (Round 5 correction — client-confirmed; was "from `trade_dt`, never `proc_dt`", which was wrong for this client) | SCHEMA_SPEC §0, ROUND_D D6, ROUND_5 task 2 | ✅ |
| 7 | Account keys normalised `ltrim(trim(x),'0')` in ONE shared function | SCHEMA_SPEC §0; `app/shared/ids.py`. **Round B must wire it into ingestion** | ⚠ |
| 8 | April is the baseline month; lost-account detection starts at May | SCHEMA_SPEC §0, ROUND_B B3.7, ROUND_C C6.10 | ✅ |
| 9 | June is partial (12 of 21 trading days) — `trading_days` on the month vertex | SCHEMA_SPEC V1, ROUND_C C1 (`month_meta`) | ✅ |
| 10 | No PII extracted — tax id, addresses, names | SCHEMA_SPEC §0, ROUND_D D3.2 | ✅ |
| 11 | Households: all relationship codes loaded; owner-role filter at query time | SCHEMA_SPEC §0, V7b | ✅ |
| 12 | Beneficiary (802) excluded from rollups, retained for future CRM joins | SCHEMA_SPEC V7b | ✅ |
| 13 | RPG is a vertex — the sharing threshold applies at group level | SCHEMA_SPEC V7d, ROUND_C C1 (`fee_reduction_by_rpg`) | ✅ |
| 14 | `account_eci_map` retained as the cross-system bridge | SCHEMA_SPEC V7c | ✅ |
| 15 | `fpic_acct_tb_pm` is a current snapshot — never use `financial_advisor_cd` for history | SCHEMA_SPEC V6 | ✅ |
| 16 | `account_open_dt` is text `MM/DD/YYYY HH:MI:SS AM`, blanks exist | SCHEMA_SPEC V6 | ✅ |
| 17 | Flows required, advisor × month grain, April + May only | SCHEMA_SPEC V13 | ✅ |
| 18 | Flow JSONB flattened into named columns | SCHEMA_SPEC V13 | ✅ |
| 19 | Flow product taxonomy differs from `product_hierarchy` — no crosswalk, advisor grain only | SCHEMA_SPEC V13 | ✅ |
| 20 | Intra-team transfers flagged (measured at zero in Q2) | SCHEMA_SPEC V12 | ✅ |
| 21 | Every per-entity primary key embeds its scope (R16 lesson) | SCHEMA_SPEC §1–2 | ✅ |
| 22 | `QUOTE="double"` on every loading job | BUILD_PLAN §4.2, verified in Round A | ✅ |

## Product model

| # | Decision | Where | |
|---|---|---|---|
| 23 | 24 display groups; aggregation group and revenue class are **parallel** dimensions | SCHEMA_SPEC §4, BUILD_PLAN §3.2 | ✅ |
| 24 | TWHS not combined — prefix label, products listed separately | SCHEMA_SPEC §4 | ✅ |
| 25 | ELIS split into Equities and Options | SCHEMA_SPEC §4 rows 11–12 | ✅ |
| 26 | LEND split into Security Based Lending and Margin | SCHEMA_SPEC §4 rows 22–23 | ✅ |
| 27 | UMA standalone row **and** Recurring | SCHEMA_SPEC §4 row 2 | ✅ |
| 28 | 529T Recurring (a trail) | SCHEMA_SPEC §4 row 8 | ✅ |
| 29 | Situational Partnership Recurring (reverses V2) | SCHEMA_SPEC §4 row 7 | ✅ |
| 30 | Donor Advised Funds Recurring (reverses V2) | SCHEMA_SPEC §4 row 9 | ✅ |
| 31 | ATMF its own group, Trails – Mutual Funds | SCHEMA_SPEC §4 row 3 | ✅ |
| 32 | Alternative Investments Non-Recurring (assumed, unconfirmed) | SCHEMA_SPEC §4 note | ✅ |
| 33 | Unmapped products visible, never dropped, V2 names | SCHEMA_SPEC §4 row 99, ROUND_D D3.2 | ✅ |
| 34 | `grid_type = 'PRODUCT_TYPE'` filter | SCHEMA_SPEC V4 | ✅ |
| 35 | Proper Title Case; "Brockered" typo fixed | SCHEMA_SPEC §4, ROUND_B B1.2 | ✅ |

## Screens

| # | Decision | Where | |
|---|---|---|---|
| 36 | Bar chart static at top, views load beneath on arrow selection | ROUND_B B1.2, mockups.html | ✅ |
| 37 | Product table: from, to, Change, Change %, % Share of Total, subtotals, grand total | ROUND_B B1.1 | ✅ |
| 38 | Negatives in parentheses, colour-coded, arrows, bold on the total row | ROUND_B B1.2 `format.ts` | ✅ |
| 39 | AI Insights: hybrid — short narrative plus bullets, not long prose | ROUND_C C3 | ✅ |
| 40 | Two pivots: By Driver and By Product | ROUND_C C5 | ✅ |
| 41 | Advisor view with per-advisor generated and stored insights | ROUND_C C4, C5 | ✅ |
| 42 | Evidence = simple account list, no formulas or operands | ROUND_C C2 (findings), mockups.html | ✅ |
| 43 | Filters only where they act; no duplicate dropdowns | ROUND_B B1.2 | ✅ |
| 44 | Rules shown in plain English with worked example; technical detail collapsed | ROUND_B B3.1, mockups.html | ✅ |
| 45 | Multi-file upload — drop zone and Browse | ROUND_B B2.4 | ✅ |
| 46 | New menu, five tabs; V2 menu discarded | ROUND_B B1.2 | ✅ |
| 47 | V2 theme: navy, tan Recurring, blue Non-Recurring, Real/Derived chips, AI Generated chip | ROUND_B B1.2, mockups.html | ✅ |
| 48 | No reconciliation banner, no MIX, no formula evidence | BUILD_PLAN §1, ROUND_C C2 | ✅ |

## AI architecture

| # | Decision | Where | |
|---|---|---|---|
| 49 | Four agents: Rule Extractor, Rule Conflict Auditor, Insights Miner, Insights Reporter | BUILD_PLAN §3.4 | ✅ |
| 50 | AI decides what counts; code does the counting | BUILD_PLAN §1, ROUND_C C0 | ✅ |
| 51 | Miner queries a fixed catalog; it does not write GSQL | ROUND_C C0, C1 | ✅ |
| 52 | Reporter never sees the graph — enforced by construction | ROUND_C C3, C6.9 | ✅ |
| 53 | Every number in prose must trace to a finding — regex assertion in code | ROUND_C C3, C6.5 | ✅ |
| 54 | Findings are independent observations, not a decomposition | ROUND_C C2, BUILD_PLAN §1 | ✅ |
| 55 | Coverage ratio computed internally, never shown | ROUND_C C2 | ✅ |
| 56 | Query budget 40 per advisor, logged, `budget_hit` visible | ROUND_C C2, C6.6 | ✅ |
| 57 | Evidence rows kept from the query that produced them | ROUND_C C2 | ✅ |
| 58 | Rules loaded into Miner context so it investigates like a plan reader | ROUND_C C2 | ✅ |
| 59 | Surprises from exhaustive evaluation, cohort deviation, expected-vs-recorded divergence | BUILD_PLAN §3.5; `peer_comparison` and `fee_reduction_accounts` in ROUND_C C1 | ✅ |
| 60 | Rules extracted once in batch, reviewed, versioned — not per request | ROUND_B B3.4 | ✅ |
| 61 | Conflicts detected and proposed, never auto-applied | ROUND_B B3.5 | ✅ |
| 62 | Rule expression grammar deliberately narrow | ROUND_B B3.2 | ✅ |
| 63 | Uncompilable rule cannot be approved | ROUND_B B3.3 | ✅ |
| 64 | Missing threshold → `NEEDS_INPUT`, never invented | ROUND_B B3.4 | ✅ |
| 65 | v0 seeded with operator lifecycle rules, provenance `OPERATOR_SPECIFIED` | ROUND_B B3.7 | ✅ |
| 66 | Transferred-out checked **before** lost, so a transfer is not a loss | ROUND_B B3.7 evaluation_order | ✅ |
| 67 | Versions superseded, never deleted; insights record their version | SCHEMA_SPEC §2, ROUND_B B3.6 | ✅ |
| 68 | Chunking rework — sections, tables kept whole, page and section on every chunk | ROUND_B B2.1–B2.2 | ✅ |
| 69 | cdao embeddings 3072-dim, `_fit_dim` loud failure, sha256 idempotency | ROUND_B B2.3, ROUND_D D0.2 | ✅ |
| 70 | Honest not-found below 0.30 similarity, with no LLM call | ROUND_B B2.4 | ✅ |

## Environment and delivery

| # | Decision | Where | |
|---|---|---|---|
| 71 | cdao GPT-5: omit blank `api_version`, `temperature=1`, no `max_tokens` | BUILD_PLAN §2, ROUND_D D0.2 | ✅ |
| 72 | Tier-4 read while `GRAPH_CLIENT_MODE=real` fails loudly | BUILD_PLAN §7, ROUND_D D1 | ✅ |
| 73 | `reference/` read-only, never imported across | BUILD_PLAN §7 | ✅ |
| 74 | PROGRESS / DECISIONS / ROUND_x_COMPLETE state tracking | BUILD_PLAN §8 | ✅ |
| 75 | GSQL V1 constraints (parameter order, traversal targets, single-hop splits) | ROUND_D D2 | ✅ |
| 76 | Package availability from artifactory verified before deployment | ROUND_D D0.1 | ✅ |
| 77 | Windows/PowerShell: CRLF, paths, command chaining, long paths | ROUND_D D4 | ✅ |
| 78 | Real-data validation and reconciliation before trusting any figure | ROUND_D D3 | ✅ |
| 79 | 13-step client smoke test | ROUND_D D5 | ✅ |
| 80 | Failure playbook mapping symptom to cause | ROUND_D D6 | ✅ |

## Deferred — agreed, not lost

| # | Item | Why | Impact |
|---|---|---|---|
| D1 | Region and market filters | Confirmed absent from `pcr`; needs a client-supplied branch hierarchy | Cohort comparison uses the whole cohort rather than region peers |
| D2 | Chat / conversational assistant | After the core | None — reads what is already persisted |
| D3 | Anomaly detection screen | After the core | None — anomalies are findings ranked differently |
| D4 | Flow-to-account join | Join test inconclusive, both retries timed out | Flow findings stay at advisor grain |
| D5 | 145 bps vs 115 bps standard schedule | Client confirmation needed | Affects one rule parameter; extraction is unaffected |
| D6 | Alternative Investments revenue class | Unconfirmed since V2 R11 | Currently Non-Recurring by assumption |
| D7 | 100-advisor cohort | Starting at 10–20 for scenario coverage | Ingestion time; additive later |

---

## Open items requiring a human answer

| Item | Who | When |
|---|---|---|
| Is `chromadb` installable from the client artifactory? | Preflight D0.1 | **Before Round B ships** |
| Actual cdao embedding dimension | Preflight D0.2 | Before any document is indexed |
| Does June trade data end mid-month? | Copilot | Before the demo; affects labelling only |
| 145 vs 115 bps standard schedule | Client | Before the fee rule is trusted |
| Alternative Investments class | Client | Low urgency |
| Region/market source | Client | When filters are built |
