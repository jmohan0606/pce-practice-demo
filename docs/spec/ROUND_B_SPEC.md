# Round B — Detailed Specification

Supersedes §5 of `BUILD_PLAN.md`. Read with `SCHEMA_SPEC.md` and `docs/ui/mockups.html`.

Three tracks, disjoint directories, safe to run in parallel:
**B1 Dashboard** (`frontend/`, `app/api/routers/dashboard.py`) ·
**B2 RAG** (`app/knowledge/`) ·
**B3 Rules** (`app/rules/`, `app/agents/rule_*.py`)

---

# B1 · Dashboard

## B1.1 API endpoints — exact response shapes

All under `/api`. All read from `phx_dm_pce_monthly_revenue` via the tiered graph client. No
figure is computed in the router; routers shape query results only.

### `GET /api/advisors`
```json
{"advisors":[{"advisor_sid":"V000001","advisor_name":"Sandra Mehta","in_cohort":true}],
 "cohort_count":20}
```
Blank name stays `""` — the UI shows the SID. Never invent a name.

### `GET /api/months?advisor=<sid|all>`
```json
{"months":[{"month_id":"202604","month_name":"Apr 2026","credited_amt":6352980.00,
  "recurring_amt":4147480.00,"non_recurring_amt":2205500.00,"txn_count":18420,
  "trading_days":21,"is_baseline":true,"is_partial":false}]}
```
Ordered by `month_id`. `advisor=all` sums across cohort advisors only (`in_cohort=true`).

### `GET /api/transitions?advisor=<sid|all>`
```json
{"transitions":[{"from_month_id":"202604","to_month_id":"202605",
  "from_amt":6352980.00,"to_amt":6580210.00,
  "change_amt":227230.00,"change_pct":3.58,"direction":"up","txn_count":18420}]}
```
`direction` is `"up"` or `"down"`. `change_pct` rounded to 2dp. One entry per consecutive pair.

### `GET /api/product-contribution?from=202604&to=202605&advisor=<sid|all>&class=<all|RECURRING|NON_RECURRING>`
```json
{"from_month_id":"202604","to_month_id":"202605",
 "sections":[
   {"class_id":"RECURRING","class_name":"Recurring",
    "rows":[{"group_id":"managed_accounts","group_name":"Managed Accounts","display_prefix":"",
             "from_amt":2845120.00,"to_amt":2961480.00,"change_amt":116360.00,
             "change_pct":4.09,"share_pct":45.01,"direction":"up"}],
    "subtotal":{"from_amt":4147480.00,"to_amt":4283490.00,"change_amt":136010.00,
                "change_pct":3.28,"share_pct":65.09}}],
 "total":{"from_amt":6352980.00,"to_amt":6580210.00,"change_amt":227230.00,
          "change_pct":3.58,"share_pct":100.0}}
```

Rules:
- Rows sorted **descending by `to_amt`** within each section.
- `share_pct` is of the **`to` month total**.
- A group with zero in both months is **omitted**. A group with zero in one month is **kept** —
  that is a real signal (something started or stopped).
- `unmapped` always renders if it has any amount, never suppressed.
- Section order: Recurring, then Non-Recurring.

## B1.2 Frontend structure

Next.js app router, port 3001.

```
frontend/
  app/
    layout.tsx              top bar + tab nav (5 tabs), TigerGraph pill
    page.tsx                Dashboard
    insights/page.tsx       AI Insights   (Round C fills; Round B renders empty state)
    advisor/page.tsx        Advisor       (Round C fills; Round B renders KPIs only)
    documents/page.tsx      Documents & Rules
    rules/page.tsx          Rule Versions
  components/
    PageHeader.tsx          title + meta + optional controls slot
    RevenueBarChart.tsx     stacked bars, y-axis, gridlines, SVG arrows, pill labels
    ProductTable.tsx        sections, subtotals, total row
    Chip.tsx                variants: real | derived | tag | aigen | pos | neg
    SourceLink.tsx          the document-citation thread
    EmptyState.tsx
  lib/
    api.ts                  typed fetch wrappers
    format.ts               money, percent, negative-in-parentheses
  styles/tokens.css         copied verbatim from mockups.html :root
```

**`format.ts` is mandatory and used everywhere:**
```ts
money(n)    // 6580210 -> "$6,580,210"   |  -3670 -> "($3,670)"
percent(n)  // 3.58 -> "3.6%"            |  -2.61 -> "(2.6%)"
arrow(n)    // n>0 -> "▲" ; n<0 -> "▼" ; 0 -> "—"
```
Negatives are **always** parentheses, never a minus sign. Zero renders as an em dash, not `$0`.

**Design tokens** come from `mockups.html` `:root` verbatim — do not re-derive colours. Recurring
`#C5B88F`, Non-Recurring `#6699C2`, navy `#16365C`, positive `#157F4C`, negative `#B3261E`.

**Chart behaviour.** Bars scale to a y-axis max of the largest month rounded up to a clean value.
Arrow pills sit between bar tops; the selected pill fills navy and drives the product table below.
Default selection is the **first** transition.

**Filters only where they act** — Dashboard has advisor + product class + Apply; AI Insights has
rule-set version only; Advisor has one advisor selector; Documents and Rule Versions have none.

## B1.3 Definition of done for B1

`scripts/verify_round_b.py` checks:
- Every endpoint returns 200 with the documented keys present
- Product-contribution row totals equal the section subtotal, and subtotals equal the grand total
- `share_pct` values sum to 100.0 ± 0.1
- A recomputation of `change_amt` from `to_amt − from_amt` matches every row
- The 24 groups plus `unmapped` all resolve; no group appears in two sections

---

# B2 · RAG

## B2.1 Parsing — replace V1's parser

V1 used `pypdf`, which returns a flat text stream and destroys tables. Comp plans are mostly tables.

**Use `pdfplumber`** for PDF. It gives per-page text with coordinates **and** `extract_tables()`.

```
app/knowledge/parsing/
  base.py        ParsedDocument, ParsedBlock dataclasses
  pdf_parser.py  pdfplumber
  docx_parser.py python-docx (paragraphs + tables, styles for heading level)
  pptx_parser.py python-pptx (one block per slide, slide title as heading)
```

```python
@dataclass
class ParsedBlock:
    block_type: str      # "heading" | "paragraph" | "table" | "list"
    text: str            # tables rendered as GitHub-flavoured markdown
    page_no: int
    heading_level: int   # 0 for non-headings
    order: int
```

**Heading detection in PDF** (in priority order):
1. Numbered pattern — `^\d+(\.\d+)*\s+\S` → level = count of dots + 1
2. Font size above the page's modal body size, on a short line (< 80 chars)
3. ALL CAPS on a short line

Heading detection is heuristic and will be imperfect. That is acceptable — `section_path` is
provenance, not logic. What must never be wrong is `page_no`.

## B2.2 Chunking algorithm

```
1. Group blocks into sections: a heading starts a section; it runs to the next heading of
   equal or higher level. Blocks before the first heading form section "(preamble)".
2. Each TABLE block becomes its OWN chunk. Never split a table. Never merge a table with
   surrounding prose. Prepend the section heading as context, then the markdown table.
3. Prose within a section accumulates until MAX_CHUNK_CHARS (1800). If the section is longer,
   split at paragraph boundaries with OVERLAP_CHARS (200) of trailing context.
4. Every chunk carries:
     chunk_id       = f"{document_id}-C{index:04d}"
     page_no        = page of its first block
     section_path   = "3.2 Discount Sharing"  (dotted heading trail)
     has_table      = bool
     chunk_index    = running order
```

Constants live in `app/config/settings.py`: `CHUNK_MAX_CHARS=1800`, `CHUNK_OVERLAP_CHARS=200`.

**Why this matters:** a rate table split across two chunks retrieves as two meaningless fragments,
and the rule extracted from it will be wrong. Table integrity is the single most important property
of this stage.

## B2.3 Embedding and storage

- cdao `text-embedding-3-large-1`, `EMBEDDING_DIM=3072`, keep `_fit_dim`'s loud failure.
- Chroma collection `pce_plan_documents`, cosine space, vectors L2-normalised.
- sha256 of extracted text for idempotency — same name + same content is skipped, not re-indexed.
- Graph writes: `phx_dm_pce_document` and `phx_dm_pce_document_chunk` with `chroma_collection`,
  `page_no`, `section_path`, `has_table`.

**Dual-write ordering:** Chroma first, then graph. If the graph write fails, delete the Chroma
entries for that document before raising — never leave orphan vectors.

## B2.4 Endpoints

```
POST   /api/documents/upload      multipart, multiple files
       -> {"documents":[{"document_id","document_name","page_count","chunk_count",
                         "table_chunk_count","status","skipped_duplicate":bool}]}
GET    /api/documents             list with status and counts
DELETE /api/documents/{id}        removes chunks from Chroma AND graph
POST   /api/documents/{id}/extract-rules   triggers the Rule Extractor (B3)
GET    /api/documents/search?q=&top_k=5    retrieval check, returns chunks + similarity
```

Status values: `uploaded → parsed → chunked → embedded → indexed | failed`.

Retrieval floor: cosine similarity **0.30**. Below it, return the honest not-found — and make
**no LLM call at all**. That path is ported from V1 and must survive.

## B2.5 Definition of done for B2

- A PDF containing a table produces at least one chunk with `has_table=true` whose text contains
  the complete table
- Every chunk has a non-null `page_no`
- Re-uploading the same file returns `skipped_duplicate: true` and creates nothing
- Search below threshold returns `found=false` with no LLM call

---

# B3 · Rules

## B3.1 The rule object

```json
{
  "rule_code": "FEE_REDUCTION_SHARING",
  "rule_name": "Sharing a Client Fee Discount",
  "plain_description": "When a client pays more than 10% below the standard fee, the advisor's payout grid moves down one point for every 1% below that threshold...",
  "worked_example": "115 bps standard, 100 bps actual is a 13% reduction, so the grid moves down 3 points.",
  "grain": "account",
  "population": "is_managed = true AND month_id = :month",
  "compute": "round((standard_rate_bps - client_rate_bps) / standard_rate_bps * 100)",
  "trigger": "value > 10",
  "attribute": "grid_points = min(value - 10, 10)",
  "driver_tag": "Fee Rate",
  "provenance": "DOCUMENT_DERIVED",
  "confidence": 0.86,
  "citations": [{"chunk_id":"DOC_ab12-C0031","page_no":4,
                 "section_path":"3.2 Discount Sharing","excerpt":"..."}],
  "status": "DRAFT",
  "unclear_notes": null
}
```

`grain` ∈ `advisor | account | rpg | household | product | transaction`.
`provenance` ∈ `DOCUMENT_DERIVED | OPERATOR_SPECIFIED`.
`status` ∈ `DRAFT | PUBLISHED | SUPERSEDED | NEEDS_INPUT | REJECTED`.

## B3.2 Expression grammar — deliberately narrow

`app/rules/grammar.py` defines and validates. Anything outside this fails to compile.

```
population : condition (AND|OR condition)* | parenthesised
condition  : field OP literal | field IN (list) | field IS [NOT] NULL
OP         : = != > >= < <= LIKE
compute    : agg( expr ) | expr
agg        : sum | count | count_distinct | avg | min | max
expr       : field | number | expr (+|-|*|/) expr | round(expr) | abs(expr)
             | min(expr,expr) | max(expr,expr)
trigger    : value OP number
attribute  : name = expr
field      : a vertex attribute name from schema_catalog.json
:param     : month | advisor_sid | from_month | to_month | threshold
```

**No subqueries, no joins, no free SQL, no function calls outside the list above.** If the LLM
produces something unparseable, the rule gets `status=NEEDS_INPUT` with the parse error attached —
it is never silently dropped and never guessed at.

## B3.3 Compiler

`app/rules/compiler.py` → `compile_rule(rule) -> CompiledRule | CompileError`

1. Parse each expression against the grammar
2. Resolve every `field` against `docs/tigergraph/schema_catalog.json` for the declared `grain` —
   an unknown field is a compile error naming the field and the vertex it was sought on
3. Type-check: arithmetic needs numeric fields; comparisons need compatible types
4. Emit a query plan: `{vertex, filters, aggregate, group_by, params}`

**An uncompilable rule cannot be approved.** The UI shows the compile error on the rule card.

## B3.4 Rule Extractor

Input: all chunks of one document. Runs **per document, in batch** — never per request. Chunks are
processed in windows of 6 with 1 chunk of overlap so a rule spanning a boundary is still seen whole.

System prompt must state:
- Extract **every** distinct provision that could define, qualify, cap, exclude or time-bound a
  revenue or compensation outcome. Exhaustiveness matters more than precision.
- One rule per provision. Do not merge two provisions; do not split one.
- Use only these expression forms: *(grammar inlined)*
- Field names must come from this list: *(field list from schema_catalog.json injected)*
- If a threshold, rate or date is referenced but not stated, set `status: NEEDS_INPUT` and put what
  is missing in `unclear_notes`. **Never invent a number.**
- Every rule must cite the chunk it came from.
- Return a JSON array only. No prose, no markdown fences.

Output validated against the schema; invalid entries are kept as `NEEDS_INPUT` with the error, never
discarded silently.

## B3.5 Rule Conflict Auditor

Runs before publishing, over `{new drafts} × {live PUBLISHED rules}`.

Conflict when **any** of:
1. Same `rule_code`
2. Same `grain` **and** population field sets overlap **and** triggers can both fire on one row
3. Same `driver_tag` and overlapping population

Output per conflict:
```json
{"conflict_type":"SAME_RULE_CODE","new_rule":"...","existing_rule":"...",
 "proposed_resolution":"SUPERSEDE|COEXIST|MERGE","reasoning":"...",
 "new_citation":{...},"existing_citation":{...}}
```

**Never applies a resolution.** It proposes; a human approves. Precedence order — later effective
date wins, explicit supersession language wins over date, a plan document outranks an FAQ — is a
**proposal input only**, never automatic.

## B3.6 Versioning

- `POST /api/rules/publish` → new `phx_dm_pce_rule_set_version`, `version_no` incremented,
  `status=PUBLISHED`; the previous version becomes `SUPERSEDED`
- Approved rules are copied into the new version. Rules are **immutable**; an edit creates a new
  rule row in a new version.
- Nothing is ever deleted.
- `GET /api/rules?version=<id|latest>`, `GET /api/rules/versions`,
  `POST /api/rules/{key}/approve`, `POST /api/rules/{key}/edit`, `POST /api/rules/conflicts/check`

## B3.7 The v0 seed — write these exactly

Seeded at startup if no version exists. `provenance: OPERATOR_SPECIFIED`, `version_no: 0`,
`status: PUBLISHED`.

| rule_code | grain | plain_description | population / compute / trigger |
|---|---|---|---|
| `NEW_ACCOUNT` | account | An account opened during the period counts as new for the month its first revenue appears. | `opened_in_scope = true` / `sum(credited_amt)` / `value > 0` |
| `ACCOUNT_TRANSFERRED_IN` | account | An account moved to this advisor from another. Checked **before** lost, so a transfer is never counted as a loss. | `to_advisor_sid = :advisor_sid` / `count(*)` / `value > 0` |
| `ACCOUNT_TRANSFERRED_OUT` | account | An account that moved from this advisor to another. Not a lost account. | `from_advisor_sid = :advisor_sid` / `count(*)` / `value > 0` |
| `LOST_ACCOUNT` | account | An account whose balance fell to zero, or which had revenue in the prior month and none now — **and which did not transfer**. | `is_zero_balance = true AND present_prior_month = true` / `sum(credited_amt)` / `value > 0` |
| `FEE_REDUCTION_SHARING` | account | *(as B3.1)* | *(as B3.1)* |
| `PARTIAL_PERIOD` | advisor | A month with fewer trading days than the one before it will show lower revenue for reasons unrelated to the book. | `is_partial = true` / `trading_days` / `value < 21` |

**Ordering matters.** `ACCOUNT_TRANSFERRED_OUT` must be evaluated before `LOST_ACCOUNT`, and the
transferred accounts excluded from the lost population. Encode this as
`evaluation_order: 10,20,20,30,40,50` on the rule and honour it.

`LOST_ACCOUNT` cannot fire in April (baseline, no prior month) — the rule must return an empty
result there rather than an error.

## B3.8 Definition of done for B3

- Uploading a PDF and running extract-rules produces ≥1 draft rule with a page citation
- Every draft either compiles or carries `NEEDS_INPUT` with a readable reason
- A deliberately conflicting rule is flagged, not applied
- Approving mints v1; v0 becomes SUPERSEDED; both remain queryable
- The v0 seed exists at first startup with all six rules

---

# Round B verification — `scripts/verify_round_b.py`

Each check prints PASS/FAIL and the observed value.

```
B1  1. /api/advisors, /api/months, /api/transitions, /api/product-contribution return 200
    2. product rows sum to section subtotals; subtotals sum to grand total
    3. share_pct sums to 100.0 ± 0.1
    4. change_amt == to_amt - from_amt on every row
    5. all 24 groups + unmapped resolve; no group in two sections
    6. money()/percent() render negatives in parentheses (unit test)
B2  7. table-bearing PDF -> >=1 chunk with has_table=true containing the whole table
    8. every chunk has a non-null page_no and a section_path
    9. re-upload of identical content -> skipped_duplicate=true, no new chunks
   10. search below 0.30 -> found=false and zero LLM calls (assert with a spy)
B3 11. grammar rejects free SQL, subqueries and unknown functions
   12. compiler rejects an unknown field, naming field and vertex
   13. v0 seed present with 6 rules, all PUBLISHED, provenance OPERATOR_SPECIFIED
   14. evaluation_order puts TRANSFERRED_OUT before LOST_ACCOUNT
   15. LOST_ACCOUNT on 202604 returns empty, not an error
   16. a same-rule_code draft is flagged as a conflict and is NOT auto-applied
   17. publishing mints a new version; the prior version is SUPERSEDED and still queryable
```
