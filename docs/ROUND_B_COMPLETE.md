# Round B Complete

Built per `docs/spec/ROUND_B_SPEC.md` (supersedes BUILD_PLAN §5). Three tracks ran in
parallel in disjoint directories; the main thread wired the shared surfaces
(`app/api/main.py`, the v0 seed startup call, `scripts/verify_round_b.py`, docs) and
additionally wired `normalize_account_key` into the ingestion path.

## Delivered

### B1 · Dashboard
- `app/api/routers/dashboard.py` — `/api/advisors`, `/api/months`, `/api/transitions`,
  `/api/product-contribution` with the exact B1.1 shapes; routers shape only — all figures
  come from mock-tier graph queries in `app/graph/queries/pce_dashboard.py`
  (`pce_dashboard_advisors/months/transitions/product_contribution`).
- `frontend/` restructured to the B1.2 layout exactly (Round A tailwind/shadcn shell removed):
  5 pages, the 6 spec components (+ `TopNav.tsx` client component so the layout stays a server
  component), `lib/{api,format}.ts`, `styles/tokens.css` copied verbatim from `mockups.html :root`.
  `money()/percent()/arrow()` used everywhere — negatives always parentheses, zero renders "—".
  Chart: stacked bars (Recurring `#C5B88F` / Non-Recurring `#6699C2`), clean y-axis ceiling,
  arrow pills between bar tops, selected pill navy and driving the product table, first
  transition selected by default. Filters only where they act. `npm run build` passes
  (Next 15, no type errors); all 5 pages served 200 on :3001.

### B2 · RAG
- `app/knowledge/parsing/` — pdfplumber / python-docx / python-pptx parsers emitting
  `ParsedBlock` per B2.1; tables rendered as GitHub-flavoured markdown; PDF heading priority
  numbered → font-size → ALL-CAPS; `page_no` always real (DOCX pins 1 — no fixed pagination).
- `app/knowledge/chunker.py` — B2.2 `SectionChunker`: heading-bounded sections, "(preamble)",
  tables as their own never-split chunks with the section heading prepended, prose to
  `CHUNK_MAX_CHARS=1800` with `CHUNK_OVERLAP_CHARS=200` (constants in settings),
  `chunk_id = {document_id}-C{index:04d}` + page_no/section_path/has_table/chunk_index.
- `app/knowledge/knowledge_service.py` — full status lifecycle
  uploaded→parsed→chunked→embedded→indexed|failed; sha256 idempotency; Chroma-first dual write
  into `pce_plan_documents` (cosine, L2-normalised) then `phx_dm_pce_document` /
  `phx_dm_pce_document_chunk` (+ `chunk_of_document` edges); on graph failure the document's
  Chroma entries are deleted before raising (rollback tested — zero orphans); delete removes
  from Chroma AND graph.
- `app/api/routers/documents.py` — the five B2.4 endpoints. Retrieval floor 0.30 with the
  honest not-found and **no LLM call** below it (spy point:
  `app.knowledge.rag_service.get_llm_client`). `extract-rules` calls B3's extractor lazily.
- `scripts/make_test_pdf.py` — deterministic table-bearing comp-plan PDF, reused by verify.

### B3 · Rules
- `app/rules/grammar.py` — B3.2 tokenizer + recursive-descent parsers; everything outside the
  grammar fails with a targeted `GrammarError`.
- `app/rules/compiler.py` — field resolution against `schema_catalog.json` per grain (errors
  name field AND vertex), type-checking, query-plan emission; uncompilable rules can't be approved.
- `app/rules/{evaluator,service,store,seed}.py` — plan execution on the local store (baseline
  guard: LOST_ACCOUNT on 202604 returns empty with a reason, not an error; transfer-matched
  accounts excluded from later account-grain populations per evaluation_order 10,20,20,30,40,50);
  immutable `RuleStore` with graph mirroring to `phx_dm_pce_rule(_set_version)`; idempotent
  `ensure_v0_seed()` with the six B3.7 rules exactly (called at startup in `main.py` and
  lazily by the router).
- `app/agents/rule_extractor.py` — per-document batch, windows of 6 chunks with 1 overlap,
  B3.4 system prompt (grammar + schema field list inlined, never invent a number); invalid or
  unparseable output kept as NEEDS_INPUT, never dropped. Entrypoint:
  `extract_rules_for_document(document_id, chunks)`.
- `app/agents/rule_conflict_auditor.py` — deterministic detection of the three B3.5 conflict
  conditions, LLM only refines proposal/reasoning; **proposals only, nothing auto-applied**.
- `app/api/routers/rules.py` — list/versions/publish/conflicts/approve/edit/evaluate per B3.6.

### Main thread
- `app/api/main.py` — dashboard/documents/rules routers registered; `ensure_v0_seed()` at startup.
- **`normalize_account_key` wired into ingestion**: the entity registry derives
  `normalize_columns` from the manifest (vertex `acct_key`/`acct_src_key` columns + edge
  endpoints typed `phx_dm_pce_account`; `acct_src_raw` deliberately raw for audit) and
  `IngestionService` normalises those values before primary key, validation, delta hash and
  graph write. Verified: padded keys (`"  000ACCT_PAD_1  "` → `ACCT_PAD_1`) land normalised;
  re-ingesting clean mock data shows 0 churn (all rows SKIP).
- `scripts/verify_round_b.py` — the 17 spec checks.

## Verification output

Actual output of `python3 scripts/verify_round_b.py` (build-box modes EMBEDDING_MODE=mock,
LLM_MODE=mock; mock graph tier 4):

```
PASS  B1-1. the four dashboard endpoints return 200 with documented keys — statuses=[200, 200, 200, 200], missing keys=none
PASS  B1-2. product rows sum to section subtotals; subtotals to grand total — rows->subtotals ok=True, subtotals->total ok=True
PASS  B1-3. share_pct sums to 100.0 ± 0.1 — sum=100.01
PASS  B1-4. change_amt == to_amt - from_amt on every row — 25 rows checked, mismatches=none
PASS  B1-5. all 24 groups + unmapped resolve; no group in two sections — resolved 25/25 seeded groups, in-two-sections=none
PASS  B1-6. money()/percent() render negatives in parentheses — observed '($3,670)|(2.6%)|$6,580,210|3.6%|—|▼|▲|—'
PASS  B2-7. table-bearing PDF -> >=1 chunk with has_table=true containing the whole table — 4 chunks, 1 table chunks, 1 hold all 20 table cells intact
PASS  B2-8. every chunk has a non-null page_no and a section_path — 4 chunks; pages=[1, 2]; missing=none
PASS  B2-9. re-upload of identical content -> skipped_duplicate=true, no new chunks — skipped_duplicate=True, chunks 4 -> 4
PASS  B2-10. search below 0.30 -> found=false and zero LLM calls (spy) — found=False, llm_calls=0
PASS  B3-11. grammar rejects free SQL, subqueries and unknown functions — rejected 3/3; wrongly accepted=none
PASS  B3-12. compiler rejects an unknown field, naming field and vertex — [fields] unknown field 'made_up_field' on vertex 'phx_dm_pce_account_month' (grain 'account'; also searched: p
PASS  B3-13. v0 seed present with 6 rules, all PUBLISHED, provenance OPERATOR_SPECIFIED — version_no=0, rules=['ACCOUNT_TRANSFERRED_IN', 'ACCOUNT_TRANSFERRED_OUT', 'FEE_REDUCTION_SHARING', 'LOST_ACCOUNT', 'NEW_ACCOUNT', 'PARTIAL_PERIOD']
PASS  B3-14. evaluation_order puts TRANSFERRED_OUT before LOST_ACCOUNT — TRANSFERRED_OUT=20, LOST_ACCOUNT=30 (full order=[10, 20, 20, 30, 40, 50])
PASS  B3-15. LOST_ACCOUNT on 202604 returns empty, not an error — status=200, matched_count=0, reason=month 202604 is the baseline month — no prior month exists,
PASS  B3-16. a same-rule_code draft is flagged as a conflict and NOT auto-applied — conflicts=1 (SUPERSEDE), published rule untouched=True
PASS  B3-17. publishing mints a new version; prior is SUPERSEDED and still queryable — v1 PUBLISHED with 6 rules; v0 status=SUPERSEDED, still returns 6 rules

17/17 checks passed
```

Regression: `python3 scripts/verify_round_a.py` → **25/25 checks passed** (8b widened to
`>= 16` vertex types — the Round B rule seed honestly adds `phx_dm_pce_rule` and
`phx_dm_pce_rule_set_version` counts to health; see DECISIONS.md).

## Deviations / notes (also in DECISIONS.md)
- Transition `txn_count` = to-month count; `change_pct` null when `from_amt` is 0 (UI shows "—").
- Partial-June label renders "· 12 Trading Days" + an honest note — never a fabricated
  data-through date (the graph has none).
- Mockup controls that act on nothing (T-3/T-6, Group by, Export) omitted per
  "filters only where they act".
- `section_path` is the full heading trail joined with `" > "` (spec example is the leaf).
- **pdfplumber was NOT installed on this box** despite the confirmed-available list — installed
  0.11.10 and added to the `rag` extra in `pyproject.toml`. The other four confirmed packages
  were present.
- LOST_ACCOUNT seeded literally per B3.7 even though its trigger can't fire on the mock data's
  zero-balance rows (their current-month credited_amt is 0) — "write these exactly" wins;
  the immutable-edit flow exists for operator reinterpretation.
- Rule persistence: full rule objects in `app/rules/store.py`, schema-subset mirrored to the
  graph on every write.

## Not done / carried forward
- AI Insights page is an empty state; Advisor page is KPIs-only (Round C fills both).
- Extractor quality untestable end-to-end here (LLM_MODE=mock) — windowing, prompt content,
  validation and NEEDS_INPUT paths are verified deterministically; real extraction needs the
  client's cdao environment.
- GSQL for the app-written vertices still structurally verified only (no live TigerGraph).
