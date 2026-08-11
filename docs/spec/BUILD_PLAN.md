# pce-practice-demo — Build Plan

Everything Claude Code needs. Read with `docs/spec/SCHEMA_SPEC.md`, which is the authoritative
graph contract, and `docs/ui/mockups.html`, which is the authoritative UI reference.

---

## 1 · What this is

A **Practice Management Dashboard** for JPMC/Chase Wealth Management. It shows month-over-month
credited revenue for a cohort of financial advisors, then explains what drove the change — with the
explanation derived from the firm's own compensation-plan documents rather than from hardcoded logic.

**Stack:** TigerGraph (graph `phx_dm_pce_practice_demo`) + FastAPI (port 8001) + Next.js (port 3001)
+ Chroma (document vectors) + cdao Azure OpenAI.

**Scope:** Apr–Jun 2026, 10–20 advisors. April is the baseline month.

### The one principle that governs everything

**The AI decides what counts and why. Code does the counting.**

Agents choose which tables to open, what to suspect, what to investigate next, what is significant,
and how to say it. But every number that reaches the screen is the return value of a graph query,
never a figure produced by a language model. These documents govern advisor compensation — a number
nobody can reproduce is not a quality problem, it is a regulatory one.

This is **not** V2. There is no fixed driver list, no MIX plug, no reconciliation requirement, no
formula-and-operands evidence modal. Findings are independent observations and are **not** expected
to sum to the total change.

---

## 2 · Project setup

### Layout (already scaffolded)

```
app/
  api/          FastAPI app, routers, middleware
  agents/       rule_extractor, rule_conflict_auditor, insights_miner, insights_reporter
  graph/        tiered TigerGraph client            <- port from V2
  ingestion/    manifest-driven CSV loader          <- port from V2
  knowledge/    RAG: parser, chunker, chroma, retrieval   <- port from V1, then rework
  rules/        rule model, compiler, versioning    <- new
  revenue/      product model, monthly aggregation  <- new
  llm/          adapters + per-role config          <- port from V2
  shared/       logging, ids, responses             <- port from V2
  config/       settings
frontend/       Next.js
docs/spec/      SCHEMA_SPEC.md, BUILD_PLAN.md
docs/ui/        mockups.html
docs/tigergraph/ generated DDL + loading jobs + query catalog
docs/data/      source_catalog.json, extraction SQL
scripts/        verification scripts
data/           vertices/ edges/ manifest.json
reference/v2/   V2 codebase — READ ONLY, never edit, never import from
reference/v1/   V1 codebase — READ ONLY
```

### Port list — copy these, do not import across `reference/`

Copy the file into its new home, then change `phx_dm_v2_` prefixes to `phx_dm_pce_` and strip any
V2 domain logic. **Verify each path exists before copying**; the checkout may differ from what is
listed here.

| From `reference/v2/` | To | Notes |
|---|---|---|
| `app/graph/tiered_client.py` | `app/graph/` | 4-tier cascade: MCP → pyTigerGraph → RESTPP → local store |
| `app/graph/client.py`, RESTPP + MCP adapters | `app/graph/` | keep the identical result envelope per tier |
| `app/graph/foundation_store.py` (or equivalent) | `app/graph/` | local fallback store |
| `app/ingestion/*` | `app/ingestion/` | manifest loader, checkpoints, delta, validation, upsert |
| `app/llm/client.py` | `app/llm/` | 5 adapters incl. cdao |
| `app/llm/roles.py` | `app/llm/` | per-role config resolution |
| `app/llm/embedding_client.py` | `app/llm/` | incl. `_fit_dim` guard |
| `app/shared/*` | `app/shared/` | logging, ids, responses |
| `app/api/middleware/*` | `app/api/middleware/` | correlation ids, error handlers |
| `app/config/settings.py` | `app/config/` | **prune dead V1 keys**; keep chroma + embedding keys |
| `frontend/` layout, ui, design-system, charts, lib/api | `frontend/` | design tokens, chart components |

| From `reference/v1/` | To | Notes |
|---|---|---|
| `app/knowledge/chroma_client.py` | `app/knowledge/` | PersistentClient, cosine space |
| `app/knowledge/vector_store.py` | `app/knowledge/` | upsert/search, similarity = 1 − distance |
| `app/knowledge/document_parser.py` | `app/knowledge/` | **rework** — see Round B |
| `app/knowledge/rag_service.py` | `app/knowledge/` | keep the honest not-found path |
| `app/services/knowledge_management_service.py` | `app/knowledge/` | keep sha256 idempotency |

**Do NOT port:** `app/v2/**` (attribution, eligibility, taxonomy, commentary, anomalies, assistant),
`app/guardrails/numeric_validation.py`, V2 vertex names, the 12-driver engine, reason-code
eligibility beyond the credited-revenue rule below.

### Environment

`.env` at repo root:

```
GRAPH_CLIENT_MODE=mock            # mock | real
TIGERGRAPH_HOST=
TIGERGRAPH_GRAPH=phx_dm_pce_practice_demo
TIGERGRAPH_USER=
TIGERGRAPH_PASS=

LLM_MODE=cdao
CDAO_WORKSPACE_ID=906313
CDAO_MODEL=gpt-5
CDAO_API_VERSION=                 # BLANK on purpose — see below
AZURE_OPENAI_API_KEY=

EMBEDDING_MODE=cdao
EMBEDDING_MODEL=text-embedding-3-large-1
EMBEDDING_DIM=3072
CHROMA_PATH=./chroma

API_PORT=8001
FRONTEND_PORT=3001
```

**cdao GPT-5 compatibility — three rules, learned the hard way:**
1. When `api_version` is blank, **omit the argument entirely** — do not pass an empty string
2. `temperature=1` — no other value is accepted
3. **Never send `max_tokens`**

Config is the only signal. Never inspect the model name to decide behaviour.

### Run

```bash
uv run uvicorn app.api.main:app --reload --port 8001
cd frontend && npm run dev        # port 3001
```

---

## 3 · Requirements

### 3.1 Credited revenue

```
credited_amt = SUM(post_split_credited_amt) WHERE reason_cd IS NULL OR trim(reason_cd) = ''
```

`post_split_credited_amt` **already includes the team split** — verified, `split_pct ==
prm_share_pct`. Never re-apply a team share. Never join trade rows to team agreements when summing
revenue; it fans out one row per secondary member.

Rows with a populated reason code are still loaded as `non_credited_amt` so agents can investigate
eligibility movement. They are excluded from credited totals.

### 3.2 Product model

24 display groups, seeded from `SCHEMA_SPEC.md §4`. Two independent attributes per group:

- **Aggregation group** — the display row (Managed Accounts, TWHS – Equities, …)
- **Revenue class** — Recurring or Non-Recurring

These are **parallel dimensions, not a hierarchy**. UMA displays as its own row *and* classes as
Recurring. Do not derive one from the other.

Grain is `product_cd`, except `ELIS` (Equities / Options) and `LEND` (Security Based Lending /
Margin), which split on `product_sub_cd`. Products absent from the seed keep their
`level_two_product` name and land in group `unmapped` — visible, never silently dropped.

Filter `product_hierarchy` to `grid_type = 'PRODUCT_TYPE'`.

### 3.3 Screens — build against `docs/ui/mockups.html`

**Dashboard.** Static stacked bar chart (tan Recurring / blue Non-Recurring) with curved arrows and
pill labels between months. Selecting an arrow loads the views beneath. Product table: Apr, May,
Change, Change %, % Share of Total, grouped into Recurring and Non-Recurring with subtotals and a
grand total.

**AI Insights.** Short narrative (two bolded sentences) plus four bullets, then findings ranked by
impact in two side-by-side transition cards. Pivot toggle: By Driver / By Product. Each finding
expands to evidence rows and, where a rule drove it, a citation back to the document page.

**Advisor.** Same pattern scoped to one advisor, with KPIs, a Generate Insights button, and a
last-generated timestamp.

**Documents & Rules.** Multi-file upload (drop zone + Browse), extraction status, draft rules in
plain English with a worked example and a collapsed Technical Detail block, and Approve / Edit /
Compare actions.

**Rule Versions.** Published, superseded and seeded versions with rule counts and insight counts.

UI rules: Title Case throughout; negatives in parentheses; filters only on screens where they act
(Dashboard has advisor + product; AI Insights has rule-set version only; Advisor has one advisor
selector; Documents and Rule Versions have none); TigerGraph status pill lives in the top bar.

### 3.4 The four agents

| Agent | Runs when | Input | Output |
|---|---|---|---|
| **Rule Extractor** | Document uploaded | Chunks | Draft rules + page citations |
| **Rule Conflict Auditor** | Before publishing | Drafts + live rules | Overlaps flagged, resolution proposed |
| **Insights Miner** | Generate Insights | Rules + graph query tools | Findings with numbers + evidence rows |
| **Insights Reporter** | After mining | Findings only | Narrative + bullets |

**The Reporter never sees the graph.** It only receives findings the Miner already produced, so it
cannot introduce a figure that was never computed. That separation is the enforcement mechanism.

**Insights Miner detail.** It is the only agent with a loop. Tools: `run_graph_query`, `get_schema`,
`search_documents`. No fixed sequence, no predetermined driver list. It queries, reads results,
forms a hypothesis, queries again, follows what surprises it, stops when the story holds.

Rules loaded into its context tell it what matters in this business — fee reduction above 10% is a
sharing event, transfers matter, $4MM NNM is a threshold — so it investigates like someone who has
read the comp plan rather than a stranger reading unfamiliar tables.

**Query budget: 40 per advisor**, logged in `phx_dm_pce_agent_query_log`, with `budget_hit` set on
the run when the ceiling is reached. Visible, never silent.

### 3.5 Where surprising findings come from

Three deterministic sources, all document-driven:

1. **Exhaustive evaluation** — every advisor × product × rule is thousands of checks nobody reviews
2. **Cohort deviation** — a rule firing for one advisor far above peer rate
3. **Expected vs recorded divergence** — the plan says a grid reduction should apply; the data
   records none. This is the strongest one: firmwide, ~11,205 accounts compute above 10% reduction
   while only ~99 carry a recorded `grid_reduction`.

---

## 4 · Round A — Foundation and data

**Goal:** the API starts, the graph schema installs, mock data loads, monthly aggregates are
correct.

1. Port everything in §2's port list. Rename prefixes to `phx_dm_pce_`. Delete V2 domain logic.
2. Generate `docs/tigergraph/` from `SCHEMA_SPEC.md`: `01_vertices.gsql`, `02_edges.gsql`,
   `03_create_graph.gsql`, `90_drop_all.gsql` (reverse create order), and a loading job per entity
   with **`QUOTE="double"`** — without it JSON columns shear at the first comma.
3. `app/revenue/products.py` — seed the 24 groups from `SCHEMA_SPEC.md §4`, plus `resolve_product`
   mapping `(product_cd, product_sub_cd)` to a group. Unmapped products go to `unmapped`, never
   dropped.
4. `app/revenue/aggregation.py` — build `phx_dm_pce_monthly_revenue` from transactions.
   `mr_id = advisor_sid|month_id|product_id`.
5. Mock data generator: 20 advisors × 3 months × the full product set, written to
   `data/vertices/` and `data/edges/` with a `manifest.json` carrying row counts. Include the
   scenarios the demo needs — accounts opened in Q2, accounts zeroed, transfers in and out, fee
   reductions above 10% with and without a recorded grid reduction, team agreements.
6. Ingestion loads the mock CSVs through the ported pipeline and verifies counts against the
   manifest. Mismatch fails loudly.
7. `GET /api/health` reporting graph tier, LLM reachability, row counts per vertex.
8. `scripts/verify_round_a.py` printing PASS/FAIL per check.

**Constraints.** Account keys are normalised with `ltrim(trim(x),'0')` in **one** shared function
used everywhere. Every per-entity primary key embeds its scope. TigerGraph 4.2.2 GSQL V1: parameter
order is `TYPE name`; traversal targets must be vertex types with edge aliases; multi-hop patterns
must be split into single-hop SELECTs.

**Done when:** `verify_round_a.py` passes, `/api/health` returns green, and the monthly totals
recomputed independently from the transaction CSVs match the aggregate vertices.

---

## 5 · Round B — Dashboard, RAG, rules

**Goal:** the dashboard renders real numbers; documents produce reviewable rules.

**Dashboard**
1. `GET /api/months`, `/api/transitions`, `/api/product-contribution?from=&to=&advisor=`
2. Bar chart with stacked segments, curved SVG arrows, pill labels, selectable transitions
3. Product table exactly as `mockups.html`: sections, subtotals, grand total, Title Case,
   parenthesised negatives, colour-coded and bolded changes
4. Filters only where they act

**RAG**
5. Port V1's Chroma client and vector store as-is.
6. **Rework the parser and chunker.** V1 used fixed 900-character windows, which slice rate tables
   in half and orphan them from their headers. Comp plans are mostly tables. Chunk on section
   boundaries, keep tables whole, and carry `page_no` and `section_path` on every chunk — those
   become the citation on every rule.
7. Embedding via cdao `text-embedding-3-large-1` at 3072 dims. Keep `_fit_dim`'s loud failure on
   dimension mismatch. Keep sha256 content-hash idempotency.
8. Upload endpoint accepting multiple files; `phx_dm_pce_document` and `_document_chunk` written to
   the graph with a `chroma_collection` pointer.

**Rules**
9. Rule object model — `population`, `compute`, `trigger`, `attribute`, plus `plain_description`
   and `worked_example` for the UI. Narrow enough to compile; wide enough for every rule the comp
   plans actually state.
10. **Rule Extractor** — one pass per document. Asks for exhaustiveness, one rule per provision, and
    an explicit `UNCLEAR` flag rather than a guess. Emits drafts with citations.
11. **Rule Conflict Auditor** — flags same `rule_code` or overlapping population against the live
    set, shows both with both citations, proposes a resolution. **Never applies silently.**
12. Compiler validating that every referenced field exists in the graph schema. An uncompilable rule
    cannot be approved.
13. Versioning: approve mints a `rule_set_version`; edits mint a new version; supersede, never delete.
14. Documents & Rules screen and Rule Versions screen per the mockup.
15. Seed **v0** with the operator-specified account lifecycle rules, provenance
    `OPERATOR_SPECIFIED`: new = `account_open_dt` in scope; lost = zero balance or absent versus
    prior month; moved to another advisor = inherited, **checked before lost** so a transfer is not
    counted as a loss.

**Done when:** the dashboard matches the mockup on mock data, a PDF upload produces reviewable
rules with page citations, and approving mints v1.

---

## 6 · Round C — Agents and insights

**Goal:** Generate Insights produces findings with evidence, narrated and persisted.

1. **Insights Miner** — the agent loop with its three tools, 40-query budget, every query logged.
2. Findings persisted to `phx_dm_pce_finding` with `impact_amt`, `driver_tag`, optional `rule_key`,
   and **evidence rows kept from the query that produced them**. Never discard the rows after
   reading a count — re-running an agentic loop will not reproduce the same queries.
3. **Insights Reporter** — receives findings only. Produces the narrative and bullets. A figure
   appearing in prose that is not in the findings is a bug; assert it.
4. Async run: `POST /api/insights/generate` → daemon thread → `GET /api/insights/status/{run_id}`,
   with the progress overlay. Per-advisor and all-advisors buttons.
5. AI Insights screen and Advisor screen per the mockup: narrative, bullets, ranked findings in two
   transition cards, By Driver / By Product pivot, evidence expansion, document citations.
6. `scripts/verify_round_c.py` — asserts every figure in a narrative traces to a stored finding.

**Done when:** Generate Insights runs end to end for one advisor and the screen matches the mockup.

---

## 7 · Working rules for every round

- **Verify before claiming.** Do not report a file as ported without reading it back. Do not report
  a check as passing without running it.
- **Fail loudly.** A missing column, a tier fallback while `GRAPH_CLIENT_MODE=real`, a row count
  mismatch — all raise. Silent degradation is the failure mode that cost V2 the most time.
- **No invented data.** A blank advisor name stays blank. An unmapped product shows as unmapped.
- **`reference/` is read-only.** Copy files out; never import across; never edit in place.
- **One round, one commit.** Write `docs/ROUND_<X>_CHANGED_FILES.md` listing every file touched.

---

## 8 · State tracking — required, not optional

A session can be interrupted at any point: token limits, a dropped connection, a reset. These files
are how work resumes without re-deriving context, and how a **brand-new session** picks up cheaply
instead of re-reading the whole repo.

### `docs/PROGRESS.md` — the living state file

**Create it as the first action of every round. Update it after every completed task, not at the
end.** If the session dies mid-round, this file is the only thing that knows where it stopped.

Structure:

```markdown
# Build Progress

## Current position
Round: A
Task: 5 of 8 — mock data generator
Last updated: <timestamp>

## Task checklist
- [x] 1. Port app/graph from reference/v2
- [x] 2. Port app/ingestion
- [x] 3. Generate GSQL DDL from SCHEMA_SPEC
- [x] 4. Product model + 24 group seed
- [ ] 5. Mock data generator          <- IN PROGRESS
      Done: advisor, account, product, month vertices
      Next: revenue_transaction, then monthly_revenue
- [ ] 6. Ingestion loads mock CSVs
- [ ] 7. /api/health
- [ ] 8. verify_round_a.py

## Verified working
- FastAPI starts on 8001
- 24 vertex DDL files generate cleanly
- <only list what was actually run and observed>

## Known broken / deferred
- <anything left in a non-working state, with the reason>

## Notes for the next session
- <what a fresh session needs to know that is not in the spec>
```

Rules for this file:
- **Never mark a task complete without running it.** A checked box means observed, not intended.
- "Verified working" holds only things actually executed. If it was not run, it does not go there.
- Anything left broken goes in "Known broken" — silence is worse than a bad status.

### `docs/DECISIONS.md` — append-only

Every decision made during the build that the spec did not cover. One entry per decision:

```markdown
## <date> · Round A · <short title>
Context: <what was ambiguous>
Decision: <what was chosen>
Reason: <why>
Reversible: yes/no
```

This is what stops a later session from silently contradicting an earlier one, and what tells the
reviewer where the spec was thin.

### `docs/ROUND_<X>_COMPLETE.md` — written at the end of each round

```markdown
# Round <X> Complete

## Delivered
<what now works, one line each>

## Verification output
<paste the ACTUAL output of the verify script — not a summary, not a claim>

## Files created
## Files modified

## Not done / carried forward
<anything in scope that did not land, and why>

## For the next round
<what round X+1 needs to know: interfaces, gotchas, assumptions made>
```

### Resuming after a disruption

A new session's **first action** is to read, in this order:
`docs/PROGRESS.md` → `docs/DECISIONS.md` → the latest `docs/ROUND_*_COMPLETE.md` → then only the
spec sections still relevant. Do not re-read the whole repo; that is what these files exist to
prevent.

Then continue from the exact task marked IN PROGRESS. Do not restart the round.
