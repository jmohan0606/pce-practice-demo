# TigerGraph DDL package — `phx_dm_pce_practice_demo`

Generated from the authoritative contract in `docs/spec/SCHEMA_SPEC.md`.
Target: TigerGraph 4.2.2, GSQL Syntax V1. Do not edit these files directly — change the spec first.

## File inventory

| File | Contents |
|---|---|
| `01_vertices.gsql` | 24 `CREATE VERTEX` statements (16 source-loaded, 8 app-written), each `WITH primary_id_as_attribute="true"` |
| `02_edges.gsql` | 36 `CREATE DIRECTED EDGE` statements, each `WITH REVERSE_EDGE` |
| `03_create_graph.gsql` | `CREATE GRAPH phx_dm_pce_practice_demo` listing all 24 vertex and 36 edge types (reverse edges are implied by the `WITH REVERSE_EDGE` clauses) |
| `90_drop_all.gsql` | Full teardown, in exact reverse of create order |
| `loading/load_<entity>.gsql` | 16 loading jobs, one per source-loaded vertex |
| `loading/load_edges.gsql` | One combined loading job for the 27 source-derivable edges (the app-written rules & insights edges are excluded — the app writes those directly) |
| `schema_catalog.json` | Machine-readable catalog (graph, vertices with primary id and typed attributes, edges with from/to/reverse) — drives typed coercion in the app's local graph store |

## Install order

1. `01_vertices.gsql`
2. `02_edges.gsql`
3. `03_create_graph.gsql`
4. `loading/*.gsql` (loading jobs; run vertex loads before `load_edges.gsql` so edge endpoints exist)

## Drop order

`90_drop_all.gsql` is the exact reverse of create order: `DROP GRAPH` first, then the 36 edges in
reverse of `02_edges.gsql`, then the 24 vertices in reverse of `01_vertices.gsql`. Keep it in sync
if the create scripts change.

## CSV contract and `QUOTE="double"`

One CSV per vertex and per edge, named exactly for the type, header row required. Vertex CSV columns
are exactly the vertex attributes in DDL order, primary id first. Edge CSVs have columns
`from_id,to_id`.

`QUOTE="double"` is **mandatory on every LOAD**: several columns carry JSON blobs
(e.g. `bullets_json`, `params_json`, `row_json`) and free text with embedded commas. Without the
quote setting, those values shear at the first comma and every downstream column shifts.
