from __future__ import annotations

import hashlib
import json

from app.ingestion.checkpoint_repository import CheckpointRepository
from app.ingestion.models import DeltaAction


class DeltaDetector:
    def __init__(self, checkpoint_repository: CheckpointRepository) -> None:
        self.checkpoint_repository = checkpoint_repository

    @staticmethod
    def row_hash(record: dict[str, str]) -> str:
        normalized = json.dumps(record, sort_keys=True, default=str)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def detect(self, entity_name: str, primary_key: str, record: dict[str, str]) -> tuple[DeltaAction, str]:
        new_hash = self.row_hash(record)
        old_hash = self.checkpoint_repository.get_hash(entity_name, primary_key)
        if old_hash is None:
            return DeltaAction.CREATE, new_hash
        if old_hash == new_hash:
            return DeltaAction.SKIP, new_hash
        return DeltaAction.UPDATE, new_hash
