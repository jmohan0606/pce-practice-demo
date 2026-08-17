"""Round 4 task 6 — shared behaviour of the four insight-generation scripts.

Build once, use in all four. Every behaviour here answers something that has
already gone wrong on this project:

- RESUMABLE: a checkpoint (data/checkpoints/, the extract_chunked pattern)
  records each completed target; rerunning resumes, ``--restart`` starts over.
- COST PROJECTION BEFORE SPENDING: the average comes from /api/trace/summary
  (real history), never a hardcoded constant; with no history the per-run
  cost prints as unknown. ``--yes`` skips the prompt.
- SKIP WHAT EXISTS: a target that already has a COMPLETE run for its
  scope/transition/rule-set-version is skipped with a line saying so;
  ``--regenerate`` supersedes.
- SEQUENTIAL BY DEFAULT: ``--parallel`` exists, defaults to 1 — generation is
  LLM-bound and parallelism multiplies half-generated failure states.
- PER-TARGET REPORTING: one line per completed target (turns, queries,
  tokens, cost, wall, findings) — figures from the trace API, never estimated.
- FAILURE ISOLATION: one failing target never stops the rest; every failure
  is listed at the end with its reason.
- HONEST EXIT CODE: zero only when every target succeeded or was skipped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_BASE = os.environ.get("API_BASE", "http://localhost:8002")
CHECKPOINT_DIR = REPO_ROOT / "data" / "checkpoints"

POLL_SECONDS = 3.0


class GenError(RuntimeError):
    pass


# ------------------------------------------------------------------ HTTP


def _request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode()).get("detail", "")
        except Exception:  # noqa: BLE001
            pass
        raise GenError(f"{method} {path} -> HTTP {exc.code}"
                       + (f": {detail}" if detail else "")) from exc
    except urllib.error.URLError as exc:
        raise GenError(f"{method} {path} -> unreachable ({exc.reason})") from exc


def api_get(path: str) -> dict:
    return _request("GET", path)


def api_post(path: str, body: dict) -> dict:
    return _request("POST", path, body)


# ------------------------------------------------------------------ prerequisites


def check_prerequisites(require_real: bool = False) -> dict:
    """Every script checks these up front, failing with a clear message —
    never a stack trace. Returns {mode, published_version_id}."""
    # 1 — the backend is reachable (these scripts drive the API).
    try:
        health = api_get("/api/health")
    except GenError as exc:
        raise GenError(
            f"the backend is not reachable at {API_BASE} — start it "
            f"(uvicorn app.api.main:app --port 8002) or set API_BASE. "
            f"({exc})") from exc
    mode = ((health.get("graph") or {}).get("client_mode")
            or (health.get("graph") or {}).get("mode") or "unknown")
    # 2 — GRAPH_CLIENT_MODE when the intent is real data: a mock-mode run
    # generates against the local store and would appear to succeed.
    if mode != "real":
        message = (f"backend graph client mode is '{mode}', not 'real' — "
                   f"generation will run against the LOCAL store, not the "
                   f"client's TigerGraph.")
        if require_real:
            raise GenError(message + " Re-run without --require-real only if "
                                     "that is the intent.")
        print(f"WARNING: {message} (pass --require-real to make this fatal)")
    # 3 — a published rule set exists: with none, every run would produce
    # findings with no rule matches.
    versions = (api_get("/api/rules/versions").get("versions")) or []
    published = [v for v in versions if v.get("status") == "PUBLISHED"]
    if not published:
        raise GenError("no PUBLISHED rule-set version exists — publish one "
                       "before generating (every run would otherwise have "
                       "zero rule matches).")
    published_id = max(published, key=lambda v: v.get("version_no", 0))["version_id"]
    # 4 — the dashboard.insights flag is on; the endpoint refuses when off.
    try:
        flags = api_get("/api/flags")
        rows = flags.get("flags") if isinstance(flags, dict) else flags
        row = next((f for f in rows or [] if f.get("key") == "dashboard.insights"), None)
        if row is not None and not row.get("effective_enabled", row.get("enabled", True)):
            raise GenError(
                "the dashboard.insights feature flag is OFF — the generate "
                "endpoint refuses while it is off. Turn it on in Settings "
                "(or PATCH /api/flags/dashboard.insights) and rerun.")
    except GenError:
        raise
    except Exception:  # noqa: BLE001 — flags endpoint variance never blocks
        pass
    return {"mode": mode, "published_version_id": published_id}


# ------------------------------------------------------------------ projection


def cost_projection(run_count: int) -> str:
    """Estimate from the trace API's real history — never a constant."""
    try:
        projection = api_get("/api/trace/summary").get("projection") or {}
    except GenError:
        projection = {}
    avg_cost = projection.get("avg_run_cost_usd")
    if avg_cost is None:
        return (f"{run_count} run(s); no run history yet — per-run cost "
                f"unknown (the first runs establish it)")
    avg_wall = projection.get("avg_run_wall_ms") or 0
    minutes = max(1, round(run_count * avg_wall / 60000))
    history = projection.get("history_runs")
    return (f"estimated: ~${run_count * avg_cost:.2f} and ~{minutes} min "
            f"(from {history} runs' actuals)")


def confirm_or_exit(prompt: str, yes: bool) -> None:
    print(prompt)
    if yes:
        return
    answer = input("proceed? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        print("aborted — nothing generated.")
        sys.exit(0)


# ------------------------------------------------------------------ checkpoint


class Checkpoint:
    """data/checkpoints/generate_<kind>.json — completed targets keyed by
    target key, guarded by a plan fingerprint (a different plan starts its
    own record; --restart wipes it)."""

    def __init__(self, kind: str, plan: dict, restart: bool) -> None:
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        self.path = CHECKPOINT_DIR / f"generate_{kind}.json"
        self.fingerprint = hashlib.sha256(
            json.dumps(plan, sort_keys=True).encode()).hexdigest()[:16]
        self.completed: dict[str, dict] = {}
        if restart:
            if self.path.exists():
                self.path.unlink()
            return
        if self.path.exists():
            try:
                stored = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                stored = {}
            if stored.get("fingerprint") == self.fingerprint:
                self.completed = stored.get("completed", {})

    def mark(self, key: str, result: dict) -> None:
        self.completed[key] = result
        self.path.write_text(json.dumps(
            {"fingerprint": self.fingerprint, "completed": self.completed},
            indent=1))


# ------------------------------------------------------------------ generation


def existing_run(advisor: str, from_month: str, to_month: str,
                 version_id: str) -> dict | None:
    """The stored COMPLETE run for this exact key, or None."""
    try:
        run = api_get(f"/api/insights/{advisor}/{from_month}/{to_month}"
                      f"?version={version_id}")
    except GenError:
        return None
    return run if run.get("status") == "COMPLETE" else None


def _trace_metrics(run_id: str) -> dict:
    try:
        rows = api_get("/api/trace/runs")
        rows = rows.get("runs") or rows.get("rows") or []
        return next((r for r in rows if r.get("run_id") == run_id), {})
    except GenError:
        return {}


def generate_target(target: dict, version_id: str | None) -> dict:
    """POST /api/insights/generate for one target, poll to completion, return
    the per-run report. Raises GenError with the server's reason on failure."""
    body = {"advisor": target["advisor"], "from_month": target["from"],
            "to_month": target["to"]}
    if version_id:
        body["version_id"] = version_id
    if target.get("practice_only"):
        body["practice_only"] = True
    job = api_post("/api/insights/generate", body)
    job_id = job["job_id"]
    status = api_get(f"/api/insights/status/{job_id}")
    while status.get("status") == "running":
        time.sleep(POLL_SECONDS)
        status = api_get(f"/api/insights/status/{job_id}")
    runs = status.get("runs") or []
    failed = [r for r in runs if r.get("status") == "failed"]
    if failed:
        raise GenError(failed[0].get("error") or "run failed with no recorded error")
    run = runs[0] if runs else {}
    metrics = _trace_metrics(run.get("run_id") or "")
    tokens = ((metrics.get("input_tokens") or 0)
              + (metrics.get("cache_read_tokens") or 0)
              + (metrics.get("cache_write_tokens") or 0))
    return {
        "run_id": run.get("run_id"),
        "finding_count": run.get("finding_count", 0),
        "turns": metrics.get("turns"),
        "queries": metrics.get("query_count"),
        "prompt_tokens": tokens,
        "output_tokens": metrics.get("output_tokens"),
        "cost_usd": metrics.get("est_cost_usd"),
        "wall_ms": metrics.get("wall_ms"),
    }


def _fmt(value, money: bool = False) -> str:
    """A figure or an honest em dash — never estimated."""
    if value is None:
        return "—"
    if money:
        return f"${value:.4f}"
    return f"{value:,}" if isinstance(value, int) else str(value)


def report_line(label: str, result: dict) -> str:
    wall = result.get("wall_ms")
    return (f"  DONE  {label:34s} turns {_fmt(result.get('turns')):>4} · "
            f"queries {_fmt(result.get('queries')):>3} · "
            f"tokens {_fmt(result.get('prompt_tokens')):>9} · "
            f"cost {_fmt(result.get('cost_usd'), money=True):>8} · "
            f"wall {(str(round(wall / 1000)) + 's') if wall else '—':>5} · "
            f"findings {_fmt(result.get('finding_count'))}")


def run_targets(kind: str, targets: list[dict], args,
                version_id: str | None) -> int:
    """The shared driver. Returns the process exit code (0 only when every
    target succeeded or was skipped)."""
    plan = {"kind": kind, "version_id": version_id,
            "targets": [t["key"] for t in targets]}
    checkpoint = Checkpoint(kind, plan, restart=getattr(args, "restart", False))

    todo: list[dict] = []
    for t in targets:
        if t["key"] in checkpoint.completed:
            print(f"  SKIP  {t['label']:34s} already completed in this plan's "
                  f"checkpoint (rerun with --restart to redo)")
            continue
        if not getattr(args, "regenerate", False):
            existing = existing_run(t["advisor"], t["from"], t["to"],
                                    version_id or "latest")
            if existing is not None:
                print(f"  SKIP  {t['label']:34s} run already stored for this "
                      f"key (generation {existing.get('generation')}, "
                      f"{existing.get('version_id')}) — --regenerate supersedes")
                checkpoint.mark(t["key"], {"skipped": "existing run"})
                continue
        todo.append(t)

    failures: list[tuple[str, str]] = []
    succeeded = 0

    def _one(t: dict) -> tuple[dict, dict | None, str | None]:
        try:
            return t, generate_target(t, version_id), None
        except GenError as exc:
            return t, None, str(exc)
        except Exception as exc:  # noqa: BLE001 — isolate, report, continue
            return t, None, f"{type(exc).__name__}: {exc}"

    parallel = max(1, int(getattr(args, "parallel", 1)))
    started = time.perf_counter()
    total_cost = 0.0
    if todo:
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = [pool.submit(_one, t) for t in todo]
            for future in as_completed(futures):
                t, result, error = future.result()
                if error is not None:
                    failures.append((t["label"], error))
                    print(f"  FAIL  {t['label']:34s} {error}")
                    continue
                succeeded += 1
                total_cost += result.get("cost_usd") or 0.0
                print(report_line(t["label"], result))
                checkpoint.mark(t["key"], result)

    wall = time.perf_counter() - started
    skipped = len(targets) - len(todo)
    print(f"\ntotal: {succeeded} generated · {skipped} skipped · "
          f"{len(failures)} failed · ${total_cost:.4f} · {round(wall)}s")
    if failures:
        print("failures:")
        for label, reason in failures:
            print(f"  - {label}: {reason}")
    return 0 if not failures else 1


# ------------------------------------------------------------------ shared CLI


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--yes", action="store_true",
                        help="skip the cost-projection confirmation")
    parser.add_argument("--regenerate", action="store_true",
                        help="force fresh runs (supersedes stored ones)")
    parser.add_argument("--restart", action="store_true",
                        help="discard the checkpoint and start over")
    parser.add_argument("--parallel", type=int, default=1,
                        help="concurrent targets (default 1 — LLM-bound)")
    parser.add_argument("--version-id", default=None,
                        help="pin a rule-set version (default: the published one)")
    parser.add_argument("--require-real", action="store_true",
                        help="fail unless the backend graph mode is 'real'")


def month_ids() -> list[str]:
    months = api_get("/api/months?advisor=all").get("months") or []
    return [m["month_id"] for m in months]


def consecutive_transitions() -> list[tuple[str, str]]:
    ids = sorted(month_ids())
    return list(zip(ids, ids[1:]))
