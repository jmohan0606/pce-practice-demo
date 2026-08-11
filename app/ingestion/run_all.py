from __future__ import annotations

import threading
from datetime import datetime

from app.ingestion.entity_registry import list_entity_configs
from app.ingestion.ingestion_service import IngestionService
from app.ingestion.models import (
    IngestionRunRequest,
    IngestionStatus,
    RunAllEntityResult,
    RunAllStatus,
)
from app.shared.ids import timestamp_id
from app.shared.logging import get_logger

_log = get_logger("app.ingestion.run_all")

# Safety valve: an entity is (rows / batch_size) + slack batch calls; a stuck
# resume loop must never spin forever against a remote engine.
_MAX_BATCH_CALLS_PER_ENTITY = 500


class RunAllManager:
    """Full-dataset ingestion orchestrator behind the 'Run All Ingestion' button.

    Loads the ENTIRE source-of-truth dataset — every vertex type first (manifest
    order, which encodes dependencies), then every edge type — by driving the same
    per-entity batch/checkpoint/resume loop the single-entity button uses, in a
    background thread, with per-entity progress readable via status().
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._status = RunAllStatus()

    def status(self) -> RunAllStatus:
        with self._lock:
            return self._status.model_copy(deep=True)

    def start(self, dry_run: bool = False, batch_size: int | None = None) -> RunAllStatus:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._status.model_copy(deep=True)
            configs = list_entity_configs()  # vertices first, then edges
            self._status = RunAllStatus(
                run_id=timestamp_id("runall"),
                status=IngestionStatus.RUNNING,
                dry_run=dry_run,
                started_at=datetime.utcnow(),
                total_entities=len(configs),
                batch_size_override=batch_size,
                message="Started",
                entities=[
                    RunAllEntityResult(
                        entity_name=c.entity_name,
                        kind=c.kind,
                        file_name=c.csv_file_name,
                        total_records=c.expected_rows or 0,
                        batch_size=batch_size or c.batch_size,
                    )
                    for c in configs
                ],
            )
            self._thread = threading.Thread(
                target=self._run, args=(dry_run, batch_size), name="ingestion-run-all", daemon=True
            )
            self._thread.start()
            return self._status.model_copy(deep=True)

    # --- worker ---

    def _update(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                setattr(self._status, k, v)

    def _update_entity(self, index: int, **kwargs) -> None:
        with self._lock:
            entity = self._status.entities[index]
            for k, v in kwargs.items():
                setattr(entity, k, v)

    def _run(self, dry_run: bool, batch_size: int | None = None) -> None:
        service = IngestionService()
        configs = list_entity_configs()
        completed = 0
        failed = 0
        total_rows = 0

        for index, config in enumerate(configs):
            self._update(current_entity=config.entity_name, current_entity_index=index + 1)
            self._update_entity(index, status=IngestionStatus.RUNNING)
            try:
                calls = 0
                while True:
                    calls += 1
                    if calls > _MAX_BATCH_CALLS_PER_ENTITY:
                        raise RuntimeError(
                            f"exceeded {_MAX_BATCH_CALLS_PER_ENTITY} batch calls — aborting entity"
                        )
                    response = service.run_entity_ingestion(
                        IngestionRunRequest(
                            entity_name=config.entity_name,
                            resume=calls > 1,  # fresh start on first call, resume within this run
                            dry_run=dry_run,
                            batch_size=batch_size,
                        )
                    )
                    batch = response.batch_status
                    self._update_entity(
                        index,
                        total_records=batch.total_records,
                        processed_records=batch.processed_records,
                        created_records=batch.created_records,
                        updated_records=batch.updated_records,
                        skipped_records=batch.skipped_records,
                        failed_records=batch.failed_records,
                        message=batch.message,
                    )
                    if batch.status == IngestionStatus.COMPLETED:
                        completed += 1
                        total_rows += batch.processed_records
                        self._update_entity(index, status=IngestionStatus.COMPLETED)
                        break
                    if batch.status == IngestionStatus.FAILED:
                        failed += 1
                        self._update_entity(index, status=IngestionStatus.FAILED)
                        _log.error(
                            "run-all: entity %s FAILED: %s", config.entity_name, batch.message
                        )
                        break
                    # RUNNING → another batch remains; loop continues with resume=True
            except Exception as exc:  # noqa: BLE001 — keep going; report per entity
                failed += 1
                self._update_entity(
                    index, status=IngestionStatus.FAILED, message=str(exc)
                )
                _log.error("run-all: entity %s raised: %s", config.entity_name, exc)
            self._update(
                completed_entities=completed,
                failed_entities=failed,
                total_rows_processed=total_rows,
            )

        self._update(
            status=IngestionStatus.FAILED if failed else IngestionStatus.COMPLETED,
            current_entity=None,
            current_entity_index=None,
            finished_at=datetime.utcnow(),
            message=(
                f"{completed}/{len(configs)} entities completed"
                + (f", {failed} failed — expand the failed rows for the error and fix, "
                   f"then Reload just those entities" if failed else "")
            ),
        )
        _log.info("run-all finished: %s", self.status().message)


_manager: RunAllManager | None = None


def get_run_all_manager() -> RunAllManager:
    global _manager
    if _manager is None:
        _manager = RunAllManager()
    return _manager
