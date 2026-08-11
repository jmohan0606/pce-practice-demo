"""Round A task 6 — verify loaded graph counts against the manifest.

After a full load, every vertex and edge target must hold EXACTLY the number of
rows the manifest declares (expected_rows). Any deviation fails loudly — a
partially-loaded graph must never pass silently."""
from __future__ import annotations

import json

from app.config.settings import get_settings
from app.ingestion.graph_validation import _parse_count


def verify_counts_against_manifest(graph_client) -> dict:
    """Compare the live graph count of every manifest target with expected_rows.

    Returns {"ok": bool, "mismatches": [...], "checked": [...]}. Raises
    RuntimeError listing ALL mismatches when any target's loaded count differs
    from its expected_rows (fail loudly — no partial pass)."""
    manifest_path = get_settings().resolved_manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    checked: list[dict] = []
    mismatches: list[dict] = []

    for entry in manifest.get("files", []):
        target = entry["target"]
        kind = entry.get("kind", "vertex")
        expected = entry.get("expected_rows")
        if expected is None:
            continue  # no declared expectation for this target
        expected = int(expected)

        try:
            stats = graph_client.statistics(kind=kind, target_type=target)
            actual = _parse_count(stats, target)
        except Exception as exc:  # noqa: BLE001 — an unreadable count is a failure, not a pass
            actual = None
            error = f"{type(exc).__name__}: {exc}"
        else:
            error = None

        record = {
            "target": target,
            "kind": kind,
            "expected_rows": expected,
            "graph_count": actual,
        }
        if error:
            record["error"] = error
        checked.append(record)
        if actual != expected:
            mismatches.append(record)

    result = {"ok": not mismatches, "mismatches": mismatches, "checked": checked}
    if mismatches:
        lines = [
            f"  {m['kind']} {m['target']}: expected {m['expected_rows']}, "
            f"graph holds {m['graph_count']}"
            + (f" ({m['error']})" if m.get("error") else "")
            for m in mismatches
        ]
        raise RuntimeError(
            "Graph counts do not match the manifest "
            f"({len(mismatches)}/{len(checked)} targets mismatched):\n" + "\n".join(lines)
        )
    return result
