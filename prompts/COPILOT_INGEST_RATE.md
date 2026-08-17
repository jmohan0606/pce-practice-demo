# Copilot Task — Measure the TigerGraph Ingestion Rate

**This is the only number the load plan is missing.** Everything measured so far was an in-process
local store in a Codespace; the client environment writes over the network, where per-batch latency
dominates. **Do not estimate it — run it.**

Known load size: **34,249,456 vertex rows** plus edges (roughly 1.5×), so about **85.6M rows total**.
At 5,000 rows/sec that is a 5-hour load; at 500 rows/sec it is 48 hours. The difference decides how
the next two days are sequenced.

TigerGraph is installed with the schema and **no data**. Graph `phx_dm_pce_practice_demo`,
31 vertex types, 44 edge types.

---

## OUTPUT RULES

1. Output ONLY the filled template at the bottom. No preamble, no plan, no summary.
2. Under 30 lines — this will be photographed.
3. A step that fails gets `FAILED: <one-line reason>`. **Never estimate a figure you did not
   measure.**
4. Report **p95, not just median.** A load is paced by its slow batches, not its typical ones.

---

## Write and run `scripts/measure_ingest_rate.py`

### 1 · Connect exactly as the app does

Use `app/ingestion/tigergraph_upsert.py` — same client, same auth, same batching path. **Do not
write a fresh REST call**; a hand-rolled request would measure something the real load does not do.

### 2 · Use realistic payloads

Generate synthetic rows matching the **real `phx_dm_pce_revenue_transaction` column set** — all 25
columns, realistic string lengths and value types. Payload size drives throughput, so a trivial
three-column vertex would measure nothing useful.

Take the column list from `docs/tigergraph/01_vertices.gsql`.

### 3 · Measure vertices at three batch sizes

**500, 1000, 5000.** Twenty batches at each size. Record every batch's wall time and report
min / median / p95 / max, plus rows per second.

### 4 · Measure edges separately

Edges do not necessarily run at the vertex rate. Use `phx_dm_pce_txn_by_advisor` (or another
two-column edge), at the best-performing batch size from step 3, twenty batches.

### 5 · Baseline the network

Ten samples of a single trivial RESTPP call (an echo or a one-row read). Report min / median / p95.

This separates network latency from ingestion cost — if a round trip is 200ms, no batch size will
save you and the answer is fewer, larger batches.

### 6 · Clean up

Delete the synthetic rows, or write to a throwaway vertex type dropped afterwards. **The graph must
end empty** — the real load starts from zero.

### 7 · Report the connection path

Whether the client reaches TigerGraph directly, through an NLB, or through a proxy; and whether
`pyTigerGraph` or raw RESTPP is serving. Both change what a batch costs.

---

## Then project honestly

```
85,600,000 rows ÷ (p95 rows/sec) × 1.2     ← 20% for orchestration, validation, retries
```

**From p95, not median.** And state the batch size the projection assumes.

---

## RETURN EXACTLY THIS

```
=== INGESTION RATE · live TigerGraph, empty graph ===
connection: direct | NLB | proxy        serving: pyTigerGraph | RESTPP
RESTPP round trip:  min=    ms   median=    ms   p95=    ms

VERTEX (phx_dm_pce_revenue_transaction, 25 cols, 20 batches each)
  batch  500:  median=    s  p95=    s   -> rows/sec=
  batch 1000:  median=    s  p95=    s   -> rows/sec=
  batch 5000:  median=    s  p95=    s   -> rows/sec=

EDGE (phx_dm_pce_txn_by_advisor, best batch size)
  batch     :  median=    s  p95=    s   -> rows/sec=

best batch size:
graph left empty:  YES | NO

PROJECTED LOAD (85.6M rows, p95 + 20%):        hours
```
