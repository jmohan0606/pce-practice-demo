"""Round F task 4.4 / Round 2a task 3 — load the REAL dataset, phase-ordered.

    python3 scripts/load_real_data.py [--data-dir data/real] [--fresh]
                                      [--max-parallel 3]

Extraction parallelises freely; LOADING DOES NOT. Edges reference vertices —
an edge loaded before its endpoint vertices exist produces dangling edges that
silently vanish rather than erroring. So the manifest's `phase` field drives a
strict two-phase load:

  phase 1  all vertex entities   — parallel, --max-parallel workers (default 3)
  phase 2  all edge entities     — parallel, but ONLY after phase 1 completes
                                   ENTIRELY; a phase-2 entity REFUSES to start
                                   (not a warning) while any phase-1 entity is
                                   incomplete

A worker failure fails the WHOLE phase: the stop flag halts every other worker
at its next batch boundary, phase 2 never starts, and the process exits
non-zero — never leaving workers running against a graph that is now
inconsistent. --max-parallel defaults to 3: higher is possible, but it
multiplies partial-failure states and the ~2-hour window leaves little to win.

Per-entity resume is unchanged: the ingestion checkpoints are the real resume
mechanism; a rerun resumes at the first incomplete entity/batch. After the
load, counts are verified against the manifest — a mismatch raises. Then run
scripts/reconcile_load.py for the three-way source/extracted/loaded proof.

The env is set BEFORE any app import, because get_settings() is cached at
first use. SQLITE_DB_PATH keeps real-data checkpoints separate from the mock
set's, so loading real data never corrupts the mock checkpoint state the
verify_round_* suites rely on.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def assert_phase_complete(configs, checkpoints, phase: int) -> None:
    """REFUSE (raise) unless every entity of `phase` has a COMPLETED
    checkpoint. Called before any later-phase entity starts — also guards a
    hand-run edges-only load against a half-loaded vertex set."""
    from app.ingestion.models import IngestionStatus

    incomplete = []
    for c in configs:
        if c.phase != phase:
            continue
        latest = checkpoints.latest_batch(c.entity_name, c.csv_file_name)
        if latest is None or latest.status != IngestionStatus.COMPLETED:
            incomplete.append(
                f"{c.entity_name} ({'never loaded' if latest is None else latest.status.value})")
    if incomplete:
        raise RuntimeError(
            f"REFUSING to start phase {phase + 1}: {len(incomplete)} phase-{phase} "
            f"entit{'y is' if len(incomplete) == 1 else 'ies are'} incomplete — "
            f"{', '.join(incomplete)}. Edges loaded before their endpoint "
            f"vertices exist dangle silently; finish phase {phase} first "
            f"(rerun this script — it resumes).")


def _load_entity(config, stop: threading.Event, max_calls: int) -> tuple[str, str]:
    """One entity's full batch loop in one worker. Returns (entity, status).
    Checks the stop flag between batch calls so a failing sibling halts the
    phase at the next batch boundary."""
    from app.ingestion.ingestion_service import IngestionService
    from app.ingestion.models import IngestionRunRequest, IngestionStatus

    service = IngestionService()  # per-worker instance (own SQLite handles)
    calls = 0
    while True:
        if stop.is_set():
            return config.entity_name, "halted (another entity failed)"
        calls += 1
        if calls > max_calls:
            return (config.entity_name,
                    f"failed: exceeded {max_calls} batch calls "
                    f"(INGESTION_MAX_BATCH_CALLS_PER_ENTITY)")
        response = service.run_entity_ingestion(
            IngestionRunRequest(entity_name=config.entity_name, resume=calls > 1))
        batch = response.batch_status
        if batch.status == IngestionStatus.COMPLETED:
            print(f"{config.kind:6} {config.entity_name:30} "
                  f"processed={batch.processed_records} "
                  f"created={batch.created_records} updated={batch.updated_records} "
                  f"skipped={batch.skipped_records}")
            return config.entity_name, "completed"
        if batch.status == IngestionStatus.FAILED:
            return config.entity_name, f"failed: {batch.message}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default="data/real",
                    help="dataset directory (manifest.json + vertices/ + edges/)")
    ap.add_argument("--fresh", action="store_true",
                    help="clear ingestion checkpoints first (full re-write)")
    ap.add_argument("--max-parallel", type=int, default=3,
                    help="concurrent entities per phase (default 3 — higher "
                         "multiplies partial-failure states for little win)")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    manifest = (data_dir if data_dir.is_absolute() else ROOT / data_dir) / "manifest.json"
    if not manifest.exists():
        print(f"ERROR: {manifest} not found — run scripts/build_real_data.py first",
              file=sys.stderr)
        return 1
    if args.max_parallel < 1:
        print("ERROR: --max-parallel must be >= 1", file=sys.stderr)
        return 1

    os.environ["DATA_DIR"] = str(data_dir)
    os.environ.setdefault(
        "SQLITE_DB_PATH", str(Path(str(data_dir)) / "checkpoints" / "ingestion.db")
    )
    print(f"DATA_DIR={os.environ['DATA_DIR']}  SQLITE_DB_PATH={os.environ['SQLITE_DB_PATH']}")

    # import AFTER the env is set — settings are cached at first use
    from app.config.settings import get_settings
    from app.graph.client import get_graph_client
    from app.ingestion.checkpoint_repository import CheckpointRepository
    from app.ingestion.entity_registry import list_entity_configs
    from app.ingestion.ingestion_service import IngestionService
    from app.ingestion.manifest_check import verify_counts_against_manifest
    from app.shared.jobs import get_job_store

    if args.fresh:
        service = IngestionService()
        print("clearing checkpoints:",
              service.clear_checkpoints()["cleared_entities"], "entities")

    configs = list_entity_configs()
    phases = sorted({c.phase for c in configs})
    max_calls = get_settings().ingestion_max_batch_calls
    checkpoints = CheckpointRepository()

    # Round 1 task 2: the load runs under a phx_dm_pce_job of kind data_load,
    # one stage per entity; the ingestion checkpoints are the real resume.
    jobs = get_job_store()
    job = jobs.begin_job("data_load", "manifest",
                         stages=[c.entity_name for c in configs])

    for phase in phases:
        phase_configs = [c for c in configs if c.phase == phase]
        for prior in phases:
            if prior >= phase:
                break
            # NOT a warning — a refusal (spec Task 3).
            assert_phase_complete(configs, checkpoints, prior)
        print(f"\n=== phase {phase}: {len(phase_configs)} entities, "
              f"up to {args.max_parallel} in parallel ===")
        stop = threading.Event()
        failures: list[tuple[str, str]] = []
        with ThreadPoolExecutor(max_workers=args.max_parallel) as pool:
            futures = {pool.submit(_load_entity, c, stop, max_calls): c
                       for c in phase_configs}
            for fut in list(futures):
                try:
                    entity, status = fut.result()
                except Exception as exc:  # noqa: BLE001 — a worker crash fails the phase
                    entity, status = futures[fut].entity_name, f"failed: {exc}"
                jobs.update(job["job_id"], stage=entity)
                if status.startswith("failed"):
                    failures.append((entity, status))
                    stop.set()  # halt every other worker at its next batch boundary
        if failures:
            msg = "; ".join(f"{e}: {s}" for e, s in failures)
            jobs.fail(job["job_id"], f"phase {phase} failed — {msg}")
            print(f"\nPHASE {phase} FAILED — {msg}\n"
                  f"No later phase was started. Fix the cause and rerun — the "
                  f"checkpoints resume at the first incomplete entity/batch.",
                  file=sys.stderr)
            return 1

    jobs.complete(job["job_id"])
    report = verify_counts_against_manifest(get_graph_client())
    print(f"\nmanifest verification: ok={report['ok']} "
          f"targets checked={len(report['checked'])} mismatches={len(report['mismatches'])}")
    print("next: python3 scripts/reconcile_load.py  (three-way count proof)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
