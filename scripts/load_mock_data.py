"""Round A task 6 — load the mock CSV set through the ported ingestion pipeline.

Runs every manifest entity (vertices first, then edges) through IngestionService's
batch/checkpoint loop against the active GraphClient, then verifies loaded counts
against data/manifest.json. A count mismatch raises — fail loudly.

Run: python3 scripts/load_mock_data.py [--fresh]
  --fresh  clear ingestion checkpoints first (full re-write)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.graph.client import get_graph_client  # noqa: E402
from app.ingestion.entity_registry import list_entity_configs  # noqa: E402
from app.ingestion.ingestion_service import IngestionService  # noqa: E402
from app.ingestion.manifest_check import verify_counts_against_manifest  # noqa: E402
from app.ingestion.models import IngestionRunRequest, IngestionStatus  # noqa: E402

# Round H 5.3: settings-resolved (INGESTION_MAX_BATCH_CALLS_PER_ENTITY), no
# script-local constant — the scale-28 run measured 116 calls max per entity
# (57,657 rows / batch 500), well inside the deliberately-kept 500 cap.
from app.config.settings import get_settings  # noqa: E402

MAX_BATCH_CALLS = get_settings().ingestion_max_batch_calls


def main() -> None:
    service = IngestionService()
    if "--fresh" in sys.argv:
        print("clearing checkpoints:", service.clear_checkpoints()["cleared_entities"], "entities")

    failed: list[str] = []
    for config in list_entity_configs():
        calls = 0
        while True:
            calls += 1
            if calls > MAX_BATCH_CALLS:
                raise RuntimeError(f"{config.entity_name}: exceeded {MAX_BATCH_CALLS} batch calls")
            response = service.run_entity_ingestion(
                IngestionRunRequest(entity_name=config.entity_name, resume=calls > 1)
            )
            batch = response.batch_status
            if batch.status == IngestionStatus.COMPLETED:
                print(f"{config.kind:6} {config.entity_name:30} "
                      f"processed={batch.processed_records} created={batch.created_records} "
                      f"updated={batch.updated_records} skipped={batch.skipped_records}")
                break
            if batch.status == IngestionStatus.FAILED:
                print(f"FAILED {config.entity_name}: {batch.message}")
                failed.append(config.entity_name)
                break

    if failed:
        raise RuntimeError(f"{len(failed)} entities failed to load: {failed}")

    report = verify_counts_against_manifest(get_graph_client())
    print(f"\nmanifest verification: ok={report['ok']} "
          f"targets checked={len(report['checked'])} mismatches={len(report['mismatches'])}")


if __name__ == "__main__":
    main()
