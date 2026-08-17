#!/usr/bin/env python3
"""Round 1 (schema freeze) task 3 — migration parity.

Two install paths exist for the client environment:

  clean install:  01_vertices.gsql → 02_edges.gsql → 03_create_graph.gsql
  migrated:       Round-F2 schema (migrations/baseline_f2/) then EVERY
                  migrations/0NN_*.gsql in numeric order (001, 002, …)

If those two ever diverge, one environment silently differs from another —
this script asserts they cannot. It parses the GSQL (vertices with their
attribute name/type lists, edges with from/to/reverse), applies the migrations
to the committed F2 baseline snapshot IN MEMORY, and requires the result to
EQUAL the clean-install schema exactly. It also asserts every migration is
data-safe (no DROP / DELETE / UPDATE / CLEAR / loading statement) and that
schema_catalog.json agrees with the DDL — the app resolves fields there, so a
catalog/DDL mismatch is the same silent-divergence failure.

Run: python3 scripts/verify_schema_parity.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TG = ROOT / "docs" / "tigergraph"

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("//")[0] for line in text.splitlines())


def _parse_attrs(body: str) -> dict[str, str]:
    """'PRIMARY_ID x STRING, a STRING, b DOUBLE' -> {x: STRING, a: STRING, ...}"""
    attrs: dict[str, str] = {}
    for part in body.split(","):
        part = part.strip()
        if not part:
            continue
        part = re.sub(r"^PRIMARY_ID\s+", "", part)
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s+([A-Z][A-Z0-9]*)", part)
        if m:
            attrs[m.group(1)] = m.group(2)
    return attrs


def parse_vertices(text: str) -> dict[str, dict[str, str]]:
    text = _strip_comments(text)
    out: dict[str, dict[str, str]] = {}
    for m in re.finditer(
            r"CREATE\s+VERTEX\s+([A-Za-z0-9_]+)\s*\((.*?)\)\s*WITH",
            text, re.S | re.I):
        out[m.group(1)] = _parse_attrs(m.group(2))
    return out


def parse_edges(text: str) -> dict[str, tuple[str, str, str]]:
    text = _strip_comments(text)
    out: dict[str, tuple[str, str, str]] = {}
    for m in re.finditer(
            r"CREATE\s+DIRECTED\s+EDGE\s+([A-Za-z0-9_]+)\s*\(\s*FROM\s+([A-Za-z0-9_]+)\s*,"
            r"\s*TO\s+([A-Za-z0-9_]+)\s*\)\s*WITH\s+REVERSE_EDGE\s*=\s*\"([A-Za-z0-9_]+)\"",
            text, re.S | re.I):
        out[m.group(1)] = (m.group(2), m.group(3), m.group(4))
    return out


def parse_alters(text: str) -> dict[str, dict[str, str]]:
    text = _strip_comments(text)
    out: dict[str, dict[str, str]] = {}
    for m in re.finditer(
            r"ALTER\s+VERTEX\s+([A-Za-z0-9_]+)\s+ADD\s+ATTRIBUTE\s*\((.*?)\)\s*;",
            text, re.S | re.I):
        out.setdefault(m.group(1), {}).update(_parse_attrs(m.group(2)))
    return out


def main() -> int:
    clean_v = parse_vertices((TG / "01_vertices.gsql").read_text())
    clean_e = parse_edges((TG / "02_edges.gsql").read_text())
    base_v = parse_vertices((TG / "migrations" / "baseline_f2" / "01_vertices.gsql").read_text())
    base_e = parse_edges((TG / "migrations" / "baseline_f2" / "02_edges.gsql").read_text())
    mig_files = sorted((TG / "migrations").glob("0[0-9][0-9]_*.gsql"))

    # 1 — no migration contains a data-touching statement
    for mf in mig_files:
        stripped = _strip_comments(mf.read_text()).upper()
        dangerous = [kw for kw in ("DROP ", "DELETE ", "UPDATE ", "CLEAR GRAPH",
                                   "LOAD ", "LOADING JOB", "TRUNCATE")
                     if kw in stripped]
        check(f"SP-1 {mf.name} is data-safe (no DROP/DELETE/UPDATE/CLEAR/LOAD)",
              not dangerous,
              f"forbidden statements found: {dangerous}" if dangerous else "")

    # 2 — apply every migration, in order, to the F2 baseline in memory
    migrated_v = {name: dict(attrs) for name, attrs in base_v.items()}
    migrated_e = dict(base_e)
    for mf in mig_files:
        mig_text = mf.read_text()
        for name, attrs in parse_vertices(mig_text).items():
            check(f"SP-2 {mf.name} creates {name} as a NEW vertex",
                  name not in migrated_v)
            migrated_v[name] = attrs
        for name, spec in parse_edges(mig_text).items():
            check(f"SP-2 {mf.name} creates {name} as a NEW edge",
                  name not in migrated_e)
            migrated_e[name] = spec
        for name, attrs in parse_alters(mig_text).items():
            check(f"SP-2 {mf.name} alters an EXISTING vertex {name}",
                  name in migrated_v)
            overlap = sorted(set(attrs) & set(migrated_v.get(name, {})))
            check(f"SP-2 {mf.name} {name} ALTER adds only new attributes",
                  not overlap, f"already present: {overlap}" if overlap else "")
            migrated_v.setdefault(name, {}).update(attrs)

    # 3 — migrated baseline == clean install, exactly
    only_clean = sorted(set(clean_v) - set(migrated_v))
    only_migrated = sorted(set(migrated_v) - set(clean_v))
    check("SP-3 vertex type sets identical", not only_clean and not only_migrated,
          f"clean-only={only_clean} migrated-only={only_migrated}"
          if only_clean or only_migrated else f"{len(clean_v)} vertex types")
    diffs = []
    for name in sorted(set(clean_v) & set(migrated_v)):
        if clean_v[name] != migrated_v[name]:
            missing = sorted(set(clean_v[name].items()) - set(migrated_v[name].items()))
            extra = sorted(set(migrated_v[name].items()) - set(clean_v[name].items()))
            diffs.append(f"{name}: clean-not-migrated={missing} migrated-not-clean={extra}")
    check("SP-4 every vertex's attributes identical (names AND types)",
          not diffs, "; ".join(diffs))
    e_only_clean = sorted(set(clean_e) - set(migrated_e))
    e_only_migrated = sorted(set(migrated_e) - set(clean_e))
    e_diffs = [f"{n}: clean={clean_e[n]} migrated={migrated_e[n]}"
               for n in sorted(set(clean_e) & set(migrated_e))
               if clean_e[n] != migrated_e[n]]
    check("SP-5 edge type sets + from/to/reverse identical",
          not e_only_clean and not e_only_migrated and not e_diffs,
          f"clean-only={e_only_clean} migrated-only={e_only_migrated} diffs={e_diffs}"
          if e_only_clean or e_only_migrated or e_diffs else f"{len(clean_e)} edge types")

    # 4 — 03_create_graph lists every type exactly once
    graph_text = _strip_comments((TG / "03_create_graph.gsql").read_text())
    names = [n for n in re.findall(r"phx_dm_pce_[a-z0-9_]+", graph_text)
             if n != "phx_dm_pce_practice_demo"]  # the graph's own name
    listed = set(names)
    expected = set(clean_v) | set(clean_e)
    check("SP-6 03_create_graph lists every vertex+edge type exactly once",
          listed == expected and len(names) == len(expected),
          f"missing={sorted(expected - listed)} extra={sorted(listed - expected)} "
          f"dupes={sorted({n for n in names if names.count(n) > 1})}"
          if listed != expected or len(names) != len(expected)
          else f"{len(expected)} types")

    # 5 — schema_catalog.json agrees with the DDL (the app resolves fields there)
    catalog = json.loads((TG / "schema_catalog.json").read_text())
    cat_v = {name: {k: v for k, v in spec["attributes"].items()}
             for name, spec in catalog["vertices"].items()}
    cat_e = {name: (spec["from"], spec["to"], spec["reverse"])
             for name, spec in catalog["edges"].items()}
    check("SP-7 schema_catalog vertices == DDL vertices (names, attrs, types)",
          cat_v == clean_v,
          "; ".join(f"{n}: cat={cat_v.get(n)} ddl={clean_v.get(n)}"
                    for n in sorted(set(cat_v) ^ set(clean_v))
                    or [n for n in clean_v if cat_v.get(n) != clean_v[n]][:3])
          if cat_v != clean_v else f"{len(cat_v)} vertices")
    check("SP-8 schema_catalog edges == DDL edges", cat_e == clean_e,
          f"diff={sorted(set(cat_e.items()) ^ set(clean_e.items()))[:4]}"
          if cat_e != clean_e else f"{len(cat_e)} edges")

    # 6 — drop order is the exact reverse of create order
    drop_text = _strip_comments((TG / "90_drop_all.gsql").read_text())
    drop_edges = re.findall(r"DROP\s+EDGE\s+([A-Za-z0-9_]+)", drop_text)
    drop_vertices = re.findall(r"DROP\s+VERTEX\s+([A-Za-z0-9_]+)", drop_text)
    create_edge_order = list(parse_edges((TG / "02_edges.gsql").read_text()))
    create_vertex_order = list(parse_vertices((TG / "01_vertices.gsql").read_text()))
    check("SP-9 90_drop_all drops edges then vertices in exact reverse create order",
          drop_edges == create_edge_order[::-1]
          and drop_vertices == create_vertex_order[::-1])

    print(f"\n{len(FAILURES)} failure(s)" if FAILURES
          else f"\nall checks passed — migrations "
               f"({', '.join(mf.name.split('_')[0] for mf in mig_files)}) "
               f"== clean install ({len(clean_v)} vertices / {len(clean_e)} edges)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
