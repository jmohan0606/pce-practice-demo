from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.config.settings import get_settings, resolve_app_path


class FoundationGraphStore:
    """In-memory graph loaded from the mock CSV data set.

    Loads the manifest-controlled CSVs (data/manifest.json + data/vertices/*.csv
    + data/edges/*.csv) into typed indexes so MockGraphClient query
    implementations can traverse the same graph the real GSQL queries traverse
    on TigerGraph.
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        settings = get_settings()
        if data_dir is not None:
            base = resolve_app_path(data_dir)
            self.manifest_path = base / "manifest.json"
        else:
            base = settings.resolved_data_dir
            self.manifest_path = settings.resolved_manifest_path
        # manifest entries' "file" values are relative to the data dir, e.g.
        # "vertices/phx_dm_pce_advisor.csv"
        self.base_dir = base
        # Typed attribute map — CSV values are cast to their DDL types so e.g.
        # month ids stay STRINGs, exactly as TigerGraph would return them.
        # The catalog is generated alongside the GSQL DDL; guard for absence.
        self.schema_types: dict[str, dict[str, str]] = {}
        schema_path = resolve_app_path("docs/tigergraph/schema_catalog.json")
        if schema_path.exists():
            catalog = json.loads(schema_path.read_text(encoding="utf-8"))
            self.schema_types = {
                vt: spec.get("attributes", {}) for vt, spec in catalog.get("vertices", {}).items()
            }

        # vertices[vertex_type][vertex_id] -> attribute dict (graph attribute names)
        self.vertices: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        # edges[edge_name] -> list of edge dicts {from_type, from_id, to_type, to_id, attrs}
        self.edges: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # out_index[edge_name][from_id] -> list of (to_id, attrs)
        self.out_index: dict[str, dict[str, list[tuple[str, dict[str, Any]]]]] = defaultdict(lambda: defaultdict(list))
        # in_index[edge_name][to_id] -> list of (from_id, attrs)
        self.in_index: dict[str, dict[str, list[tuple[str, dict[str, Any]]]]] = defaultdict(lambda: defaultdict(list))
        self.edge_meta: dict[str, dict[str, str]] = {}
        self.loaded = False
        self.load_report: dict[str, Any] = {}

    def available(self) -> bool:
        return self.manifest_path.exists() and self.base_dir.exists()

    def load(self) -> dict[str, Any]:
        if self.loaded:
            return self.load_report
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        vertex_rows = 0
        edge_rows = 0
        mismatches: list[str] = []
        for entry in manifest["files"]:
            path = self.base_dir / entry["file"]
            with path.open(newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            if entry.get("expected_rows") is not None and len(rows) != entry["expected_rows"]:
                mismatches.append(f"{entry['file']}: expected {entry['expected_rows']}, got {len(rows)}")
            if entry["kind"] == "vertex":
                vertex_type = entry["target"]
                id_col = entry["id_column"]
                columns = entry["columns"]
                for row in rows:
                    vertex_id = str(row[id_col]).strip()
                    attrs = {graph_attr: self.coerce_typed(vertex_type, graph_attr, row.get(src))
                             for src, graph_attr in columns.items()}
                    self.vertices[vertex_type][vertex_id] = attrs
                vertex_rows += len(rows)
            else:
                edge_name = entry["target"]
                from_col, to_col = entry["from_column"], entry["to_column"]
                columns = entry.get("columns", {})
                self.edge_meta[edge_name] = {"from_type": entry["from_type"], "to_type": entry["to_type"]}
                for row in rows:
                    from_id = str(row[from_col]).strip()
                    to_id = str(row[to_col]).strip()
                    attrs = {
                        graph_attr: _coerce(row.get(src))
                        for src, graph_attr in columns.items()
                        if src not in (from_col, to_col)
                    }
                    edge = {
                        "from_type": entry["from_type"],
                        "from_id": from_id,
                        "to_type": entry["to_type"],
                        "to_id": to_id,
                        "attrs": attrs,
                    }
                    self.edges[edge_name].append(edge)
                    self.out_index[edge_name][from_id].append((to_id, attrs))
                    self.in_index[edge_name][to_id].append((from_id, attrs))
                edge_rows += len(rows)
        self.loaded = True
        self.load_report = {
            "vertex_types": len(self.vertices),
            "edge_types": len(self.edges),
            "vertex_rows": vertex_rows,
            "edge_rows": edge_rows,
            "row_count_mismatches": mismatches,
        }
        # Mismatch fails loudly (build-plan rule): a CSV whose row count differs
        # from the manifest's expected_rows means the data set and the manifest
        # disagree — never load silently on top of that.
        if mismatches:
            raise RuntimeError(
                "FoundationGraphStore row-count mismatch vs manifest expected_rows: "
                + "; ".join(mismatches)
            )
        return self.load_report

    def coerce_typed(self, vertex_type: str, attr: str, value: Any) -> Any:
        """Cast a raw CSV/upsert value to its DDL type; falls back to the generic
        heuristic for types not in the schema catalog."""
        ddl_type = self.schema_types.get(vertex_type, {}).get(attr)
        if ddl_type is None:
            return _coerce(value)
        if value is None:
            return None
        if ddl_type in ("STRING", "DATETIME"):
            return str(value)
        text = str(value).strip()
        if text == "":
            return None
        try:
            if ddl_type == "INT":
                return int(float(text))
            if ddl_type == "DOUBLE":
                return float(text)
            if ddl_type == "BOOL":
                return text.lower() in {"true", "1", "yes"}
        except ValueError:
            return _coerce(value)
        return _coerce(value)

    # --- traversal helpers used by mock GQ implementations ---

    def vertex(self, vertex_type: str, vertex_id: str) -> dict[str, Any] | None:
        return self.vertices.get(vertex_type, {}).get(str(vertex_id))

    def remove_vertex(self, vertex_type: str, vertex_id: str) -> bool:
        """Remove a runtime vertex + all its edge-index entries (both directions)
        from the in-memory store. Returns True if removed."""
        vid = str(vertex_id)
        removed = self.vertices.get(vertex_type, {}).pop(vid, None) is not None
        for edge_name in list(self.edges.keys()):
            self.edges[edge_name] = [e for e in self.edges[edge_name] if e.get("from_id") != vid and e.get("to_id") != vid]
            if vid in self.out_index.get(edge_name, {}):
                self.out_index[edge_name].pop(vid, None)
            if vid in self.in_index.get(edge_name, {}):
                self.in_index[edge_name].pop(vid, None)
            # also strip vid from other nodes' adjacency lists
            for src, lst in self.out_index.get(edge_name, {}).items():
                self.out_index[edge_name][src] = [(t, a) for (t, a) in lst if t != vid]
            for dst, lst in self.in_index.get(edge_name, {}).items():
                self.in_index[edge_name][dst] = [(f, a) for (f, a) in lst if f != vid]
        return removed

    def remove_vertex_type(self, vertex_type: str) -> int:
        """Delete every vertex of a type and cascade-remove its edges (both
        directions), mirroring TigerGraph's vertex-delete semantics. Returns the
        number of vertices removed."""
        removed = len(self.vertices.get(vertex_type, {}))
        self.vertices.pop(vertex_type, None)
        for edge_name in list(self.edges.keys()):
            meta = self.edge_meta.get(edge_name, {})
            before = self.edges[edge_name]
            kept = [e for e in before if e.get("from_type") != vertex_type and e.get("to_type") != vertex_type]
            if len(kept) != len(before) or vertex_type in (meta.get("from_type"), meta.get("to_type")):
                self.edges[edge_name] = kept
                self._rebuild_edge_indexes(edge_name)
        return removed

    def remove_edge_type(self, edge_name: str) -> int:
        """Delete every edge of a type. Returns the number of edges removed."""
        removed = len(self.edges.get(edge_name, []))
        self.edges.pop(edge_name, None)
        self.out_index.pop(edge_name, None)
        self.in_index.pop(edge_name, None)
        return removed

    def _rebuild_edge_indexes(self, edge_name: str) -> None:
        self.out_index[edge_name] = defaultdict(list)
        self.in_index[edge_name] = defaultdict(list)
        for e in self.edges.get(edge_name, []):
            self.out_index[edge_name][e["from_id"]].append((e["to_id"], e.get("attrs", {})))
            self.in_index[edge_name][e["to_id"]].append((e["from_id"], e.get("attrs", {})))

    def all_vertices(self, vertex_type: str) -> dict[str, dict[str, Any]]:
        return self.vertices.get(vertex_type, {})

    def out(self, edge_name: str, from_id: str) -> list[tuple[str, dict[str, Any]]]:
        """Targets of edge_name leaving from_id: list of (to_id, edge_attrs)."""
        return self.out_index.get(edge_name, {}).get(str(from_id), [])

    def inbound(self, edge_name: str, to_id: str) -> list[tuple[str, dict[str, Any]]]:
        """Sources of edge_name arriving at to_id: list of (from_id, edge_attrs)."""
        return self.in_index.get(edge_name, {}).get(str(to_id), [])

    def out_ids(self, edge_name: str, from_id: str) -> list[str]:
        return [to_id for to_id, _ in self.out(edge_name, from_id)]

    def in_ids(self, edge_name: str, to_id: str) -> list[str]:
        return [from_id for from_id, _ in self.inbound(edge_name, to_id)]

    def statistics(self) -> dict[str, Any]:
        return {
            "vertex_counts": {t: len(v) for t, v in self.vertices.items()},
            "edge_counts": {t: len(e) for t, e in self.edges.items()},
        }


def _coerce(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value).strip()
    if text == "":
        return None
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


_store: FoundationGraphStore | None = None


def get_foundation_store() -> FoundationGraphStore:
    global _store
    if _store is None:
        _store = FoundationGraphStore()
        if _store.available():
            _store.load()
    return _store
