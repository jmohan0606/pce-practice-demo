# Direct foundation-store reads outside app/graph/ — the audit (Round 8)

> **Round 9 status: ALL 37 reads converted.** Every site below now reads
> through `run_catalog_query` (existing queries, the three new queries, or the
> internal `rule_evaluation_rows` generic vertex fetch);
> `scripts/check_store_reads.py` runs with an EMPTY baseline (strict guard),
> and mock-mode outputs were proven byte-identical before/after
> (docs/ROUND_9_COMPLETE.md). The tables below are the audit record.
>
> **Round 9 arithmetic correction:** this audit previously said **41** reads —
> that figure came from subtracting the evaluator's 3 from a prior count of 44
> rather than summing the tables, which total **36**. An independent AST
> census found **37**: the 36 audited plus `app/rules/service.py:497`
> `fstore.load()`, which the audit omitted (now added below). The bucket
> totals are re-derived from the tables: **A/B = 22, EXT = 6, NEW = 8, plus
> the one load-guard line** — every RAW mention in the tables is an
> alternative to a NEW/EXT verdict, never a standalone bucket. The
> three-new-queries conclusion survives; the arithmetic did not.

**The finding is systemic.** `app/rules/evaluator.py` was the first instance
(fixed in Round 8: it now reads through the internal `rule_evaluation_rows`
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

## Per-site classification (37 remaining reads — corrected in Round 9)

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

### app/rules/service.py — 3 reads (never-fired sweep)
| Line | Reads | Verdict |
|---|---|---|
| 497 | `fstore.load()` — ensure-loaded guard before the sweep | **(added in Round 9 — omitted by the original audit)** removed outright: the tiered mock path loads its own store; no query needed |
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

## The verdict (buckets re-derived from the tables — Round 9 correction)

Of the 37 remaining reads (36 audited + the omitted `service.py:497`):

- **22 are covered by existing queries as-is** (A/B — mostly month lists,
  cohort/advisor names, month existence checks: A=7, B=15)
- **6 need additive extensions** to three existing queries
  (`pce_dashboard_advisors` + the Round-5 attribute columns & non-cohort rows;
  `accounts_for_month` + an `advisor_sid` column; `team_members` +
  `team_rep_cd`)
- **8 need genuinely new queries — but only THREE distinct ones**:
  `account_managed_flags` (bulk is_managed, 3 sites),
  `aum_managed` (managed-scoped AUM, 2 sites),
  `product_group_master` (name lookup, 2 sites) + optionally
  `revenue_by_group_for_accounts` (1 site, RAW-coverable)
- **1 is the `fstore.load()` ensure-loaded guard** — removed, not converted
- RAW mentions in the tables are ALTERNATIVES to a NEW/EXT verdict (via the
  internal `rule_evaluation_rows`), never a standalone bucket — the previous
  "3 RAW-exclusive" claim was wrong

**This is a day, not a week**: three small new queries, three additive
extensions, then mechanical rewiring — with the mock-mode identity proof
pattern established by the evaluator fix (capture before, rewire, diff).
Each new/extended query also needs its GSQL twin in the client install set.

## The guard

`scripts/check_store_reads.py` — fails if any module outside `app/graph/`
imports `get_foundation_store` / `FoundationGraphStore` or calls
`all_vertices(` / `.vertex(` **beyond the recorded baseline** (this audit).
Round 9 (task 7) closed the pattern holes — it now also catches the tiered
client's `.store` back-door and the store's other read methods (`out` /
`inbound` / `out_ids` / `in_ids`, store-receiver `.load(` /
`.statistics(`) — and the ratchet SELF-TIGHTENS: an under-baseline run writes
the lower count back into the script, so the ceiling only moves down. The
baseline reached EMPTY in Round 9: the script is now the strict guard —
zero direct reads outside `app/graph/`.
