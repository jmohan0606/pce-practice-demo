# Running the Demo in the Client Environment — Mock Mode

For showing the client something before real data is loaded. **No TigerGraph, no PostgreSQL, no
extraction.** The app runs entirely on the bundled mock dataset, with real cdao for the AI parts.

Roughly 20 minutes if the packages install cleanly.

---

## What mock mode means

| Layer | Mock mode | Note |
|---|---|---|
| Graph data | Local CSVs in `data/vertices` and `data/edges`, served by the tier-4 foundation store | 20 advisors, Apr–Jun 2026, ~2,190 transactions |
| TigerGraph | **Not used** | No schema install, no connection needed |
| PostgreSQL | **Not used** | No IAM token, no extraction |
| LLM | **Real cdao** | So the AI insights are genuine, not canned |
| Embeddings | **Real cdao** | So document upload and rule extraction work |

The numbers on screen are fabricated but internally consistent — totals reconcile, rules fire,
drill-downs resolve. It demonstrates the system honestly; it just is not the client's data.

**Say so plainly when demoing.** The app has a provenance model precisely so nothing is passed off
as something it is not.

---

## Step 1 — Get the code onto the machine

```powershell
cd C:\Users\R757680\ds\workspace
git clone https://github.com/jmohan0606/pce-practice-demo.git
cd pce-practice-demo
```

If GitHub is unreachable from the client machine, copy the repo across as a zip instead. You need
everything **except** `reference/`, `.git/`, `node_modules/` — those are large and unnecessary.

⚠ **`data/vertices` and `data/edges` must come across.** They are the mock dataset. If they are
gitignored on your machine, copy them manually — without them the app starts and shows nothing.

Verify:
```powershell
dir data\vertices\*.csv    # expect 17 files
dir data\edges\*.csv       # expect 29 files
type data\manifest.json | findstr /C:"files"
```

---

## Step 2 — Python dependencies

```powershell
uv sync
```

Or if `pyproject.toml` does not resolve against the client artifactory:

```powershell
uv pip install fastapi uvicorn pydantic pydantic-settings httpx anthropic openai `
               chromadb pdfplumber python-docx python-pptx reportlab openpyxl python-multipart
```

All of these were confirmed installable in your environment earlier. If any fails, note which —
it determines what has to be switched off in Step 5.

---

## Step 3 — Node dependencies

```powershell
node --version          # 18 or higher
cd frontend
npm install
npm run build
cd ..
```

If npm cannot reach the registry, you need a `node_modules` bundle carried across from the
Codespace. Test `npm run build`, not just `npm run dev` — a dev server can start on code that will
not build.

---

## Step 4 — Configuration

Create `.env` in the repo root:

```
# --- Data: mock, no TigerGraph ---
GRAPH_CLIENT_MODE=mock
DATA_DIR=data

# --- LLM: real cdao ---
LLM_MODE=cdao
CDAO_WORKSPACE_ID=906313
CDAO_MODEL=gpt-5
CDAO_API_VERSION=
AZURE_OPENAI_API_KEY=<your key>

# --- Embeddings: real cdao ---
EMBEDDING_MODE=cdao
EMBEDDING_MODEL=text-embedding-3-large-1
EMBEDDING_DIM=3072
CHROMA_PATH=C:\Users\R757680\ds\workspace\pce-practice-demo\chroma

# --- Ports ---
API_PORT=8002
FRONTEND_PORT=3002
```

And `frontend/.env.local`:
```
NEXT_PUBLIC_API_BASE=http://localhost:8002
```

**Four things that will bite if you get them wrong:**

1. **`CDAO_API_VERSION` stays blank.** Not empty-string-in-quotes, not omitted — blank. The adapter
   omits the argument entirely when it is blank; a GPT-5 cdao deployment rejects any value.
2. **`CHROMA_PATH` must be absolute on Windows.** A relative path resolves against whatever
   directory you started the process from.
3. **`EMBEDDING_MODE` valid values are `cdao | cdao_openai | local | azure | azure_openai`.**
   There is no `mock` — it raises. (`LLM_MODE` does have a `mock`, but do not use it: canned text
   is not a demo.)
4. **`GRAPH_CLIENT_MODE=mock` is the whole point** — leave `TIGERGRAPH_*` empty. In `real` mode a
   tier-4 read fails loudly by design, which is correct behaviour but not what you want today.

---

## Step 5 — Preflight, before you start the servers

```powershell
uv run python scripts\check_llm.py
```

Must print a real cdao sentence **and** an embedding whose length equals `EMBEDDING_DIM`.
If the dimension differs from 3072, set `EMBEDDING_DIM` to the actual value **before uploading any
document** — re-embedding after the fact means redoing every document.

```powershell
uv run python scripts\check_cache_support.py
```

Reports whether cdao's automatic prefix caching engages. Not a blocker — but if it does not, each
insight run costs roughly double what we measured on Claude. Worth knowing before you generate for
twenty advisors in front of the client.

---

## Step 6 — Start both servers

Two PowerShell windows. **PowerShell uses `;` not `&&`.**

Window 1 — backend:
```powershell
cd C:\Users\R757680\ds\workspace\pce-practice-demo
uv run python -m uvicorn app.api.main:app --host 0.0.0.0 --port 8002
```

Window 2 — frontend:
```powershell
cd C:\Users\R757680\ds\workspace\pce-practice-demo\frontend
npm run dev -- --port 3002
```

Check:
```powershell
curl http://localhost:8002/api/health
```

`graph_mode` should read `mock` and the vertex row counts should be non-zero. Then open
**http://localhost:3002**.

---

## Step 7 — Pre-generate before the client is watching

Insight generation takes 30–90 seconds per transition. **Do not do it live.** Run it once beforehand
so every screen loads instantly — results are stored, not cached, so they persist.

1. Dashboard → select the **Apr → May** arrow → **Generate Insights**
2. Repeat for **May → Jun**
3. Advisor page → generate for the two or three advisors you plan to show
4. Click into one drill-down per level so those runs are stored too

Then reload every page and confirm it renders from storage with no spinner.

---

## Step 8 — The document demo

The rule extraction story is the most compelling part, and it works in mock mode because cdao is real.

1. Documents & Rules → upload a plan document (PDF, DOCX, PPTX, TXT or CSV)
2. Rules are extracted with page citations
3. Review, approve, publish — a new rule set version is minted
4. Regenerate insights and show the new rule appearing in the narrative with its citation

**A one-line conflict demo:** create `fee_change.txt` containing something like
*"Effective 1 September 2026 the standard managed fee schedule changes from 145 bps to 125 bps."*
Upload it as a Plan document and the Rule Conflict Auditor should flag it against the published
145 bps rule — showing conflict detection without a large document.

---

## What to say about the data

Be direct: **this is fabricated data with the client's real structure.** Their product taxonomy,
their reason codes, their plan rules, their calculations — twenty synthetic advisors instead of
theirs.

What is genuinely real: every rule extracted from whatever document you upload, every citation, the
AI reasoning, and all the arithmetic.

The provenance chips already carry this — `REAL`, `DERIVED`, `DUMMY`. CRM opportunities are marked
Dummy Data on screen, so that part explains itself.

---

## If something breaks

| Symptom | Cause | Fix |
|---|---|---|
| Health shows tier 4 but data is empty | `data/vertices` did not come across | Copy the CSVs; check `dir data\vertices\*.csv` returns 17 |
| Every revenue figure is zero | `reason_cd` blank instead of `__NONE__` | Only affects real extraction; in mock mode check the CSVs are intact |
| cdao chat fails | `CDAO_API_VERSION` has a value | Blank it |
| Embedding raises on dimension | `EMBEDDING_DIM` does not match the deployment | Set it to what `check_llm.py` reported, then re-index |
| Frontend loads but no data | `NEXT_PUBLIC_API_BASE` wrong, or backend not running | `curl localhost:8002/api/health` |
| Insight run stops early | A limit bound | The UI now states which limit and its effect — raise it in `.env` |
| Chroma errors on write | `CHROMA_PATH` relative | Make it absolute |

Logs: `logs\app.log`, rotating at midnight with dated archives.

---

## What this does not demonstrate

Worth being clear with yourself about, so the client is not surprised later:

- **Their actual revenue figures** — the numbers are fabricated
- **Scale** — 2,190 transactions here against ~60,000 for a real 20-advisor cohort, and millions
  firm-wide
- **TigerGraph** — the graph queries run against the local store; live GSQL is unproven
- **Real cohort scenarios** — the mock data has fee reductions and transfers because it was
  generated to, not because those advisors did that

None of it undermines the demo. It just means "we will show you your own numbers next" is the
honest next sentence.
