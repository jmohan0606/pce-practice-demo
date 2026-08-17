# Round 2a — post-restart state report (2026-08-17)

The Codespace restarted mid-round. This report establishes the true state,
verified against the actual code (not just PROGRESS.md checkboxes or the git
log messages). **Nothing was changed to produce this report.**

## Committed — Tasks 1–4, every spec claim verified in code

| Spec item | Verified evidence |
|---|---|
| Task 1: batch_size 5000 | `data/manifest.json` line 4 `"batch_size": 5000`; `app/config/settings.py:236` `ingestion_batch_size` default 5000; env override honored in `app/ingestion/entity_registry.py:51`. Commit 159e755. |
| 2.1: adv_flows April–June | `docs/data/extraction/raw_adv_flows.sql` header: "APRIL-JUNE (Round 2a — June flow rows now exist; the earlier April/May-only finding no longer holds)". |
| 2.2: temp tables, no inlined SIDs | `docs/data/extraction/00_session_setup.sql` exists; `generate_extraction_sql.py` creates `cohort_adv` (500-SID multi-row inserts) + `scoped_acct` temp tables; templates join, never inline. |
| 2.4: four large tables chunked | Balances chunk per month (never a UNION); account / eci_rel / eci_map split by `mod(abs(hashtext(s.k)), :n)` buckets (`--buckets`, default 4) in both `generate_extraction_sql.py` and `extract_chunked.py`. |
| 2.5: build reads five chunk families | `build_real_data.py` ~line 170 declares the five families with sequence-gap detection and both-forms-refuse. |
| 2.6: streaming builders | Per-bucket account / eci_rel / eci_map passes, `txn_stream()` generator feeding `build_monthly_revenue`, per-month spilled account_month (`_am_spill`). |
| 2.7: disk check | `check_free_disk` (20 GB floor, `--skip-disk-check`) in both `build_real_data.py` (line 384) and `extract_chunked.py`. |
| Task 3: phase field + --max-parallel | `phase` in committed `data/manifest.json` (18 phase-1 vertices / 31 phase-2 edges); `load_real_data.py` `--max-parallel` default 3, per-phase ThreadPoolExecutor. Commit e36499f. |
| Task 4: reconcile_load.py | `scripts/reconcile_load.py` exists, committed in 03591a2. |

The four commit hashes in PROGRESS.md (159e755, 72feccb, e3eb213, e36499f,
03591a2) all match `git log` on `main`.

## Uncommitted on disk — the interrupted Task 6 commit

New (untracked):
- `scripts/verify_round_2a.py` — 536 lines, parses cleanly
- `scripts/make_scale_proof.py` — 312 lines, parses cleanly
- `docs/ROUND_2A_COMPLETE.md` — 142 lines, records **16/16 PASS**
  (check 11 = the deferred Task 5 guide, printed as SKIP), ends with its
  proper closing section — not truncated

Modified (unstaged):
- `scripts/build_real_data.py` (+61/−32) — memory optimizations from the
  scale-proof work: compact `advisor_by_acct` storage (bare str / tuple
  instead of per-account sets), per-month `month_attribution()` recomputation
  instead of holding all months, `households.clear()` after the household
  pass. Parses cleanly.
- `docs/CLIENT_ENV_RUNBOOK.md` (+58 lines net) — Phases 2/3/5 updated to
  match the Round 2a reality (5000 batch size, 109-chunk plan, streaming
  build output, two-phase parallel load).
- `docs/PROGRESS.md` — the entire Round 2a section is itself part of the
  uncommitted work.

**Nothing died mid-write.** All three Python files pass `ast.parse`; both
docs end coherently. The restart hit *after* the files were written but
*before* the Task 6 commit.

## Never started

- **Task 5** (Copilot extraction guide) — deliberately deferred by operator
  instruction, per PROGRESS.md and verify check 11's SKIP.

## Caveat before committing

`ROUND_2A_COMPLETE.md`'s "16/16 PASS" and regression-green claims were
produced by the pre-restart session and have **not been re-executed** on this
tree. The uncommitted `build_real_data.py` memory edits are what that verify
allegedly ran against.

**Recommended next step:** re-run `scripts/verify_round_2a.py` (and the
regression suites) to prove the working tree, then commit the uncommitted
files as the Task 6 commit.
