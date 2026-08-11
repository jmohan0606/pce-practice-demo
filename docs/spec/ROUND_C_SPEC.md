# Round C — Detailed Specification

Supersedes §6 of `BUILD_PLAN.md`. Read with `SCHEMA_SPEC.md`, `ROUND_B_SPEC.md` and
`docs/ui/mockups.html`.

---

## C0 · The decision this round turns on

The Insights Miner investigates by querying the graph. **It does not write GSQL.** A model
generating arbitrary graph queries is unreproducible, unreviewable and one syntax error away from
a dead run.

Instead: a **catalog of named, parameterised queries**. The Miner chooses which to call and with
what parameters — that choice is where its reasoning lives. The query text is fixed and reviewed.

This keeps the whole property the app is built on: **the agent decides what to look at; code
returns the numbers.** Same run, same rules, same data → same figures.

If a needed question has no query, the Miner records `unanswerable: <question>` in the run log
rather than improvising. Those log entries are how the catalog grows between rounds.

---

## C1 · The query catalog

`app/graph/queries/catalog.py` — each entry has a name, typed parameters, and a local
implementation against the mock store plus a GSQL file under `docs/tigergraph/queries/`.
Both return the identical envelope, exactly as Round A's ported tiered client expects.

| Name | Parameters | Returns |
|---|---|---|
| `revenue_by_product` | advisor_sid \| "all", month_id | group_id, group_name, class_id, credited_amt, txn_count, distinct_accounts |
| `revenue_change_by_product` | advisor, from_month, to_month | group_id, from_amt, to_amt, change_amt, change_pct |
| `revenue_by_advisor` | month_id | advisor_sid, credited_amt, rank |
| `advisor_totals` | advisor, from_month, to_month | from_amt, to_amt, change_amt, change_pct |
| `accounts_for_month` | advisor, month_id | acct_key, credited_amt, end_balance, is_zero_balance |
| `accounts_opened` | advisor, from_dt, to_dt | acct_key, account_open_dt, first_month_revenue |
| `accounts_zeroed` | advisor, from_month, to_month | acct_key, prior_balance, prior_credited_amt |
| `accounts_absent` | advisor, from_month, to_month | acct_key, prior_credited_amt |
| `transfers_in` | advisor, from_dt, to_dt | acct_key, from_advisor_sid, transfer_ts |
| `transfers_out` | advisor, from_dt, to_dt | acct_key, to_advisor_sid, transfer_ts |
| `fee_reduction_accounts` | advisor, month_id, threshold_pct | acct_key, standard_bps, client_bps, reduction_pct, grid_reduction, rpg_id |
| `fee_reduction_by_rpg` | advisor, month_id | rpg_id, account_count, blended_reduction_pct, accounts_above_threshold |
| `account_txns` | acct_key, month_id | txn_id, product_id, credited_amt, trade_dt, reason_cd |
| `top_txns` | advisor, month_id, group_id, limit | txn_id, acct_key, credited_amt, trade_description |
| `product_txn_stats` | advisor, month_id, group_id | txn_count, distinct_accounts, avg_amt, max_amt |
| `non_credited_summary` | advisor, month_id | reason_cd, non_credited_amt, txn_count |
| `flows_for_advisor` | advisor, month_id | flow_product_cd, inflows, outflows, net_flows, credited_flows |
| `household_accounts` | eci_id | acct_key, advisor_sid, credited_amt |
| `account_household` | acct_key | eci_id, relationship_code, party_role_name, is_owner_role |
| `rpg_accounts` | rpg_id | acct_key, advisor_sid, credited_amt |
| `team_members` | advisor | agreement_id, prm_advisor_sid, sec_advisor_sid, share_pct, status |
| `peer_comparison` | month_id, metric, advisor | advisor_sid, value, rank, cohort_median |
| `month_meta` | month_id | trading_days, is_baseline, is_partial |
| `account_master` | acct_key | account_class_cd, managed_platform_cd, is_managed, opened_in_scope, primary_eci_id |

24 queries. Every rollup filters `is_owner_role = true` when traversing households, and cohort
totals filter `in_cohort = true`.

---

## C2 · Insights Miner

### Tools

```python
run_graph_query(query_name: str, params: dict) -> {"rows":[...], "row_count":int}
get_schema() -> {vertices, attributes, query catalog with parameter signatures}
search_documents(query: str, top_k: int = 5) -> [{chunk_id, page_no, section_path, excerpt, similarity}]
```

Every call appends a `phx_dm_pce_agent_query_log` row: `run_id`, `seq_no`, `agent_name`,
`query_name`, `params_json`, `row_count`, `latency_ms`.

### Context given at the start of a run

1. The published rule set — `plain_description`, `driver_tag` and `worked_example` for each rule.
   These tell the Miner **what matters in this business**, so it investigates like someone who has
   read the comp plan.
2. The transition being explained: advisor, from month, to month, totals, change.
3. The query catalog with parameter signatures.
4. Month metadata, including trading days and the partial flag.

### Loop

```
budget = 40
findings = []
observations = [initial revenue_change_by_product call]

while budget > 0 and not done:
    decide: which query next, and why          <- the agent's reasoning
    result = run_graph_query(...)              <- deterministic
    budget -= 1
    interpret: does this explain part of the move? does it raise a new question?
    if a coherent finding has formed:
        findings.append(finding_with_evidence_rows)
    if no thread remains worth pulling: done = True
```

**Guidance in the system prompt, not hard rules:**
- Start broad (which products moved), then narrow to the accounts behind the move.
- When a number does not add up, say so and keep looking — an unexplained residual is itself a
  finding worth reporting.
- Follow surprises across entity boundaries: product → account → transfer → household → RPG.
- Prefer few well-evidenced findings over many thin ones.
- A rule that fires is worth reporting. A rule that *should* have fired and did not is worth more.

### Findings

```json
{
  "title": "Fee Reduction Above the Sharing Threshold",
  "summary": "11 accounts across 2 advisors passed 10%, but only 1 carries a grid reduction",
  "impact_amt": -18400.00,
  "driver_tag": "Fee Rate",
  "group_id": "managed_accounts",
  "rule_key": "v4|FEE_REDUCTION_SHARING",
  "provenance": "REAL",
  "confidence": 0.9,
  "evidence_rows": [{"account":"0095762099","advisor":"F360436","standard":"145 bps",
                     "actual":"118 bps","reduction":"19%","expected":9,"recorded":0}],
  "evidence_columns": ["account","advisor","standard","actual","reduction","expected","recorded"],
  "source_query": {"query_name":"fee_reduction_accounts",
                   "params":{"advisor":"V077477","month_id":"202605","threshold_pct":10}}
}
```

Rules:
- `impact_amt` is a query result, never an estimate. If a finding is qualitative, set it to `null`
  and say so in the summary — do not invent a figure to fill the field.
- `provenance` is `REAL` when every figure came from a query; `DERIVED` when the Miner computed a
  ratio or difference **from query results** (e.g. trading-day scaling).
- **Evidence rows are kept from the query that produced them**, capped at 50 stored / 20 displayed.
  Never discard rows after reading a count — re-running an agentic loop will not reproduce the
  same queries.
- `rule_key` is null when the finding came from investigation rather than a rule. That is expected
  and desirable: it is where the surprises live.
- Findings are **independent observations**. They are not expected to sum to the total change and
  must not be forced to.

### Coverage check — internal only

After the run, compute `sum(|impact_amt|) / |total change|` and store it on the run. Log a warning
above 200% (likely double-counting) or below 20% (thin coverage). **Never shown in the UI** — it is
a build-time signal that a rule is over-claiming, not a client-facing number.

---

## C3 · Insights Reporter

**Receives findings only. No graph access. No tools.** This is the enforcement mechanism, not a
convention — wire it so it physically cannot query.

Produces:
```json
{"narrative":"<two short paragraphs, key clauses in **bold**>",
 "bullets":["<four bullets, each opening with a bolded claim>"]}
```

Style, from `mockups.html`:
- Two sentences of narrative, then four bullets. Roughly half the length of a full prose write-up.
- Lead with what is *interesting*, not what is largest. "Revenue rose $227,230, but almost none of
  it came from new business" beats "Revenue rose 3.6%."
- Plain business English. No driver codes, no field names, no rule identifiers.
- Negatives in parentheses. Figures formatted as the UI formats them.

**Hard assertion, enforced in code not prompt:** every numeric token in the narrative and bullets
must appear in the findings — `impact_amt`, an evidence cell, or a count from a finding. Extract
all numbers with a regex, check membership, and on failure fall back to a template built directly
from the top findings. Log the failure. **Never publish an unverified figure.**

---

## C4 · Async runs

```
POST /api/insights/generate  {"advisor":"V077477"|"all","from_month":"202604","to_month":"202605"}
     -> {"job_id":"...", "run_count":n}
GET  /api/insights/status/{job_id}
     -> {"status":"running|complete|failed","completed":4,"total":20,
         "current":"V000005","runs":[{"run_id","advisor_sid","status","finding_count"}]}
GET  /api/insights/{advisor}/{from}/{to}?version=latest
     -> {"run_id","version_id","narrative","bullets","findings":[...],
         "generated_at","query_count","budget_hit"}
```

Daemon thread, one advisor at a time, progress after each. A failed advisor does not abort the
batch — it is marked failed with its error and the run continues.

Persist: `insight_run`, `finding`, `evidence_row`, `agent_query_log`, with edges to
`rule_set_version` and `advisor`. `run_id = advisor_sid|from_month|to_month|version_id` — re-running
supersedes rather than duplicating.

---

## C5 · UI

**AI Insights** (`/insights`) — rule-set version selector, Regenerate, Export. Narrative block with
the `◆ AI Generated` chip, then two side-by-side transition cards with tinted headers. Findings
ranked by `|impact_amt|`, each showing title, summary, impact, provenance chip, driver tag, and
`View evidence ›`. Expanding shows the evidence table and, when `rule_key` is set, the source
citation. Pivot toggle By Driver / By Product regroups the same findings — it does not refetch.

**Advisor** (`/advisor`) — advisor selector, Generate Insights, KPI row (Apr, May, Change, rank in
cohort, last generated), then the same narrative and findings scoped to that advisor.

Empty state before any run: "No insights generated yet" with the Generate button. Never a spinner
with no explanation.

---

## C6 · Verification — `scripts/verify_round_c.py`

```
 1. every catalog query executes against mock data and returns the documented columns
 2. a full run for one advisor completes and persists insight_run + findings + evidence
 3. every finding with a non-null impact_amt has a source_query recorded
 4. every finding has >=1 evidence row, or an explicit reason it has none
 5. EVERY number in narrative and bullets appears in the findings   <- the critical check
 6. query_count <= 40; budget_hit set correctly when the ceiling is reached
 7. agent_query_log has one row per tool call, in sequence
 8. re-running the same advisor supersedes rather than duplicating
 9. the Reporter has no graph client in scope (assert by construction)
10. a run against 202604 as from-month handles the baseline correctly (no prior month errors)
11. all-advisors batch: one failing advisor does not abort the rest
12. coverage ratio computed and stored, and absent from every API response
```

**Done when** Generate Insights runs end to end for one advisor, the screen matches the mockup, and
check 5 passes with zero unverified figures.
