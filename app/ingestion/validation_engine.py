from __future__ import annotations

from app.graph.client import validate_entry_header
from app.ingestion.models import IngestionEntityConfig


def _config_entry(config: IngestionEntityConfig, file_name: str | None = None) -> dict:
    """Shape an entity config as a manifest-style entry for the shared header check."""
    return {
        "kind": config.kind,
        "target": config.tigergraph_vertex,
        "file": file_name or config.csv_file_name,
        "columns": config.columns,
        "id_column": config.primary_key,
        "from_column": config.from_column,
        "to_column": config.to_column,
    }


class ValidationEngine:
    def validate_header(
        self, config: IngestionEntityConfig, headers: list[str], file_name: str | None = None
    ) -> list[str]:
        """Pre-flight: the CSV header must match the manifest mapping EXACTLY
        (no missing, no extra, no duplicate columns). A partial mapping would
        silently drop attributes, so it fails the entity before any write."""
        errors = validate_entry_header(_config_entry(config, file_name), headers)
        missing_required = [
            col for col in config.required_columns if col not in (headers or [])
        ]
        for col in missing_required:
            message = f"Missing required column: {col}"
            if message not in errors and not any(col in e for e in errors):
                errors.append(message)
        return errors

    def validate_record(self, config: IngestionEntityConfig, record: dict[str, str]) -> list[str]:
        errors = []
        for col in config.required_columns:
            value = record.get(col)
            if value is None or str(value).strip() == "":
                errors.append(f"Required column {col} is empty")
        return errors
