# Connection Details — Client Environment

**Fill this in before running anything. Copilot reads it first, every session.**

⚠ **This file contains credentials. It must be gitignored and never committed.**
Confirm before filling it in:

```bash
grep -q "^CONNECTION_DETAILS.md$" .gitignore || echo "CONNECTION_DETAILS.md" >> .gitignore
git check-ignore -v CONNECTION_DETAILS.md    # must print a match
```

---

## 1 · PCL login — ALWAYS RUN THIS FIRST

**Every session, and again after every token expiry.** The IAM token lasts 30 minutes; extraction
takes longer, so this will be run repeatedly during a single extraction.

```
<<< PASTE YOUR PCL LOGIN COMMAND HERE >>>
```

```
<<< PASTE THE TOKEN-GENERATION COMMAND HERE, IF SEPARATE >>>
```

**How to know it worked:** the next PostgreSQL command runs without a PAM or authentication error.
If a query fails with an authentication message, the token has expired — rerun the above and retry.
**That is normal, not a fault.**

---

## 2 · PostgreSQL

```
Host      nlb1b016e39-glbdep-v1-71d8d3fdc76fc824.elb.us-east-1.amazonaws.com
Port      6160
Database  fpicdb
Schema    pcr
User      fpicdbAuroraAppAdmin
Password  <IAM token from step 1 — expires after 30 minutes>
```

The extraction script reads either `PCE_PG_DSN` or the standard `PG*` variables. Export after each
login:

```bash
export PCE_PG_DSN="host=nlb1b016e39-glbdep-v1-71d8d3fdc76fc824.elb.us-east-1.amazonaws.com port=6160 dbname=fpicdb user=fpicdbAuroraAppAdmin password=<token>"
```

Verify:

```bash
python3 -c "import psycopg2,os; psycopg2.connect(os.environ['PCE_PG_DSN']).close(); print('postgres ok')"
```

**Always set a statement timeout** — one query over 12.4M rows will otherwise hang:

```sql
SET statement_timeout = '900s';
```

---

## 3 · TigerGraph

```
Host          <<< FILL IN — hostname only, no port >>>
RESTPP port   9000
GSQL port     14240
Graph         phx_dm_pce_practice_demo
Username      <<< FILL IN >>>
Password      <<< FILL IN >>>
```

Verify the schema is installed and the graph is empty before loading:

```bash
gsql -g phx_dm_pce_practice_demo "ls"
```

Expect **31 vertex types, 44 edge types**, and zero rows.

---

## 4 · `.env` — required before the load and reconcile steps

Steps 7 and 8 of the extraction guide import the application's graph client, which reads `.env`.
**If `GRAPH_CLIENT_MODE` is not `real`, the load writes to a local store and reconciliation compares
against the wrong thing — and both appear to succeed.**

```
GRAPH_CLIENT_MODE=real
TIGERGRAPH_HOST=<hostname, no port>
TIGERGRAPH_RESTPP_PORT=9000
TIGERGRAPH_GSQL_PORT=14240
TIGERGRAPH_GRAPH=phx_dm_pce_practice_demo
TIGERGRAPH_USERNAME=<user>
TIGERGRAPH_PASSWORD=<password>
DATA_DIR=data/real
```

Check:

```bash
grep -E "GRAPH_CLIENT_MODE|TIGERGRAPH_HOST|TIGERGRAPH_GRAPH" .env
```

---

## 5 · cdao — AI features only

Not needed for extraction or loading. Required only when generating insights or uploading documents.

```
CDAO_WORKSPACE_ID     906313
CDAO_MODEL            gpt-5
CDAO_API_VERSION      <<< LEAVE BLANK — a GPT-5 deployment rejects any value >>>
AZURE_OPENAI_API_KEY  <<< FILL IN >>>
EMBEDDING_MODE        cdao
EMBEDDING_MODEL       text-embedding-3-large-1
EMBEDDING_DIM         3072
CHROMA_PATH           <<< ABSOLUTE path — a relative one resolves against the working directory >>>
```

**Confirm the embedding dimension before indexing any document.** If the deployment returns
something other than 3072, `EMBEDDING_DIM` must match it — changing it afterwards means
re-embedding everything.

```bash
python3 scripts/check_llm.py
```

---

## 6 · Paths

```
Repo            <<< FILL IN >>>
Raw extracts    data/real/_raw
Built dataset   data/real
Cohort file     data/real/cohort.txt      (5,746 advisor SIDs, one per line, no header)
Logs            logs/app.log              (rotates at midnight, 30 days retained)
```

**Disk:** 20 GB free required; ~15 GB used at peak.

---

## For Copilot — the standing rules

1. **Run the PCL login in section 1 first, every session.** Do not attempt a database command
   before it.
2. **On any authentication or PAM error, rerun the login and retry.** The token expired. This is
   expected during a long extraction and is not a fault to debug.
3. **Never commit this file** and never echo its contents into terminal output, a report, or a
   commit message.
4. **Never hardcode a credential into a script.** Read from the environment.
5. Connection details come from **this file only** — do not infer a host, port or database name from
   anywhere else in the repository.
