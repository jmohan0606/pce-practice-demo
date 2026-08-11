from __future__ import annotations

import json
from functools import lru_cache

from app.config.settings import get_settings
from app.ingestion.models import IngestionEntityConfig

# The registry is GENERATED from the source-of-truth manifest (data/manifest.json),
# so the ingestion pipeline covers ALL vertex and edge types — not a hand-picked
# subset. Entity names are the manifest targets with the schema prefix stripped
# (e.g. phx_dm_pce_advisor -> "advisor").

_PREFIX = "phx_dm_pce_"

# Larger write batches for the high-volume series files.
_BATCH_OVERRIDES: dict[str, int] = {
    "revenue_transaction": 1000,
    "monthly_revenue": 1000,
    "account_month": 1000,
}


def _entity_name(target: str) -> str:
    return target[len(_PREFIX):] if target.startswith(_PREFIX) else target


@lru_cache(maxsize=1)
def _configs() -> dict[str, IngestionEntityConfig]:
    manifest_path = get_settings().resolved_manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    default_batch = int(manifest.get("batch_size", 500))

    configs: dict[str, IngestionEntityConfig] = {}
    for entry in manifest["files"]:
        name = _entity_name(entry["target"])
        kind = entry["kind"]
        if kind == "vertex":
            primary_key = entry["id_column"]
            required = entry.get("required_columns") or [primary_key]
        else:
            primary_key = entry["from_column"]  # display only; edges key on from->to
            required = entry.get("required_columns") or [entry["from_column"], entry["to_column"]]
        configs[name] = IngestionEntityConfig(
            entity_name=name,
            csv_file_name=entry["file"],  # includes vertices/ or edges/ subdir
            primary_key=primary_key,
            tigergraph_vertex=entry["target"],
            required_columns=list(required),
            batch_size=_BATCH_OVERRIDES.get(name, default_batch),
            kind=kind,
            order=int(entry.get("order", 0)),
            expected_rows=entry.get("expected_rows"),
            columns=dict(entry.get("columns") or {}),
            from_type=entry.get("from_type"),
            to_type=entry.get("to_type"),
            from_column=entry.get("from_column"),
            to_column=entry.get("to_column"),
        )
    return configs


def get_entity_config(entity_name: str) -> IngestionEntityConfig:
    configs = _configs()
    try:
        return configs[entity_name]
    except KeyError as exc:
        raise ValueError(f"Unknown ingestion entity: {entity_name}") from exc


def list_entity_configs() -> list[IngestionEntityConfig]:
    """All entities in dependency order: vertices first (manifest order), then edges."""
    configs = list(_configs().values())
    return sorted(configs, key=lambda c: (0 if c.kind == "vertex" else 1, c.order))
