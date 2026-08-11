from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.config.settings import get_settings
from app.graph.client import get_graph_client
from app.shared.logging import get_logger

_log = get_logger("app.ingestion")


@lru_cache(maxsize=1)
def _manifest_index() -> tuple[dict[str, dict], dict[str, dict]]:
    """Build lookups from the source-of-truth manifest so upserts carry the
    correct schema metadata (vertex id column; edge from_type/to_type/columns).

    This is what lets a single ``(vertex_type, primary_key, attributes)`` call be
    turned into the proper RESTPP/pyTigerGraph upsert payload — no server-side file
    path, just a JSON body keyed by the real schema.
    """
    settings = get_settings()
    manifest_path = settings.resolved_manifest_path
    vertices: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest.get("files", []):
            if entry.get("kind") == "vertex":
                vertices[entry["target"]] = entry
            elif entry.get("kind") == "edge":
                edges[entry["target"]] = entry
    except Exception as exc:  # noqa: BLE001 — manifest optional; fall back to defaults
        _log.warning("ingestion manifest index unavailable (%s); using generic entries", exc)
    return vertices, edges


class TigerGraphUpsertClient:
    """Writes vertices/edges into whichever GraphClient is active.

    Routes through the canonical ``get_graph_client()`` so a single code path serves
    every mode:
      * real modes → pyTigerGraph ``upsertVertices``/``upsertEdges`` or the RESTPP
        ``POST /graph/{graph}`` JSON upsert. BOTH are the schema-driven REST/upsert
        path that needs NO server-side file on the TigerGraph host.
      * ``mock`` (and the local fallback tier when a live engine is unreachable) →
        the mock client, which PERSISTS into the same local store the read queries
        traverse, so upserted rows are immediately visible to the app.
    """

    def __init__(self) -> None:
        self.graph = get_graph_client()

    def upsert_vertex(
        self,
        vertex_type: str,
        primary_key: str,
        attributes: dict[str, Any],
        id_column: str | None = None,
    ) -> dict[str, Any]:
        vertices, _ = _manifest_index()
        manifest_entry = vertices.get(vertex_type)
        id_col = id_column or (manifest_entry or {}).get("id_column") or "id"

        # The primary id is not a settable attribute in TigerGraph — drop it from the
        # attribute set (matching the verified foundation loader) and carry it as the
        # vertex id instead.
        attrs = {k: v for k, v in attributes.items() if k != id_col}
        record = {id_col: primary_key, **attrs}
        entry = {
            "kind": "vertex",
            "target": vertex_type,
            "id_column": id_col,
            "columns": {k: k for k in attrs},
            "file": (manifest_entry or {}).get("file", vertex_type),
        }
        result = self.graph.upsert(entry, [record])
        self._raise_if_rejected(result, requested=1, kind="vertex", target=vertex_type)
        return result

    def upsert_vertex_rows(
        self,
        vertex_type: str,
        rows: list[dict[str, Any]],
        id_column: str,
    ) -> dict[str, Any]:
        """Bulk vertex upsert — one adapter call for a whole batch of CSV rows.

        This is the write path Run-All uses: against a remote TigerGraph it becomes a
        single RESTPP/pyTigerGraph upsert payload per batch instead of one HTTP call
        per row."""
        if not rows:
            return {"accepted_vertices": 0}
        vertices, _ = _manifest_index()
        manifest_entry = vertices.get(vertex_type) or {}
        columns = manifest_entry.get("columns") or {k: k for k in rows[0].keys()}
        entry = {
            "kind": "vertex",
            "target": vertex_type,
            "id_column": id_column,
            "columns": columns,
            "file": manifest_entry.get("file", vertex_type),
        }
        result = self.graph.upsert(entry, rows)
        self._raise_if_rejected(result, requested=len(rows), kind="vertex", target=vertex_type)
        return result

    def upsert_edge_rows(
        self,
        edge_type: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Bulk edge upsert — one adapter call per batch, schema metadata from the
        source-of-truth manifest (from/to types and columns)."""
        if not rows:
            return {"accepted_edges": 0}
        _, edges = _manifest_index()
        manifest_entry = edges.get(edge_type)
        if manifest_entry is None:
            raise RuntimeError(f"edge {edge_type} not in the manifest")
        entry = {
            "kind": "edge",
            "target": edge_type,
            "from_type": manifest_entry["from_type"],
            "to_type": manifest_entry["to_type"],
            "from_column": manifest_entry.get("from_column", "from_id"),
            "to_column": manifest_entry.get("to_column", "to_id"),
            "columns": manifest_entry.get("columns") or {k: k for k in rows[0].keys()},
            "file": manifest_entry.get("file", edge_type),
        }
        result = self.graph.upsert(entry, rows)
        self._raise_if_rejected(result, requested=len(rows), kind="edge", target=edge_type)
        return result

    def upsert_edge(
        self,
        edge_type: str,
        from_id: str,
        to_id: str,
        attributes: dict[str, Any] | None = None,
        from_type: str | None = None,
        to_type: str | None = None,
    ) -> dict[str, Any]:
        _, edges = _manifest_index()
        manifest_entry = edges.get(edge_type, {})
        resolved_from = from_type or manifest_entry.get("from_type")
        resolved_to = to_type or manifest_entry.get("to_type")
        if not resolved_from or not resolved_to:
            # Real engines require the endpoint vertex types; mock does not. Fail loudly
            # only for a live tier by letting the client surface it — but log the gap.
            _log.warning(
                "edge %s missing from_type/to_type (manifest gap); real upsert may reject",
                edge_type,
            )
            resolved_from = resolved_from or "unknown"
            resolved_to = resolved_to or "unknown"

        attrs = attributes or {}
        record = {"from_id": from_id, "to_id": to_id, **attrs}
        entry = {
            "kind": "edge",
            "target": edge_type,
            "from_type": resolved_from,
            "to_type": resolved_to,
            "from_column": "from_id",
            "to_column": "to_id",
            "columns": {k: k for k in attrs},
            "file": manifest_entry.get("file", edge_type),
        }
        result = self.graph.upsert(entry, [record])
        self._raise_if_rejected(result, requested=1, kind="edge", target=edge_type)
        return result

    @staticmethod
    def _raise_if_rejected(result: dict[str, Any], requested: int, kind: str, target: str) -> None:
        if result.get("error"):
            raise RuntimeError(result.get("message") or f"{kind} upsert failed for {target}")
        accepted_key = "accepted_vertices" if kind == "vertex" else "accepted_edges"
        accepted = result.get(accepted_key)
        if isinstance(accepted, int) and accepted < requested:
            raise RuntimeError(
                f"{kind} upsert for {target} accepted {accepted}/{requested} records"
            )
        # Checkpoint honesty. In a real mode the tiered client can fall back to the
        # local mock store; that "succeeds" without TigerGraph receiving a single
        # byte. Such a write must FAIL the batch (loudly, with remediation), never
        # be checkpointed as landed.
        mode = get_settings().graph_client_mode.lower()
        if mode not in {"mock", "local"} and result.get("served_by_tier") == 4:
            raise RuntimeError(
                f"{kind} upsert for {target} was served by the LOCAL FALLBACK tier, not TigerGraph "
                f"(GRAPH_CLIENT_MODE={mode}) — the write did NOT land in the real graph. "
                f"Check TigerGraph connectivity (/api/health / logs/app.log) and re-run; "
                f"the batch is marked FAILED and no row hashes were recorded."
            )
