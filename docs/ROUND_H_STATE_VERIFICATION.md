# Round H state verification (post-restart, 2026-08-12)

Context: the previous session hit its usage limit mid-round and the Codespace
restarted. This report establishes the true repo state, verified against actual
code — not just the git log or PROGRESS.md checkboxes.

**Headline: everything the session claimed to finish is genuinely committed, the
working tree is completely clean (no stashes, no uncommitted files), and
PROGRESS.md's checkboxes are accurate — nothing died mid-write.**

## Committed (verified against code)

- **Task 1 — confirmed.** The only `transferred_keys` mention in
  `app/rules/service.py` is a docstring at line 13 noting the implicit
  accumulation was deleted. `app/rules/seed.py:188` gives LOST_ACCOUNT an
  explicit `exclude_matched_of: ["ACCOUNT_TRANSFERRED_IN",
  "ACCOUNT_TRANSFERRED_OUT"]`. Commit `6802da4` plus the API-serialization
  follow-up `ba3a58a`.
- **Task 2 — confirmed, all limits.** Every limit from ROUND_H_SPEC §2.1
  resolves from `app/config/settings.py` with an env alias — the table's 12
  rows expand to 16 fields (BUDGETS became 4 drilldown fields; compiler
  MAX_SEARCHES/MAX_REPAIRS split), plus `MINER_WRAPUP_TURNS` and
  `MINER_EXPLORATION_RESERVE`, matching PROGRESS.md's "18 fields" claim. The
  §2.2 resizes are in place (tokens 250k, queries 25, turns 35, rows 40,
  evidence 200, payload 4k; ingestion cap kept at 500 as spec'd).
  Commit `85b9790`.
- **Task 2.5 — confirmed, with a nuance.** `app/shared/logging.py:120` defines
  `DatedSizeRotatingFileHandler`, which *subclasses* `TimedRotatingFileHandler`
  (midnight roll + size cap as a within-day safety net), and it is the handler
  actually installed at line 185. So yes on TimedRotating, via a subclass —
  exactly as PROGRESS.md describes.
- **Task 3 — confirmed.** `grep cache_control app/agents/` returns zero hits;
  `scripts/check_cache_support.py` exists (5.6 KB). Commit `512efc9`.
- **Task 4 — committed** (`6fae221`, the limit-surfacing UI). Commit verified
  to exist; `npm run build` was not re-run in this check.
- **Ports — fully migrated to 8002/3002.** No 8001/3001 references remain in
  `.env`, `.env.example`, `frontend/.env.local(.example)`, `package.json`,
  `lib/api.ts`, `next.config.mjs`, `e2e_finish.py`, or `settings.py`. Settings
  defaults are 8002/3002 (`app/config/settings.py:225-227`). Commit `e2eda07`.
  (The "8001/3001" text in PROGRESS.md's Round E/G history sections is old
  narrative, not live config.)

## Never started (matches PROGRESS.md's honest deferral)

- **Task 5 (scale test)** — genuinely untouched. No `--scale` flag on
  `scripts/generate_mock_data.py` (grep hits there are unrelated internal
  variables). The resized Task 2 defaults remain unmeasured at target volume.
- **Task 6 / `docs/ROUND_H_COMPLETE.md`** — does not exist. Check 11 is
  deferred with Task 5.

## Uncommitted on disk

Nothing. `git status` is clean and the stash list is empty.

## Resumption point

Exactly where PROGRESS.md says: Tasks 1–4 done and committed; remaining work is
Task 5 (scale test: `--scale` flag, scale run, measurements) and Task 6 (final
check sweep + ROUND_H_COMPLETE.md).
