# Round D — Client Environment Deployment

Everything between "it works in the Codespace" and "it works on the client machine". V2's single
largest source of lost time was environment divergence; this round exists to spend that time once,
deliberately, in the right order.

**Client environment:** Windows / PowerShell, `uv`, IntelliJ, client artifactory for packages, live
Aurora PostgreSQL (IAM token auth), live TigerGraph, live cdao Azure OpenAI.

---

## D0 · PREFLIGHT — run this FIRST, before copying any code

Every item here can block the entire application. Discovering any of them after the code is moved
wastes the night. **Run all six, record the results, then decide what to deploy.**

### D0.1 Package availability from the client artifactory

```powershell
uv pip install chromadb pdfplumber python-docx python-pptx pyTigerGraph fastapi uvicorn pydantic-settings
```

| Package | Used for | If unavailable |
|---|---|---|
| `chromadb` | Vector store | **Blocker for RAG.** Fall back to TigerGraph 4.2 native vector search, or an in-process numpy cosine index over chunk embeddings persisted as CSV. Decide before Round B ships. |
| `pdfplumber` | PDF text **and tables** | Fall back to `pypdf` — but tables are lost, so rule extraction quality drops sharply. Flag to the client rather than degrade silently. |
| `python-docx` / `python-pptx` | DOCX / PPTX | Those formats become unsupported; PDF still works. |
| `pyTigerGraph` | Graph tier 2 | Tier 3 (RESTPP over `requests`) still works. Not a blocker. |

⚠ V1's `runtime_chroma_validation.json` recorded `"chromadb_import_error": "No module named
'chromadb'"` — chroma may never have run for real in this environment. **Treat this as the single
highest-risk unknown and test it first.**

### D0.2 cdao reachability

```powershell
uv run python -c "from cdao import openai_azure_client; c = openai_azure_client(workspace_id=906313); print('cdao ok')"
```

Then a live chat call and a live embedding call:
```powershell
uv run python scripts/check_cdao.py
```
`scripts/check_cdao.py` must verify, and print, all four:
- chat completion returns text with `temperature=1`, **no** `max_tokens`, `api_version` **omitted**
- embedding returns a vector and its length equals `EMBEDDING_DIM`
- the deployed model name matches `CDAO_MODEL`
- the embedding model name matches `EMBEDDING_MODEL`

**If the embedding dimension is not 3072**, set `EMBEDDING_DIM` to the actual value *before* any
document is indexed. Re-embedding after the fact means re-indexing everything.

### D0.3 TigerGraph reachability and version

```powershell
uv run python scripts/check_tigergraph.py
```
Prints host, version, existing graphs, and whether `phx_dm_pce_practice_demo` already exists.
**Confirm GSQL syntax version is V1** — the DDL and queries are written for it.

### D0.4 Node and frontend build

```powershell
node --version    # 18+ required for Next.js app router
cd frontend; npm install
```
If npm cannot reach the registry, an offline `node_modules` bundle must be carried across. Test the
production build, not just dev: `npm run build`.

### D0.5 Port availability

8001 (API) and 3001 (frontend) must be free. If not, both are configurable via `.env`; the frontend
reads the API base from `NEXT_PUBLIC_API_BASE`.

### D0.6 Record the results

Write `docs/CLIENT_PREFLIGHT.md` with the observed output of every check above — not a summary.
This is the document that tells you which features can ship.

---

## D1 · Configuration switch — Codespace to client

| Variable | Codespace | Client | Effect if wrong |
|---|---|---|---|
| `GRAPH_CLIENT_MODE` | `mock` | `real` | In `mock`, the UI silently serves local CSVs — looks fine, data is fake |
| `TIGERGRAPH_HOST` | — | `https://<host>:14240` | Tier cascade falls through to tier 4 (local) |
| `TIGERGRAPH_GRAPH` | `phx_dm_pce_practice_demo` | same | — |
| `TIGERGRAPH_USER` / `_PASS` | — | set | Auth failure per tier, logged |
| `LLM_MODE` | `mock` | `cdao` | Mock returns templated text, not real narration |
| `CDAO_API_VERSION` | *(blank)* | *(blank)* | **Must stay blank** — the argument is omitted, not empty-stringed |
| `EMBEDDING_MODE` | `mock` | `cdao` | Mock embeddings are deterministic but not semantic; retrieval is meaningless |
| `EMBEDDING_DIM` | `3072` | *(observed in D0.2)* | Dimension mismatch → `_fit_dim` raises loudly. Good. |
| `CHROMA_PATH` | `./chroma` | absolute Windows path | Relative paths resolve against the working directory, which differs under PowerShell |
| `DATA_DIR` | `data/` | `data/real/` | Loads mock CSVs into the live graph |

**A tier-4 (local store) read while `GRAPH_CLIENT_MODE=real` must fail loudly, not serve.** Round A
ported this behaviour — verify it survived.

`/api/health` must report, and the smoke test must assert: graph mode, the tier actually serving,
LLM reachability, embedding reachability, and per-vertex row counts.

---

## D2 · Install the schema on live TigerGraph

Order matters. Run from `docs/tigergraph/`:

```
1. 90_drop_all.gsql        (only if re-installing — drops in exact reverse of create order)
2. 01_vertices.gsql
3. 02_edges.gsql
4. 03_create_graph.gsql
5. loading/*.gsql          (16 vertex jobs + load_edges.gsql)
6. queries/*.gsql          (the 24-query catalog from Round C), then INSTALL QUERY ALL
```

**GSQL V1 constraints — carried from V2, all three cost a round there:**
1. Parameter order is `TYPE name`, not `name TYPE`
2. Traversal targets must be vertex **types**, not pre-defined set variables, and edge aliases are
   required
3. Multi-hop patterns must be split into single-hop `SELECT` statements

**Structural verification in the Codespace does not prove live behaviour.** Every one of the 24
catalog queries must be installed and executed once against live TigerGraph with real parameters,
and the output compared to the local-store implementation of the same query. A query that installs
but returns a different shape than tier 4 will break the app in ways that look like data problems.

`scripts/verify_live_queries.py` runs all 24 and diffs the envelopes.

---

## D3 · Load real data

1. Copilot's extraction writes CSVs to `data/real/{vertices,edges}/` plus `manifest.json`.
2. **Validate before loading:**
   ```powershell
   uv run python scripts/validate_real_data.py
   ```
   - every file in the manifest exists; every file on disk is in the manifest
   - header of each CSV matches the schema catalog exactly — a missing mapped column raises
     `ColumnMismatchError`, never silently drops the attribute
   - row counts match the manifest
   - `acct_key` values are normalised (no leading zeros) — spot-check 100 rows
   - `reason_cd` is `__NONE__` where blank, never empty string
   - every `product_id` resolves to a group; count how many land in `unmapped` and print them
   - no PII columns present (`tax_id`, `mail_addr_*`, `account_name`, `cust_full_nm`)
3. Load: `uv run python scripts/load_real_data.py` — batched per `entity_registry`, checkpointed,
   verifying loaded counts against the manifest and failing loudly on mismatch.
4. Post-load reconciliation:
   ```powershell
   uv run python scripts/verify_real_data.py
   ```
   - monthly aggregates recomputed independently from the transaction CSVs match the graph
   - the April and May cohort totals are of a plausible magnitude (sanity anchor: the client's own
     reference figure implies roughly $363M/month across 10,899 advisors, so a 20-advisor cohort
     should land in the high hundreds of thousands to low millions per month — an order of
     magnitude out means the extraction filtered wrongly)
   - every scenario the demo needs is present: fee reductions above 10% both with and without a
     recorded grid reduction, transfers in and out, accounts opened in scope, accounts zeroed,
     team agreements, at least one advisor above $4MM NNM

**Keep the mock data.** `DATA_DIR` switches between them; the mock set is the fallback if real data
turns out unusable during a demo.

---

## D4 · Windows and PowerShell specifics

- **Line endings.** Every V2 source file was CRLF. Add `.gitattributes` with `* text=auto` and
  `*.csv text eol=lf` so CSVs written on Windows and read by the loader agree. A stray `\r` in the
  last column of a CSV becomes part of the value and silently corrupts a key.
- **Paths.** Never build paths with string concatenation and `/`. Use `pathlib.Path` throughout.
  `CHROMA_PATH` must be absolute on Windows.
- **Commands.** `uv run python -m uvicorn app.api.main:app --port 8001` — `&&` chaining does not
  work in older PowerShell; use `;`.
- **`.env` loading.** Confirm `pydantic-settings` reads `.env` from the working directory the app is
  actually started from, not the repo root.
- **Long paths.** Windows caps at 260 characters unless long paths are enabled. The repo path is
  already deep (`C:\Users\R757680\ds\workspace\...`); keep nesting shallow.

---

## D5 · Smoke test — the sequence that proves it works

`scripts/smoke_client.py`, run in this order. Each step prints PASS/FAIL with the observed value.

```
 1. /api/health -> 200, graph_mode=real, tier in (1,2,3), llm reachable, embedding reachable
 2. /api/advisors -> cohort count matches the manifest
 3. /api/months -> 3 months, April flagged baseline, June flagged partial
 4. /api/transitions -> 2 transitions with non-zero change
 5. /api/product-contribution -> rows sum to subtotals sum to total; share sums to 100%
 6. upload one plan PDF -> chunks created, >=1 has_table=true, all have page_no
 7. search a known phrase -> returns a chunk above 0.30 similarity
 8. extract rules -> >=1 draft with a page citation
 9. approve -> v1 published, v0 superseded, both queryable
10. generate insights for ONE advisor -> run completes, findings persisted with evidence rows
11. every number in the narrative appears in the findings   <- the critical assertion
12. the same advisor re-run supersedes rather than duplicating
13. frontend loads on 3001, all five tabs render, no console errors
```

**Steps 1–5 must pass before anything else is attempted.** If step 1 shows tier 4 while
`GRAPH_CLIENT_MODE=real`, stop — everything downstream is reading fake data.

---

## D6 · Failure playbook

| Symptom | Most likely cause | Check |
|---|---|---|
| Health shows tier 4 in real mode | TigerGraph unreachable or auth failed | `app/graph/tier_log` — it records which tiers were tried and why each failed |
| All revenue figures zero | `reason_cd` empty string instead of `__NONE__`, so nothing is credited | `SELECT DISTINCT reason_cd` in the loaded transaction CSV |
| Product table missing rows | `product_id` not resolving; everything in `unmapped` | `validate_real_data.py` prints the unmapped list |
| Totals an order of magnitude out | Wrong `proc_dt` scope bounds (Round 5: `proc_dt` IS the correct filter), or the team-agreement join fanned out | Compare row counts per month against the extraction manifest |
| Chunks with no page numbers | Parser fell back to `pypdf` because `pdfplumber` is missing | `docs/CLIENT_PREFLIGHT.md` |
| Rules extracted but none compile | Field names in expressions do not match the schema catalog | Compile errors name the field and vertex |
| Narrative contains a figure not in findings | Reporter assertion failed and the fallback did not engage | The run log records the assertion failure |
| Insight run returns nothing | `budget_hit` true at query 1, or the rule set is empty | `agent_query_log` for that `run_id` |

---

## D7 · Definition of done

- `docs/CLIENT_PREFLIGHT.md` exists with observed output for all six D0 checks
- All 24 catalog queries installed and executed against live TigerGraph, envelopes matching tier 4
- Real data loaded, reconciliation passing, scenario coverage confirmed
- `smoke_client.py` passes all 13 steps
- `docs/ROUND_D_COMPLETE.md` written with the actual smoke output pasted
