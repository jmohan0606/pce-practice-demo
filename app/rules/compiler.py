"""B3.3 — compile a rule against the graph schema.

``compile_rule(rule) -> CompiledRule | CompileError``

1. Parse each expression against the narrow grammar (app/rules/grammar.py)
2. Resolve every field against docs/tigergraph/schema_catalog.json for the
   declared grain — an unknown field is a compile error naming the field AND
   the vertex it was sought on
3. Type-check: arithmetic needs numeric fields; comparisons need compatible types
4. Emit a query plan: {vertex, filters, aggregate, group_by, params} (+ the
   compute/trigger/attribute trees and join specs the evaluator needs)

An uncompilable rule cannot be approved.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from functools import lru_cache
from pathlib import Path

from app.rules.grammar import (
    GrammarError,
    collect_fields,
    collect_params,
    parse_attribute,
    parse_compute,
    parse_population,
    parse_trigger,
)

GRAINS = ("advisor", "account", "rpg", "household", "product", "transaction")

# The vertices a grain's fields resolve against, in priority order. The first
# vertex is the grain's home; the driving vertex of the query plan is the one
# that resolves the most referenced fields (ties break by this order).
GRAIN_VERTICES: dict[str, list[str]] = {
    "account": [
        "phx_dm_pce_account_month",
        "phx_dm_pce_account",
        "phx_dm_pce_account_transfer",
        "phx_dm_pce_revenue_transaction",
    ],
    "advisor": [
        "phx_dm_pce_advisor",
        "phx_dm_pce_month",
        "phx_dm_pce_monthly_revenue",
        "phx_dm_pce_advisor_flow_month",
    ],
    "rpg": ["phx_dm_pce_rpg"],
    "household": ["phx_dm_pce_household"],
    "product": ["phx_dm_pce_product"],
    "transaction": ["phx_dm_pce_revenue_transaction"],
}

# The entity key a plan groups by, per grain (falls back to the vertex primary id).
GRAIN_KEYS = {
    "account": "acct_key",
    "advisor": "advisor_sid",
    "rpg": "rpg_id",
    "household": "eci_id",
    "product": "product_id",
    "transaction": "txn_id",
}

# Keys two vertices can be joined on, in preference order.
_JOIN_KEYS = ("acct_key", "advisor_sid", "month_id", "product_id")

NUMERIC_TYPES = {"INT", "UINT", "DOUBLE", "FLOAT"}

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "docs" / "tigergraph" / "schema_catalog.json"


@lru_cache(maxsize=1)
def load_schema_catalog() -> dict:
    with open(_CATALOG_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def vertex_attributes(vertex: str) -> dict[str, str]:
    return load_schema_catalog()["vertices"].get(vertex, {}).get("attributes", {})


def fields_for_grain(grain: str) -> dict[str, dict[str, str]]:
    """vertex -> {field: DDL type} for every vertex in a grain's resolution set.
    Used both by the compiler and to inject the field list into the extractor prompt."""
    return {vertex: vertex_attributes(vertex) for vertex in GRAIN_VERTICES.get(grain, [])}


@dataclass(frozen=True)
class CompileError:
    """A readable compile failure. Returned (not raised) by compile_rule."""

    rule_code: str
    stage: str  # population | compute | trigger | attribute | grain | fields | types
    message: str

    def __str__(self) -> str:
        return f"[{self.stage}] {self.message}"


@dataclass
class CompiledRule:
    rule_code: str
    grain: str
    plan: dict
    field_vertices: dict[str, str] = dc_field(default_factory=dict)


def _resolve_fields(grain: str, fields: set[str], rule_code: str) -> dict[str, str] | CompileError:
    """field -> owning vertex, searched across the grain's vertex set.
    Unknown field → CompileError naming the field and the vertex it was sought on."""
    vertices = GRAIN_VERTICES[grain]
    resolution: dict[str, str] = {}
    for name in sorted(fields):
        owner = next((v for v in vertices if name in vertex_attributes(v)), None)
        if owner is None:
            searched = ", ".join(vertices[1:]) or "(none)"
            return CompileError(
                rule_code, "fields",
                f"unknown field '{name}' on vertex '{vertices[0]}' (grain '{grain}'; "
                f"also searched: {searched}) — field names must come from schema_catalog.json",
            )
        resolution[name] = owner
    return resolution


def _pick_driving_vertex(grain: str, resolution: dict[str, str]) -> str:
    vertices = GRAIN_VERTICES[grain]
    votes = {v: sum(1 for owner in resolution.values() if owner == v) for v in vertices}
    return max(vertices, key=lambda v: (votes[v], -vertices.index(v)))


def _field_type(name: str, resolution: dict[str, str]) -> str:
    return vertex_attributes(resolution[name]).get(name, "STRING")


def _expr_type(node: dict, resolution: dict[str, str], rule_code: str, stage: str) -> str | CompileError:
    """Type of an expr node: 'NUMERIC' | 'STRING' | 'BOOL' | 'DATETIME'."""
    kind = node.get("type")
    if kind == "number" or kind == "valueref" or kind == "star":
        return "NUMERIC"
    if kind == "string":
        return "STRING"
    if kind == "bool":
        return "BOOL"
    if kind == "param":
        return "PARAM"  # params compare with anything (month ids are strings, threshold numeric)
    if kind == "field":
        ddl = _field_type(node["name"], resolution)
        return "NUMERIC" if ddl in NUMERIC_TYPES else ddl
    if kind == "binop":
        for side in ("left", "right"):
            side_type = _expr_type(node[side], resolution, rule_code, stage)
            if isinstance(side_type, CompileError):
                return side_type
            if side_type not in ("NUMERIC", "PARAM"):
                offender = node[side].get("name", node[side].get("value"))
                return CompileError(
                    rule_code, "types",
                    f"{stage}: arithmetic '{node['op']}' needs numeric operands but "
                    f"'{offender}' is {side_type}",
                )
        return "NUMERIC"
    if kind == "func":
        for arg in node["args"]:
            arg_type = _expr_type(arg, resolution, rule_code, stage)
            if isinstance(arg_type, CompileError):
                return arg_type
            if arg_type not in ("NUMERIC", "PARAM"):
                return CompileError(
                    rule_code, "types",
                    f"{stage}: {node['name']}() needs numeric arguments, got {arg_type}",
                )
        return "NUMERIC"
    return CompileError(rule_code, "types", f"{stage}: cannot type node {kind!r}")


def _check_population_types(node: dict, resolution: dict[str, str], rule_code: str) -> CompileError | None:
    kind = node.get("type")
    if kind in ("and", "or"):
        for item in node["items"]:
            error = _check_population_types(item, resolution, rule_code)
            if error is not None:
                return error
        return None
    if kind == "isnull":
        return None
    if kind == "in":
        field_type = _expr_type({"type": "field", "name": node["field"]}, resolution, rule_code, "population")
        for literal in node["values"]:
            lit_type = _expr_type(literal, resolution, rule_code, "population")
            if lit_type not in (field_type, "PARAM"):
                return CompileError(
                    rule_code, "types",
                    f"population: IN list value type {lit_type} does not match field "
                    f"'{node['field']}' ({field_type})",
                )
        return None
    if kind == "cond":
        field_type = _expr_type({"type": "field", "name": node["field"]}, resolution, rule_code, "population")
        if isinstance(field_type, CompileError):
            return field_type
        value_type = _expr_type(node["value"], resolution, rule_code, "population")
        if isinstance(value_type, CompileError):
            return value_type
        op = node["op"]
        if op == "LIKE" and field_type != "STRING":
            return CompileError(
                rule_code, "types",
                f"population: LIKE needs a STRING field but '{node['field']}' is {field_type}",
            )
        if op in (">", ">=", "<", "<=") and field_type not in ("NUMERIC", "DATETIME"):
            return CompileError(
                rule_code, "types",
                f"population: ordering comparison '{op}' needs a numeric or datetime field "
                f"but '{node['field']}' is {field_type}",
            )
        if value_type != "PARAM" and op in ("=", "!=") and value_type != field_type:
            # month_id-style string fields compared to string literals are fine;
            # anything cross-type (bool vs number etc.) is an error.
            if not (field_type == "DATETIME" and value_type == "STRING"):
                return CompileError(
                    rule_code, "types",
                    f"population: '{node['field']}' ({field_type}) compared with a "
                    f"{value_type} literal — incompatible types",
                )
        if value_type != "PARAM" and op in (">", ">=", "<", "<=") and value_type not in ("NUMERIC", "STRING"):
            return CompileError(
                rule_code, "types",
                f"population: '{op}' right-hand side must be numeric, got {value_type}",
            )
        return None
    return CompileError(rule_code, "types", f"population: cannot check node {kind!r}")


def compile_rule(rule: dict) -> CompiledRule | CompileError:
    """Compile one rule dict (B3.1 shape — `population`/`compute`/`trigger`/
    `attribute` keys, or the stored *_expr aliases). Returns a CompiledRule or a
    CompileError; never raises for a bad rule."""
    rule_code = rule.get("rule_code") or "(unnamed rule)"
    grain = (rule.get("grain") or "").strip().lower()
    if grain not in GRAINS:
        return CompileError(rule_code, "grain",
                            f"unknown grain {grain!r} — expected one of {', '.join(GRAINS)}")

    population_src = rule.get("population", rule.get("population_expr", ""))
    compute_src = rule.get("compute", rule.get("compute_expr", ""))
    trigger_src = rule.get("trigger", rule.get("trigger_expr", ""))
    attribute_src = rule.get("attribute", rule.get("attribute_expr", ""))

    try:
        population = parse_population(population_src)
    except GrammarError as exc:
        return CompileError(rule_code, "population", str(exc))
    try:
        compute = parse_compute(compute_src)
    except GrammarError as exc:
        return CompileError(rule_code, "compute", str(exc))
    try:
        trigger = parse_trigger(trigger_src)
    except GrammarError as exc:
        return CompileError(rule_code, "trigger", str(exc))
    try:
        attribute = parse_attribute(attribute_src)
    except GrammarError as exc:
        return CompileError(rule_code, "attribute", str(exc))

    fields = collect_fields(population) | collect_fields(compute)
    if attribute is not None:
        fields |= collect_fields(attribute)
    resolution = _resolve_fields(grain, fields, rule_code)
    if isinstance(resolution, CompileError):
        return resolution

    error = _check_population_types(population, resolution, rule_code)
    if error is not None:
        return error
    compute_expr = compute["arg"] if compute.get("type") == "agg" else compute
    if compute_expr.get("type") != "star":
        compute_type = _expr_type(compute_expr, resolution, rule_code, "compute")
        if isinstance(compute_type, CompileError):
            return compute_type
        aggregate = compute.get("name") if compute.get("type") == "agg" else None
        if aggregate in ("sum", "avg") and compute_type not in ("NUMERIC", "PARAM"):
            return CompileError(rule_code, "types",
                                f"compute: {aggregate}() needs a numeric expression, got {compute_type}")
    if attribute is not None:
        attr_type = _expr_type(attribute["expr"], resolution, rule_code, "attribute")
        if isinstance(attr_type, CompileError):
            return attr_type

    vertex = _pick_driving_vertex(grain, resolution)
    group_key = GRAIN_KEYS[grain]
    if group_key not in vertex_attributes(vertex):
        group_key = load_schema_catalog()["vertices"][vertex]["primary_id"]

    joins = []
    for name, owner in sorted(resolution.items()):
        if owner == vertex:
            continue
        via = next(
            (k for k in _JOIN_KEYS if k in vertex_attributes(vertex) and k in vertex_attributes(owner)),
            None,
        )
        if via is None:
            return CompileError(
                rule_code, "fields",
                f"field '{name}' resolves to '{owner}' which cannot be joined to the "
                f"driving vertex '{vertex}' (no shared key among {', '.join(_JOIN_KEYS)})",
            )
        joins.append({"field": name, "vertex": owner, "via": via})

    params = sorted(collect_params(population) | collect_params(compute)
                    | (collect_params(attribute) if attribute is not None else set()))
    plan = {
        "vertex": vertex,
        "filters": population,
        "aggregate": compute.get("name") if compute.get("type") == "agg" else None,
        "compute": compute,
        "trigger": trigger,
        "attribute": attribute,
        "group_by": group_key,
        "params": params,
        "joins": joins,
        "grain": grain,
        "population_fields": sorted(collect_fields(population)),
    }
    return CompiledRule(rule_code=rule_code, grain=grain, plan=plan, field_vertices=resolution)


def compile_status(rule: dict) -> dict:
    """{compiled: bool, compile_error: str|None, plan: dict|None} — the shape the
    API attaches to every serialised rule so the UI can show the error on the card."""
    result = compile_rule(rule)
    if isinstance(result, CompileError):
        return {"compiled": False, "compile_error": str(result), "plan": None}
    return {"compiled": True, "compile_error": None, "plan": result.plan}
