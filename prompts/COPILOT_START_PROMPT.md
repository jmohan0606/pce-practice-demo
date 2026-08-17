# Copilot — Start Prompt

Paste the block below into Copilot to begin the data load.

---

Read `docs/COPILOT_EXTRACTION_GUIDE.md` in full before running anything. It is the complete
procedure for extracting client data from PostgreSQL, building the graph dataset, and loading it
into TigerGraph.

Read `CONNECTION_DETAILS.md` in the repo root for all connection details. It is the only source —
do not infer a host, port or database name from anywhere else in the repository. Run the PCL login
in its section 1 first, and again after every token expiry.

Do not write new extraction or load logic. The scripts exist and are tested — run them as
documented.

Three things that will happen and are **normal, not faults**:

- The IAM token expires after 30 minutes. Extraction stops cleanly with a checkpoint. Rerun the
  login, re-export the DSN, rerun the identical command. Expect this several times across 109
  chunks. **Never pass `--restart`.**
- The build reports dropped `nnm_in_month` edges. Expected — the NNM files cover months outside our
  three-month scope.
- A phase-2 entity refuses to start while phase 1 is incomplete. That refusal is correct behaviour.

**Stop at step 5, the review gate.** Send me the complete validation output and wait for an explicit
go-ahead before building or loading. Do not skip it.

Report progress as you go: chunks completed, row counts, anything that fails. Never estimate a
number — every figure you report must come from a run.

---

## What this covers

| Steps | |
|---|---|
| 0–1 | Login, preflight, place the four NNM `.txt` files and the CRM `.csv` |
| 2–3 | **Extraction** — 109 chunks, resuming on token expiry |
| 4 | **Validation** — sequence gaps, column contracts, baseline comparison |
| **5** | **Review gate — stops here** |
| 6 | **Build** — raw CSVs into 18 vertex and 31 edge CSVs |
| 7 | **Load** — TigerGraph, two phases, ~2.9 hours |
| 8 | **Reconcile** — source vs extracted vs loaded, 49 targets |
| 9 | Smoke test |

## Before pasting

Confirm the connection file exists, is filled in, and is gitignored:

```bash
ls CONNECTION_DETAILS.md
git check-ignore -v CONNECTION_DETAILS.md    # must print a match
```

## Known first-time risk

The scripts are verified on fixtures, but the memory model has **never been proven at 12.4M rows** —
the scale proof was written and not run. If the build fails, it fails loudly with a memory message
rather than silently, and the documented response is `--max-memory-mb 8192`.
