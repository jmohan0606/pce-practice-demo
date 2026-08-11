"""'What to do next' hints for persisted ingestion errors.

Maps known error shapes to a concrete operator action. Unknown errors get the
generic triage step rather than nothing."""
from __future__ import annotations

_RULES: list[tuple[tuple[str, ...], str]] = [
    (("missing declared column", "no manifest mapping", "duplicate column", "Missing required column"),
     "The CSV header does not match the manifest. Regenerate the data set with "
     "`python scripts/generate_mock_data.py` (or fix the CSV header), then Reload this entity."),
    (("absent from the record", "header/manifest mismatch"),
     "A mapped column is missing from a data row — the file is malformed or was "
     "edited by hand. Regenerate it with `python scripts/generate_mock_data.py`."),
    (("ZERO attributes", "attribute-less"),
     "Every non-key value in a row resolved empty — the row would have loaded as an "
     "id-only vertex. Check the source extract for that row, regenerate, and Reload."),
    (("LOCAL FALLBACK tier",),
     "TigerGraph was unreachable and the write was refused rather than silently "
     "diverted. Check connectivity via /api/health and logs/app.log, then Reload."),
    (("accepted", "PartialUpsertError", "of "),
     "TigerGraph accepted only part of the batch. Check the TigerGraph error log for "
     "the rejected records, fix the data, and Reload — the batch was NOT checkpointed."),
    (("Required column",),
     "A required value is empty in the named row. Fix the source data and Reload; "
     "rows before it are checkpointed and will skip."),
    (("CSV file not found", "FileNotFoundError"),
     "The entity's CSV is missing from the data directory (see resolved_paths on "
     "/api/health). Run `python scripts/generate_mock_data.py` first."),
    (("Connection", "connect", "timeout", "Timeout"),
     "The graph engine did not respond. Verify TigerGraph is up and credentials in "
     ".env are valid (/api/health), then Reload."),
]


def remediation_for(error_message: str) -> str:
    msg = error_message or ""
    lowered = msg.lower()
    for needles, action in _RULES:
        if any(n.lower() in lowered for n in needles):
            return action
    return ("Read the full error above; fix the underlying cause and Reload this "
            "entity. If state looks inconsistent, clear the checkpoints and re-run "
            "the ingestion.")
