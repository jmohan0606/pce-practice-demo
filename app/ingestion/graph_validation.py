"""Graph-truth validation for the ingestion screen.

A "loaded" state that comes from the checkpoint SQLite alone can report success
for writes that never landed. This module answers "did it REALLY load?" by
interrogating the graph itself, per entity:

  expected count   = data rows in the source CSV (never hardcoded)
  graph count      = live count from the graph (statistics)
  attribute check  = sample N stored rows; each must carry >=1 populated
                     non-primary-key attribute (vertices with mapped non-key
                     columns only — edges/no-attr entities validate on count)

State per entity:
  VALIDATED    graph count == expected AND sampled rows have populated non-PK attrs
  EMPTY_ATTRS  count matches but sampled rows carry only the primary key
  MISMATCH     graph count != expected, or checkpoint claim != graph truth
  NOT_LOADED   nothing in the graph and no checkpoint claim
  UNVERIFIABLE the graph could not be interrogated (real mode with the engine
               unreachable, or the probe was served by the local fallback tier)

A probe served by the local fallback tier while GRAPH_CLIENT_MODE is a real mode
is NOT graph truth and is reported as UNVERIFIABLE, never as VALIDATED.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.config.settings import get_settings
from app.ingestion.checkpoint_repository import CheckpointRepository
from app.ingestion.entity_registry import list_entity_configs
from app.ingestion.models import IngestionEntityConfig
from app.shared.logging import get_logger

_log = get_logger("app.ingestion.validation")

SAMPLE_SIZE = 5


def _csv_rows(path: Path) -> int | None:
    import csv

    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8-sig") as f:
        return max(0, sum(1 for _ in csv.reader(f)) - 1)


def _parse_count(result: dict, target: str) -> int | None:
    """Count for one type from any tier's statistics envelope."""
    for item in result.get("results", []):
        if not isinstance(item, dict):
            continue
        counts = item.get("counts")
        if isinstance(counts, dict) and target in counts:
            return int(counts[target] or 0)
        if isinstance(counts, int):
            return counts
        # RESTPP builtins shape: {"v_type"/"e_type": ..., "count": n}
        if item.get("v_type") == target or item.get("e_type") == target:
            return int(item.get("count") or 0)
    return None


def _mock_served_in_real_mode(result: dict) -> bool:
    mode = get_settings().graph_client_mode.lower()
    return mode not in {"mock", "local"} and result.get("served_by_tier") == 4


def _non_key_attrs(config: IngestionEntityConfig) -> set[str]:
    """Graph attribute names mapped from non-key source columns."""
    keys = {config.primary_key} if config.kind == "vertex" else {
        config.from_column or "from_id", config.to_column or "to_id"
    }
    return {attr for src, attr in (config.columns or {}).items() if src not in keys}


def validate_entity(config: IngestionEntityConfig, graph, checkpoints: CheckpointRepository) -> dict:
    settings = get_settings()
    expected = _csv_rows(settings.resolved_data_dir / config.csv_file_name)

    batch = checkpoints.latest_batch(config.entity_name, config.csv_file_name)
    checkpoint_claim = {
        "status": batch.status.value if batch else None,
        "created": batch.created_records if batch else 0,
        "updated": batch.updated_records if batch else 0,
        "skipped": batch.skipped_records if batch else 0,
    }
    claimed_loaded = bool(batch) and (batch.created_records + batch.updated_records + batch.skipped_records) > 0

    report = {
        "entity_name": config.entity_name,
        "kind": config.kind,
        "target": config.tigergraph_vertex,
        "expected_count": expected,
        "graph_count": None,
        "checkpoint": checkpoint_claim,
        "attr_check": None,          # "populated" | "empty" | "n/a" | "unavailable"
        "attr_sample_size": 0,
        "state": "UNVERIFIABLE",
        "conflict": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    # --- graph count (live) ---
    try:
        stats = graph.statistics(kind=config.kind, target_type=config.tigergraph_vertex)
        if _mock_served_in_real_mode(stats):
            report["conflict"] = "graph probe served by the LOCAL FALLBACK tier — TigerGraph unreachable"
            return report
        graph_count = _parse_count(stats, config.tigergraph_vertex)
    except Exception as exc:  # noqa: BLE001 — report, never raise
        report["conflict"] = f"graph count unavailable: {type(exc).__name__}: {exc}"
        return report
    report["graph_count"] = graph_count if graph_count is not None else 0
    graph_count = report["graph_count"]

    # --- attribute check (vertices with mapped non-key columns) ---
    non_key = _non_key_attrs(config)
    if config.kind != "vertex" or not non_key:
        report["attr_check"] = "n/a"
    elif graph_count == 0:
        report["attr_check"] = "unavailable"
    else:
        try:
            sample = graph.fetch_vertices(config.tigergraph_vertex, limit=SAMPLE_SIZE)
            if _mock_served_in_real_mode(sample):
                report["conflict"] = "sample probe served by the LOCAL FALLBACK tier — TigerGraph unreachable"
                return report
            rows = sample.get("results", [])
            report["attr_sample_size"] = len(rows)
            populated = [
                row for row in rows
                if any((row.get("attributes") or {}).get(a) not in ("", None) for a in non_key)
            ]
            report["attr_check"] = "populated" if rows and len(populated) == len(rows) else "empty"
        except Exception as exc:  # noqa: BLE001
            report["attr_check"] = "unavailable"
            report["conflict"] = f"attribute sample unavailable: {type(exc).__name__}: {exc}"

    # --- state ---
    if graph_count == 0 and not claimed_loaded:
        report["state"] = "NOT_LOADED"
    elif expected is not None and graph_count != expected:
        report["state"] = "MISMATCH"
        report["conflict"] = report["conflict"] or (
            f"graph holds {graph_count} rows but the source CSV has {expected}"
        )
    elif claimed_loaded and graph_count == 0:
        report["state"] = "MISMATCH"
        report["conflict"] = (
            "checkpoint claims rows were loaded but the graph holds 0 — "
            "clear checkpoints and re-run"
        )
    elif report["attr_check"] == "empty":
        report["state"] = "EMPTY_ATTRS"
        report["conflict"] = report["conflict"] or (
            "row count matches but sampled rows carry ONLY the primary key — "
            "attributes did not land; re-load this entity"
        )
    elif report["attr_check"] == "unavailable":
        report["state"] = "UNVERIFIABLE"
    else:
        report["state"] = "VALIDATED"
    return report


def validate_all_entities() -> dict:
    from app.graph.client import get_graph_client

    graph = get_graph_client()
    checkpoints = CheckpointRepository()
    entities = [validate_entity(c, graph, checkpoints) for c in list_entity_configs()]
    states = [e["state"] for e in entities]
    summary = {state: states.count(state) for state in sorted(set(states))}
    for e in entities:
        if e["state"] not in {"VALIDATED", "NOT_LOADED"}:
            _log.warning("ingestion validation: %s is %s (%s)",
                         e["entity_name"], e["state"], e.get("conflict"))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(get_settings().resolved_data_dir),
        "summary": summary,
        "entities": entities,
    }
