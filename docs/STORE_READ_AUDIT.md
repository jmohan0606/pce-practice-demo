# Direct foundation-store reads outside app/graph/ — the audit (Round 8)

**The finding is systemic.** `app/rules/evaluator.py` was the first instance
(fixed this round: it now reads through the internal `rule_evaluation_rows`
catalog query, mock-mode results proven identical). The remaining direct reads
mean that in real mode the dashboard shows TigerGraph data while the advisor
page, exceptions, rules and chat compute from the LOCAL mock store — both look
plausible and nothing flags it.

**Scope decision input:** per call site, whether an existing query already
returns what it needs, or a new one must be written.

Legend:
- **A** — an existing CATALOG query covers it as-is
- **B** — an existing tiered named query covers it (`pce_dashboard_months` /
  `pce_dashboard_advisors` — registered like catalog queries, GSQL twins in
  the client install set, just not in the 46-query catalog)
- **EXT** — an existing query covers it after an ADDITIVE extension
  (a new return column or an accepted `'all'` scope — no caller breaks)
- **NEW** — a new (small) query must be written
- **RAW** — the honest need is raw vertex rows; the new internal
  `rule_evaluation_rows` (built this round for the evaluator) already covers
  it through the tiered client

`app/rules/evaluator.py` (3 reads) — **FIXED this round** (run_catalog_query
97 calls / 0 direct reads on the proof run; mock results identical).

## Per-site classification (41 remaining reads)

### app/insights/exceptions.py — 5 reads (helper `_store()` + 4 uses)
| Line | Reads | Verdict |
|---|---|---|
| 74 | month list (prior-month resolution) | **B** `pce_dashboard_months` |
| 108 | account master `is_managed` for ALL accounts | **NEW** `account_managed_flags` (bulk acct_key→is_managed; `account_master` is single-key) |
| 110 | account_month rows for one month, every advisor | **EXT** `accounts_for_month(advisor='all')` + an `advisor_sid` return column (today's returns omit it) |
| 120 | cohort SIDs | **B** `pce_dashboard_advisors` |
| 126 | advisor names | **B** `pce_dashboard_advisors` |

### app/api/routers/insights.py — 9 reads
| Line | Reads | Verdict |
|---|---|---|
| 82 | product_group name by id | **NEW** (tiny) `product_group_master(group_id)` — or **RAW** key lookup |
| 222 | month existence check | **A** `month_meta` (errors on an unknown month) |
| 232 | cohort SID set | **B** `pce_dashboard_advisors` |
| 243 | cohort AUM (sum end_balance over account_month) | **A** `advisor_aum(advisor='all')` — confirm the 'all' scope matches cohort semantics when wiring |
| 248 | cohort flows for a month | **A** `advisor_flows_summary(advisor='all')` |
| 257 | managed-account set | **NEW** `account_managed_flags` (same as exceptions:108) |
| 262 | managed-only AUM | **NEW** `aum_managed(advisor\|'all', month)` — D2's account-master-flag scope; `month_aum` uses a different membership rule |
| 293 | advisor names map | **B** `pce_dashboard_advisors` |
| 333 | advisor names map | **B** `pce_dashboard_advisors` |

### app/api/routers/advisor.py — 8 reads
| Line | Reads | Verdict |
|---|---|---|
| 42 | one advisor's full attributes | **EXT** `pce_dashboard_advisors` + the Round-5 attribute columns (job_code / job_display_name / work_state / work_city / is_synthetic, `in_cohort`), or a tiny `advisor_master(sid)` |
| 49 | month list | **B** `pce_dashboard_months` |
| 75 | every advisor + attributes (`/api/advisor/list`, the Round-7 cascade) | **EXT** same directory extension as :42 (must include non-cohort rows — a flag or a param) |
| 91 | team_agreement vertex (`team_rep_cd`) | **EXT** `team_members` + a `team_rep_cd` return column |
| 119 | does the advisor have account_month rows this month | **A** `accounts_for_month(advisor, month)` — row_count > 0 |
| 135 | managed-account set | **NEW** `account_managed_flags` |
| 137 | managed-only AUM rows | **NEEDS** the same **NEW** `aum_managed` as insights:262 |
| 223 | cohort SID set | **B** `pce_dashboard_advisors` |

### app/insights/describe.py — 4 reads
| Line | Reads | Verdict |
|---|---|---|
| 33 | acct_key→advisor map for a month | **EXT** `accounts_for_month(advisor='all')` + `advisor_sid` column (same extension as exceptions:110) |
| 41 | advisor names | **B** `pce_dashboard_advisors` |
| 59 | month's transactions restricted to matched accounts (dominant-group attribution) | **NEW** (small) `revenue_by_group_for_accounts(acct_keys, month)` — or **RAW** `rule_evaluation_rows(revenue_transaction, month)` (same volume as today's read) |
| 71 | product_group name | same **NEW**/RAW as insights:82 |

### app/rules/service.py — 2 reads (never-fired sweep)
| Line | Reads | Verdict |
|---|---|---|
| 499 | month list | **B** `pce_dashboard_months` |
| 500 | every advisor SID (non-cohort included) | **EXT** the advisor-directory extension (needs non-cohort rows), or **RAW** |

### app/rules/compiler.py — 2 reads (`_test_params` for check-5 execution)
| Line | Reads | Verdict |
|---|---|---|
| 515 | month list | **B** `pce_dashboard_months` |
| 516 | advisor list | **B** `pce_dashboard_advisors` |

### app/chat/agent.py — 2 reads
| Line | Reads | Verdict |
|---|---|---|
| 146 | advisor name/SID resolution map | **B** `pce_dashboard_advisors` |
| 155 | month list | **B** `pce_dashboard_months` |

### app/api/routers/nnm.py — 1 read
| Line | Reads | Verdict |
|---|---|---|
| 46 | month row existence | **A** `month_meta` |

### app/insights/service.py — 1 read
| Line | Reads | Verdict |
|---|---|---|
| 281 | month list | **B** `pce_dashboard_months` |

### app/export/providers.py — 2 reads (non-credited export)
| Line | Reads | Verdict |
|---|---|---|
| 136 | month existence | **A** `month_meta` |
| 140 | month's transactions grouped by reason code | **A** the `non_credited_by_cause` family / `non_credited_summary(advisor='all')` — confirm the export's firm-wide grouping matches when wiring |

## The verdict

Of the 41 remaining reads:

- **22 are covered by existing queries as-is** (A/B — mostly month lists,
  cohort/advisor names, month existence checks)
- **7 need additive extensions** to three existing queries
  (`pce_dashboard_advisors` + the Round-5 attribute columns & non-cohort rows;
  `accounts_for_month` + an `advisor_sid` column; `team_members` +
  `team_rep_cd`)
- **9 need genuinely new queries — but only THREE distinct ones**:
  `account_managed_flags` (bulk is_managed, 3 sites),
  `aum_managed` (managed-scoped AUM, 2 sites),
  `product_group_master` (name lookup, 2 sites) + optionally
  `revenue_by_group_for_accounts` (1 site, RAW-coverable)
- **3 are RAW-coverable today** via the internal `rule_evaluation_rows`

**This is a day, not a week**: three small new queries, three additive
extensions, then mechanical rewiring — with the mock-mode identity proof
pattern established by the evaluator fix (capture before, rewire, diff).
Each new/extended query also needs its GSQL twin in the client install set.

## The guard

`scripts/check_store_reads.py` — fails if any module outside `app/graph/`
imports `get_foundation_store` / `FoundationGraphStore` or calls
`all_vertices(` / `.vertex(` **beyond the recorded baseline** (this audit).
The baseline may only SHRINK: fixing a module without updating the baseline
passes; adding a read anywhere fails naming the file and line. When the
baseline reaches empty, the script IS the strict guard the fix demands.
