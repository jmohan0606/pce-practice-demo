"""Round E — validate and translate Rule Compiler plans.

The restricted expression grammar is GONE (it discarded 18 of 32 correct rules
for form). Rules are plain English (`statement`); the Rule Compiler agent
(app/agents/rule_compiler.py) produces a structured query plan JSON once per
rule at approval time. This module keeps ONLY the checks that protect the data
(ROUND_E_SPEC 1.3):

1. `vertex` exists in the schema catalog
2. every `field` exists on that vertex, or on a vertex reachable by a shared
   join key
3. every `params` entry is in the allowed set
4. `agg` is one of none | sum | count | count_distinct | avg | min | max
5. the plan EXECUTES against mock data without error and returns a row count
   (`execute_check`) — a plan that runs is valid; one that raises is not

`expr` strings are parsed into JSON node trees evaluated by the existing safe
evaluator over already-fetched rows — never eval, never string-concatenated
SQL, never a raw query from the model. Field-to-field comparison and string
ordering are ALLOWED (the two forms the old grammar wrongly rejected).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dc_field
from functools import lru_cache
from pathlib import Path
from typing import Any

# Round 8 task 4: "month" grain — a firm-level monthly aggregate (group by
# month_id). The grain set is app-level, not graph schema; the schema stays
# frozen at 31V/44E.
GRAINS = ("advisor", "account", "rpg", "household", "product", "transaction",
          "month")

# Join-candidate vertices per grain (the plan vertex may be any catalog vertex;
# extra fields resolve against these via a shared key).
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
        "phx_dm_pce_opportunity",
    ],
    "rpg": ["phx_dm_pce_rpg"],
    "household": ["phx_dm_pce_household"],
    "product": ["phx_dm_pce_product"],
    "transaction": ["phx_dm_pce_revenue_transaction"],
    "month": [
        "phx_dm_pce_month",
        "phx_dm_pce_revenue_transaction",
        "phx_dm_pce_monthly_revenue",
    ],
}

# The entity key a plan groups by, per grain (falls back to the vertex primary id).
GRAIN_KEYS = {
    "account": "acct_key",
    "advisor": "advisor_sid",
    "rpg": "rpg_id",
    "household": "eci_id",
    "product": "product_id",
    "transaction": "txn_id",
    "month": "month_id",
}

# Keys two vertices can be joined on, in preference order.
_JOIN_KEYS = ("acct_key", "advisor_sid", "month_id", "product_id")

NUMERIC_TYPES = {"INT", "UINT", "DOUBLE", "FLOAT"}

ALLOWED_PARAMS = ("month", "advisor_sid", "from_month", "to_month", "threshold")

# Round G task 1 — evaluation scopes a rule can run at. A rule whose plan
# references a scope parameter is restricted to the scopes that supply it;
# a rule with no scope parameter is scope-agnostic and runs everywhere.
SCOPES = ("practice", "advisor", "product", "product_advisor", "account")
_SCOPE_PARAM_IMPLIES: dict[str, tuple[str, ...]] = {
    "advisor_sid": ("advisor", "product_advisor", "account"),
}
ALLOWED_AGGS = ("none", "sum", "count", "count_distinct", "avg", "min", "max")
FILTER_OPS = ("=", "!=", ">", ">=", "<", "<=", "LIKE", "IN", "IS_NULL", "IS_NOT_NULL")
SCALAR_FUNCTIONS = ("round", "abs", "min", "max")

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "docs" / "tigergraph" / "schema_catalog.json"


@lru_cache(maxsize=1)
def load_schema_catalog() -> dict:
    with open(_CATALOG_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def vertex_attributes(vertex: str) -> dict[str, str]:
    return load_schema_catalog()["vertices"].get(vertex, {}).get("attributes", {})


def fields_for_grain(grain: str) -> dict[str, dict[str, str]]:
    return {vertex: vertex_attributes(vertex) for vertex in GRAIN_VERTICES.get(grain, [])}


@dataclass(frozen=True)
class CompileError:
    """A readable compile failure. Returned (not raised) by translate_plan."""

    rule_code: str
    stage: str  # vertex | fields | params | agg | expr | filters | execution
    message: str

    def __str__(self) -> str:
        return f"[{self.stage}] {self.message}"


@dataclass
class CompiledRule:
    rule_code: str
    grain: str
    plan: dict
    field_vertices: dict[str, str] = dc_field(default_factory=dict)


# --------------------------------------------------------------------------- node helpers

def collect_fields(node: Any) -> set[str]:
    """Every field name referenced anywhere in a node tree (incl. fieldrefs)."""
    fields: set[str] = set()
    if isinstance(node, dict):
        if node.get("type") in ("field", "fieldref"):
            fields.add(node["name"])
        if node.get("type") in ("cond", "in", "isnull"):
            fields.add(node["field"])
        for value in node.values():
            fields |= collect_fields(value)
    elif isinstance(node, list):
        for item in node:
            fields |= collect_fields(item)
    return fields


def collect_params(node: Any) -> set[str]:
    params: set[str] = set()
    if isinstance(node, dict):
        if node.get("type") == "param":
            params.add(node["name"])
        for value in node.values():
            params |= collect_params(value)
    elif isinstance(node, list):
        for item in node:
            params |= collect_params(item)
    return params


# --------------------------------------------------------------------------- expr parsing

class ExprError(ValueError):
    """An expr string could not be parsed into a safe evaluation tree."""


_EXPR_TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<param>:[A-Za-z_][A-Za-z0-9_]*)
      | (?P<number>\d+\.\d+|\d+)
      | (?P<string>'[^']*'|"[^"]*")
      | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
      | (?P<punct>[(),*+\-/])
    )""",
    re.VERBOSE,
)


def _expr_tokens(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        match = _EXPR_TOKEN_RE.match(text, pos)
        if match is None:
            remainder = text[pos:].lstrip()
            if not remainder:
                break
            raise ExprError(f"unexpected character {remainder[0]!r} in expression {text!r}")
        pos = match.end()
        for kind in ("param", "number", "string", "ident", "punct"):
            value = match.group(kind)
            if value is not None:
                tokens.append((kind, value))
                break
    return tokens


class _ExprParser:
    """Arithmetic over fields, numbers, :params, `value` and round/abs/min/max.
    Emits the evaluator's JSON node trees. This is plan TRANSLATION, not a
    grammar wall — a failure is a readable compile error on a machine-built
    plan, never a reason to discard a correct rule."""

    def __init__(self, tokens: list[tuple[str, str]], text: str) -> None:
        self.tokens = tokens
        self.pos = 0
        self.text = text

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self):
        token = self.peek()
        if token is None:
            raise ExprError(f"unexpected end of expression {self.text!r}")
        self.pos += 1
        return token

    def expect(self, char: str) -> None:
        token = self.peek()
        if token != ("punct", char):
            found = token[1] if token else "end"
            raise ExprError(f"expected {char!r} in {self.text!r}, found {found!r}")
        self.pos += 1

    def parse(self) -> dict:
        node = self.parse_expr()
        if self.pos < len(self.tokens):
            raise ExprError(f"trailing content {self.peek()[1]!r} in {self.text!r}")
        return node

    def parse_expr(self) -> dict:
        node = self.parse_term()
        while self.peek() in (("punct", "+"), ("punct", "-")):
            op = self.next()[1]
            node = {"type": "binop", "op": op, "left": node, "right": self.parse_term()}
        return node

    def parse_term(self) -> dict:
        node = self.parse_factor()
        while self.peek() in (("punct", "*"), ("punct", "/")):
            op = self.next()[1]
            node = {"type": "binop", "op": op, "left": node, "right": self.parse_factor()}
        return node

    def parse_factor(self) -> dict:
        token = self.peek()
        if token is None:
            raise ExprError(f"unexpected end of expression {self.text!r}")
        kind, value = token
        if token == ("punct", "("):
            self.next()
            node = self.parse_expr()
            self.expect(")")
            return node
        if token == ("punct", "-"):
            self.next()
            return {"type": "binop", "op": "-",
                    "left": {"type": "number", "value": 0},
                    "right": self.parse_factor()}
        if kind == "number":
            self.next()
            return {"type": "number", "value": float(value) if "." in value else int(value)}
        if kind == "param":
            self.next()
            return {"type": "param", "name": value[1:]}
        if kind == "ident":
            self.next()
            lowered = value.lower()
            if self.peek() == ("punct", "("):
                if lowered not in SCALAR_FUNCTIONS:
                    raise ExprError(
                        f"unknown function {value!r} — allowed: "
                        + ", ".join(SCALAR_FUNCTIONS))
                self.next()
                args = [self.parse_expr()]
                while self.peek() == ("punct", ","):
                    self.next()
                    args.append(self.parse_expr())
                self.expect(")")
                expected = 1 if lowered in ("round", "abs") else 2
                if len(args) != expected:
                    raise ExprError(f"{lowered}() takes {expected} argument(s), got {len(args)}")
                return {"type": "func", "name": lowered, "args": args}
            if lowered == "value":
                return {"type": "valueref"}
            return {"type": "field", "name": value}
        raise ExprError(f"unexpected token {value!r} in {self.text!r}")


def parse_expr(text: str) -> dict:
    """Parse one expr string into an evaluator node tree. Raises ExprError."""
    if not (text or "").strip():
        raise ExprError("expression is empty")
    return _ExprParser(_expr_tokens(text), text).parse()


# --------------------------------------------------------------------------- plan translation

def _literal_node(value: Any, rule_code: str) -> dict | CompileError:
    """A filter's `value` → an evaluator node. Forms:
    ':param' string → param; {'field': name} → fieldref (field-to-field
    comparison — allowed); bool/number/string → literal."""
    if isinstance(value, dict):
        name = value.get("field") or value.get("value_field")
        if not name:
            return CompileError(rule_code, "filters",
                                f"object filter value must be {{'field': <name>}}, got {value!r}")
        return {"type": "fieldref", "name": str(name)}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, (int, float)):
        return {"type": "number", "value": value}
    if isinstance(value, str):
        if value.startswith(":"):
            name = value[1:]
            if name not in ALLOWED_PARAMS:
                return CompileError(
                    rule_code, "params",
                    f"unknown parameter {value!r} — allowed: "
                    + ", ".join(f":{p}" for p in ALLOWED_PARAMS))
            return {"type": "param", "name": name}
        return {"type": "string", "value": value}
    if value is None:
        return CompileError(rule_code, "filters",
                            "filter value is null — use op IS_NULL / IS_NOT_NULL instead")
    return CompileError(rule_code, "filters", f"cannot use filter value {value!r}")


def _filters_node(filters: list, rule_code: str) -> dict | CompileError:
    """The plan's filter list → one AND node tree for the evaluator."""
    items: list[dict] = []
    for entry in filters or []:
        if not isinstance(entry, dict) or not entry.get("field"):
            return CompileError(rule_code, "filters",
                                f"each filter needs a 'field', got {entry!r}")
        fieldname = str(entry["field"])
        op = str(entry.get("op") or "=").upper().replace(" ", "_")
        if op == "<>":
            op = "!="
        if op not in FILTER_OPS:
            return CompileError(rule_code, "filters",
                                f"unknown filter op {entry.get('op')!r} — allowed: "
                                + ", ".join(FILTER_OPS))
        if op == "IS_NULL":
            items.append({"type": "isnull", "field": fieldname, "negated": False})
            continue
        if op == "IS_NOT_NULL":
            items.append({"type": "isnull", "field": fieldname, "negated": True})
            continue
        if op == "IN":
            values = entry.get("value")
            if not isinstance(values, list) or not values:
                return CompileError(rule_code, "filters",
                                    f"IN filter on {fieldname!r} needs a non-empty value list")
            nodes = []
            for v in values:
                node = _literal_node(v, rule_code)
                if isinstance(node, CompileError):
                    return node
                nodes.append(node)
            items.append({"type": "in", "field": fieldname, "values": nodes})
            continue
        node = _literal_node(entry.get("value"), rule_code)
        if isinstance(node, CompileError):
            return node
        items.append({"type": "cond", "field": fieldname, "op": op, "value": node})
    if not items:
        # an unfiltered plan is legal — the whole vertex (scoped by month/advisor
        # params automatically) is the population.
        return {"type": "and", "items": []}
    return items[0] if len(items) == 1 else {"type": "and", "items": items}


def _resolve_fields(vertex: str, grain: str, fields: set[str],
                    rule_code: str) -> dict[str, str] | CompileError:
    """field -> owning vertex: the plan vertex first, then the grain's join
    candidates. Unknown field → readable error naming where it was sought."""
    candidates = [vertex] + [v for v in GRAIN_VERTICES.get(grain, []) if v != vertex]
    resolution: dict[str, str] = {}
    for name in sorted(fields):
        owner = next((v for v in candidates if name in vertex_attributes(v)), None)
        if owner is None:
            return CompileError(
                rule_code, "fields",
                f"unknown field '{name}' on vertex '{vertex}' (also searched: "
                f"{', '.join(candidates[1:]) or '(none)'}) — field names must come "
                f"from schema_catalog.json")
        resolution[name] = owner
    return resolution


def translate_plan(rule_code: str, grain: str, plan_json: dict) -> CompiledRule | CompileError:
    """Checks 1–4 + node building: the Rule Compiler's plan JSON → the internal
    evaluator plan. Returns CompiledRule or a readable CompileError; never
    raises for a bad plan. Check 5 (execution) is `execute_check`."""
    grain = (grain or "").strip().lower()
    if grain not in GRAINS:
        return CompileError(rule_code, "fields",
                            f"unknown grain {grain!r} — expected one of {', '.join(GRAINS)}")
    if not isinstance(plan_json, dict):
        return CompileError(rule_code, "vertex", "plan is not an object")

    # 1. vertex exists
    vertex = str(plan_json.get("vertex") or "")
    if vertex not in load_schema_catalog()["vertices"]:
        return CompileError(rule_code, "vertex",
                            f"unknown vertex {vertex!r} — must be a schema_catalog.json vertex")

    # filters → node tree
    filters = _filters_node(plan_json.get("filters") or [], rule_code)
    if isinstance(filters, CompileError):
        return filters

    # 4. agg allowed; compute expr parsed
    compute_spec = plan_json.get("compute") or {}
    if not isinstance(compute_spec, dict):
        return CompileError(rule_code, "agg", f"compute must be an object, got {compute_spec!r}")
    agg = str(compute_spec.get("agg") or "none").lower()
    if agg not in ALLOWED_AGGS:
        return CompileError(rule_code, "agg",
                            f"unknown agg {agg!r} — allowed: " + " | ".join(ALLOWED_AGGS))
    expr_text = str(compute_spec.get("expr") or "").strip()
    try:
        if agg == "count" and expr_text in ("", "*"):
            compute: dict = {"type": "agg", "name": "count", "arg": {"type": "star"}}
        else:
            arg = parse_expr(expr_text)
            compute = arg if agg == "none" else {"type": "agg", "name": agg, "arg": arg}
    except ExprError as exc:
        return CompileError(rule_code, "expr", f"compute: {exc}")

    trigger_spec = plan_json.get("trigger") or {}
    op = str(trigger_spec.get("op") or ">").strip()
    if op == "<>":
        op = "!="
    if op not in ("=", "!=", ">", ">=", "<", "<="):
        return CompileError(rule_code, "expr", f"trigger op {op!r} not one of = != > >= < <=")
    try:
        threshold = float(trigger_spec.get("value", 0))
    except (TypeError, ValueError):
        return CompileError(rule_code, "expr",
                            f"trigger value must be a number, got {trigger_spec.get('value')!r}")
    trigger = {"type": "trigger", "op": op, "value": threshold}

    attribute = None
    attr_spec = plan_json.get("attribute")
    if isinstance(attr_spec, dict) and attr_spec.get("expr"):
        try:
            attribute = {"type": "attribute", "name": str(attr_spec.get("name") or "attribute"),
                         "expr": parse_expr(str(attr_spec["expr"]))}
        except ExprError as exc:
            return CompileError(rule_code, "expr", f"attribute: {exc}")

    # 2. every field exists on the vertex or a joinable vertex
    fields = collect_fields(filters) | collect_fields(compute)
    if attribute is not None:
        fields |= collect_fields(attribute)
    resolution = _resolve_fields(vertex, grain, fields, rule_code)
    if isinstance(resolution, CompileError):
        return resolution

    # 3. params in the allowed set (declared list + any :param found in nodes)
    declared = [str(p).lstrip(":") for p in plan_json.get("params") or []]
    found = collect_params(filters) | collect_params(compute) \
        | (collect_params(attribute) if attribute else set())
    bad = sorted(set(declared) - set(ALLOWED_PARAMS)) or sorted(found - set(ALLOWED_PARAMS))
    if bad:
        return CompileError(rule_code, "params",
                            f"parameter :{bad[0]} not in the allowed set "
                            + ", ".join(f":{p}" for p in ALLOWED_PARAMS))
    params = sorted(set(declared) | found)

    group_key = GRAIN_KEYS[grain]
    if group_key not in vertex_attributes(vertex):
        group_key = load_schema_catalog()["vertices"][vertex]["primary_id"]

    joins = []
    for name, owner in sorted(resolution.items()):
        if owner == vertex:
            continue
        via = next((k for k in _JOIN_KEYS
                    if k in vertex_attributes(vertex) and k in vertex_attributes(owner)), None)
        if via is None:
            return CompileError(
                rule_code, "fields",
                f"field '{name}' resolves to '{owner}' which cannot be joined to "
                f"'{vertex}' (no shared key among {', '.join(_JOIN_KEYS)})")
        joins.append({"field": name, "vertex": owner, "via": via})

    plan = {
        "vertex": vertex,
        "filters": filters,
        "aggregate": None if agg == "none" else (compute.get("name") if compute.get("type") == "agg" else None),
        "compute": compute,
        "trigger": trigger,
        "attribute": attribute,
        "group_by": group_key,
        "params": params,
        "joins": joins,
        "grain": grain,
        "population_fields": sorted(collect_fields(filters)),
    }
    return CompiledRule(rule_code=rule_code, grain=grain, plan=plan, field_vertices=resolution)


# --------------------------------------------------------------------------- check 5: execution

def _test_params() -> dict:
    """Benign parameter values from the mock data — every allowed param is
    supplied so check 5 exercises the plan itself, not parameter plumbing."""
    from app.graph.foundation_store import get_foundation_store

    store = get_foundation_store()
    months = sorted(store.all_vertices("phx_dm_pce_month"))
    advisors = sorted(store.all_vertices("phx_dm_pce_advisor"))
    return {
        "month": months[-1] if months else "202606",
        "from_month": months[0] if months else "202604",
        "to_month": months[-1] if months else "202606",
        "advisor_sid": advisors[0] if advisors else "V000001",
        "threshold": 0,
    }


def execute_check(compiled: CompiledRule) -> dict | CompileError:
    """Check 5 — the real gate: the plan runs against mock data and returns a
    row count. Returns {evaluated_rows, matched_count} or a CompileError."""
    import app.graph.queries.rules_evaluate  # noqa: F401 — registers the mock impl
    from app.graph.client import get_graph_client

    try:
        result = get_graph_client().run_query(
            "rules_evaluate_plan", {"plan": compiled.plan, "params": _test_params()})
        row = (result.get("results") or [{}])[0]
    except Exception as exc:  # noqa: BLE001 — a plan that raises is not valid
        return CompileError(compiled.rule_code, "execution",
                            f"plan raised against mock data: {type(exc).__name__}: {exc}")
    return {"evaluated_rows": row.get("evaluated_rows", 0),
            "matched_count": row.get("matched_count", 0)}


# --------------------------------------------------------------------------- scopes (Round G)

def derive_scopes(plan_json: dict | None,
                  plan_by_scope: dict[str, dict] | None = None) -> list[str]:
    """Default scope set for a rule, derived from its plan(s): a plan that
    references a scope parameter restricts the rule to the scopes that supply
    it; a scope with its own plan in plan_by_scope is applicable regardless.
    No scope parameter anywhere → all scopes (scope-agnostic)."""
    def _plan_params(plan: dict) -> set[str]:
        declared = {str(p).lstrip(":") for p in plan.get("params") or []}
        try:
            found = {str(v)[1:] for f in plan.get("filters") or []
                     if isinstance(f, dict) and isinstance(f.get("value"), str)
                     and str(f["value"]).startswith(":")}
        except Exception:  # noqa: BLE001 — malformed filters fail translation, not here
            found = set()
        return declared | found

    base_params = _plan_params(plan_json or {})
    restricting = [p for p in base_params if p in _SCOPE_PARAM_IMPLIES]
    if not restricting:
        scopes = set(SCOPES)
    else:
        scopes = set()
        for param in restricting:
            scopes |= set(_SCOPE_PARAM_IMPLIES[param])
    # a scope with its own dedicated plan is applicable by construction
    scopes |= {s for s in (plan_by_scope or {}) if s in SCOPES}
    return [s for s in SCOPES if s in scopes]


# --------------------------------------------------------------------------- rule-facing API

def compile_rule(rule: dict) -> CompiledRule | CompileError:
    """The stored rule's plan JSON → internal evaluator plan (checks 1–4)."""
    rule_code = rule.get("rule_code") or "(unnamed rule)"
    plan_json = rule.get("plan")
    if not isinstance(plan_json, dict):
        return CompileError(rule_code, "vertex",
                            "rule has no compiled plan — run the Rule Compiler first")
    return translate_plan(rule_code, rule.get("grain") or "", plan_json)


def validate_plan(rule_code: str, grain: str, plan_json: dict) -> dict:
    """All five checks in one call (the Rule Compiler agent's gate). Returns
    {ok, error?, compiled?, execution?}."""
    compiled = translate_plan(rule_code, grain, plan_json)
    if isinstance(compiled, CompileError):
        return {"ok": False, "error": str(compiled)}
    execution = execute_check(compiled)
    if isinstance(execution, CompileError):
        return {"ok": False, "error": str(execution)}
    return {"ok": True, "compiled": compiled, "execution": execution}


def compile_status(rule: dict) -> dict:
    """{compiled, compile_error, plan} for serialisation — reads the STORED
    compile outcome (set at compile time); never re-executes per request."""
    if rule.get("status") in ("COMPILED", "PUBLISHED", "SUPERSEDED") and rule.get("plan"):
        return {"compiled": True, "compile_error": None, "plan": rule.get("plan")}
    return {"compiled": False,
            "compile_error": rule.get("compile_error")
            or ("schema cannot express this rule: " + rule["needs_data_reason"]
                if rule.get("needs_data_reason") else None)
            or "not compiled yet — the Rule Compiler runs at approval",
            "plan": rule.get("plan")}
