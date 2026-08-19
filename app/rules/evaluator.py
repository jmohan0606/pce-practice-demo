"""Execute a compiled rule's query plan against the local graph store.

Pure functions over a FoundationGraphStore — registered as the mock-tier
implementation of the ``rules_evaluate_plan`` query in
app/graph/queries/rules_evaluate.py, so services run plans through the tiered
graph client like any other catalogued query.

Semantics:
- rows come from the plan's driving vertex; when the caller passes a `month`
  (or `advisor_sid`) parameter and the vertex carries that attribute, rows are
  scoped to it automatically (the seed rules rely on this scoping).
- joined fields (plan.joins) are merged onto each row via the shared key.
- population filters run per row; compute is aggregated per group_by key (or
  evaluated per row when non-aggregate); trigger selects matches; attribute
  (if any) is computed with `value` bound to the compute result.
- `exclude_keys` removes entity keys claimed by an earlier rule in the
  evaluation order (B3.7: transferred accounts are excluded from the lost
  population).
- Baseline guard: a rule whose population requires `present_prior_month` can
  never fire in a baseline month (no prior month exists) — it returns an EMPTY
  result with a reason, never an error.
"""
from __future__ import annotations

from typing import Any

from app.rules.compiler import collect_fields


class EvaluationError(RuntimeError):
    pass


def _literal(node: dict, params: dict) -> Any:
    kind = node["type"]
    if kind in ("number", "string", "bool"):
        return node["value"]
    if kind == "param":
        name = node["name"]
        if name not in params or params[name] in (None, ""):
            raise EvaluationError(f"required parameter :{name} was not supplied")
        return params[name]
    raise EvaluationError(f"cannot evaluate literal node {kind!r}")


def _filter_value(node: dict, row: dict, params: dict) -> Any:
    """A filter's right-hand side: literal / :param / another field's value."""
    if node.get("type") == "fieldref":
        return row.get(node["name"])
    return _literal(node, params)


def _row_matches(node: dict, row: dict, params: dict) -> bool:
    kind = node["type"]
    if kind == "and":
        return all(_row_matches(item, row, params) for item in node["items"])
    if kind == "or":
        return any(_row_matches(item, row, params) for item in node["items"])
    if kind == "isnull":
        is_null = row.get(node["field"]) in (None, "")
        return (not is_null) if node["negated"] else is_null
    if kind == "in":
        actual = row.get(node["field"])
        return any(_loose_eq(actual, _filter_value(v, row, params)) for v in node["values"])
    if kind == "cond":
        actual = row.get(node["field"])
        # fieldref value → field-to-field comparison (Round E: explicitly allowed)
        expected = _filter_value(node["value"], row, params)
        op = node["op"]
        if actual is None:
            return False
        if op == "=":
            return _loose_eq(actual, expected)
        if op == "!=":
            return not _loose_eq(actual, expected)
        if op == "LIKE":
            pattern = str(expected)
            text = str(actual)
            if pattern.startswith("%") and pattern.endswith("%"):
                return pattern.strip("%") in text
            if pattern.endswith("%"):
                return text.startswith(pattern.rstrip("%"))
            if pattern.startswith("%"):
                return text.endswith(pattern.lstrip("%"))
            return text == pattern
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError):
            left, right = str(actual), str(expected)  # type: ignore[assignment]
        return {"<": left < right, "<=": left <= right,
                ">": left > right, ">=": left >= right}[op]
    raise EvaluationError(f"cannot evaluate filter node {kind!r}")


def _loose_eq(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return _to_bool(actual) == _to_bool(expected)
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return float(actual) == float(expected)
        except (TypeError, ValueError):
            return False
    return str(actual) == str(expected)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _eval_expr(node: dict, row: dict, params: dict, value: float | None = None) -> float:
    kind = node["type"]
    if kind == "number":
        return node["value"]
    if kind == "param":
        return float(_literal(node, params))
    if kind == "valueref":
        if value is None:
            raise EvaluationError("'value' referenced before compute produced one")
        return value
    if kind == "field":
        raw = row.get(node["name"])
        if raw in (None, ""):
            return 0.0
        try:
            return float(raw)
        except (TypeError, ValueError) as exc:
            raise EvaluationError(f"field {node['name']!r} is not numeric: {raw!r}") from exc
    if kind == "binop":
        left = _eval_expr(node["left"], row, params, value)
        right = _eval_expr(node["right"], row, params, value)
        if node["op"] == "+":
            return left + right
        if node["op"] == "-":
            return left - right
        if node["op"] == "*":
            return left * right
        if right == 0:
            raise EvaluationError("division by zero in compute expression")
        return left / right
    if kind == "func":
        args = [_eval_expr(arg, row, params, value) for arg in node["args"]]
        if node["name"] == "round":
            return float(round(args[0]))
        if node["name"] == "abs":
            return abs(args[0])
        if node["name"] == "min":
            return min(args)
        return max(args)
    raise EvaluationError(f"cannot evaluate expression node {kind!r}")


def _trigger_fires(trigger: dict, value: float) -> bool:
    threshold = trigger["value"]
    return {"=": value == threshold, "!=": value != threshold,
            ">": value > threshold, ">=": value >= threshold,
            "<": value < threshold, "<=": value <= threshold}[trigger["op"]]


# Plan predicates the row-source query can apply server-side (Round 10 task
# 6a). Each name here must be a declared rule_evaluation_rows parameter with a
# matching WHERE clause in the GSQL twin — the twin cannot reference an
# attribute by a runtime name, so pushdown is per-parameter, not generic.
PUSHDOWN_FIELDS = ("reason_cd",)


def _pushdown_filters(filters: dict | None) -> dict[str, str]:
    """Top-level AND'ed simple equality predicates (literal value) on
    PUSHDOWN_FIELDS. Conjunctive, so the Python filter re-applying them is a
    no-op — same rows out, less shipped."""
    node = filters or {}
    items = node.get("items") if node.get("type") == "and" else [node]
    out: dict[str, str] = {}
    for item in items or []:
        if (isinstance(item, dict) and item.get("type") == "cond"
                and item.get("op") == "=" and item.get("field") in PUSHDOWN_FIELDS):
            value = item.get("value") or {}
            if value.get("type") in ("string", "number"):
                out[str(item["field"])] = str(value["value"])
    return out


def _fetch_rows(vertex: str, month: str | None = None,
                advisor_sid: str | None = None,
                key: str | None = None,
                columns: set[str] | None = None,
                pushdown: dict[str, str] | None = None) -> list[dict]:
    """Round 8 (client-env bug fix) — the evaluator's ONE row source: the
    internal ``rule_evaluation_rows`` catalog query, through the tiered graph
    client. In mock mode the mock tier serves it (results identical to the old
    direct store read — proven); in real mode it reaches TigerGraph like every
    other query, so rules stop silently evaluating against mock rows while the
    dashboard shows real figures. The evaluator itself stays Python-interpreted
    (the recorded decision) — only WHERE the rows come from changed.

    Round 9 task 4: every available filter (month / advisor_sid / key) rides
    the query so the serving tier filters BEFORE returning rows, and
    ``columns`` projects the result to only the attributes the plan
    references — the full vertex is never materialised into the response."""
    from app.graph.queries.catalog import run_catalog_query

    params: dict = {"vertex_type": vertex}
    if month not in (None, ""):
        params["month"] = str(month)
    if advisor_sid not in (None, ""):
        params["advisor_sid"] = str(advisor_sid)
    if key not in (None, ""):
        params["key_id"] = str(key)
    if columns:
        params["columns"] = ",".join(sorted(columns))
    for field, value in (pushdown or {}).items():
        params.setdefault(field, value)
    return run_catalog_query("rule_evaluation_rows", params,
                             allow_internal=True)["rows"]


def _plan_columns(plan: dict) -> set[str]:
    """Every field the plan can touch — filters, compute, attribute, group_by,
    join keys, plus month_id (the join disambiguator). This is the projection
    _fetch_rows requests so no unused column is materialised or shipped."""
    needed = set(collect_fields(plan.get("filters")))
    needed |= collect_fields(plan.get("compute"))
    needed |= collect_fields(plan.get("attribute"))
    needed |= set(plan.get("population_fields") or [])
    needed.add(str(plan.get("group_by") or ""))
    needed.add("month_id")
    for join in plan.get("joins", []):
        needed.add(str(join.get("via") or ""))
    needed.discard("")
    return needed


def _join_rows(plan: dict, rows: list[dict],
               columns: set[str] | None = None) -> list[dict]:
    """Merge joined-vertex attributes onto each driving-vertex row
    (non-overriding). The join fetch projects to the plan's own field set
    (Round 9 task 4) — merging columns the plan never reads shipped the whole
    joined table's width for nothing. The join is deliberately NOT month- or
    advisor-filtered: the lookup below prefers a month-matched candidate but
    falls back to any candidate, and pre-filtering would change that."""
    for join in plan.get("joins", []):
        source = {r.get("__vertex_id"): r
                  for r in _fetch_rows(join["vertex"], columns=columns)}
        via = join["via"]
        primary = None
        try:
            from app.rules.compiler import load_schema_catalog

            primary = load_schema_catalog()["vertices"][join["vertex"]]["primary_id"]
        except Exception:  # noqa: BLE001 — index fallback below covers it
            pass
        if primary == via:
            index = {vid: attrs for vid, attrs in source.items()}
            lookup = lambda row: index.get(str(row.get(via)))  # noqa: E731
        else:
            index: dict[str, list[dict]] = {}
            for attrs in source.values():
                index.setdefault(str(attrs.get(via)), []).append(attrs)

            def lookup(row, _index=index, _via=via):
                candidates = _index.get(str(row.get(_via))) or []
                month = row.get("month_id")
                for candidate in candidates:
                    if month and candidate.get("month_id") == month:
                        return candidate
                return candidates[0] if candidates else None

        for row in rows:
            joined = lookup(row)
            if joined:
                for key, val in joined.items():
                    row.setdefault(key, val)
    return rows


def evaluate_plan(store, plan: dict, params: dict | None = None) -> dict:
    """Run one compiled plan. Returns
    {matched: [{key, value, attribute?}], matched_count, evaluated_rows, empty_reason?}.

    Round 8: ``store`` is UNUSED (kept for the rules_evaluate_plan dispatch
    signature) — every row read goes through the internal
    ``rule_evaluation_rows`` catalog query via the tiered client, so real mode
    evaluates against TigerGraph, never the local mock store."""
    params = dict(params or {})
    exclude_keys = {str(k) for k in params.pop("exclude_keys", []) or []}

    # Validate EVERY declared parameter BEFORE fetching the population, so a
    # missing parameter fails identically whether or not any rows exist for the
    # requested scope (a zero-row month must never mask a malformed query).
    missing = [name for name in plan.get("params") or []
               if params.get(name) in (None, "")]
    if missing:
        raise EvaluationError(
            f"required parameter :{missing[0]} was not supplied"
        )

    vertex = plan["vertex"]

    # Baseline guard — a present_prior_month rule cannot fire in the baseline month.
    month = params.get("month")
    if month and "present_prior_month" in set(plan.get("population_fields") or
                                             collect_fields(plan["filters"])):
        month_rows = _fetch_rows("phx_dm_pce_month", key=str(month),
                                 columns={"is_baseline"})
        if month_rows and _to_bool(month_rows[0].get("is_baseline")):
            return {"matched": [], "matched_count": 0, "evaluated_rows": 0,
                    "empty_reason": f"month {month} is the baseline month — no prior month "
                                    f"exists, so this rule returns an empty population"}

    # Automatic scoping rides the row-source query: month applies when the
    # vertex carries month_id, advisor when it carries advisor_sid AND the
    # plan's own filters do not reference it (from_/to_advisor_sid populations
    # scope via the :advisor_sid param inside the filter — no auto scoping).
    advisor = params.get("advisor_sid")
    auto_advisor = (advisor if advisor
                    and "advisor_sid" not in collect_fields(plan["filters"])
                    else None)
    columns = _plan_columns(plan)
    pushdown = _pushdown_filters(plan.get("filters"))
    rows = _fetch_rows(vertex, month=month, advisor_sid=auto_advisor,
                       columns=columns, pushdown=pushdown)

    rows = _join_rows(plan, rows, columns=columns)
    group_by = plan["group_by"]
    population = [
        row for row in rows
        if str(row.get(group_by)) not in exclude_keys and _row_matches(plan["filters"], row, params)
    ]

    matched: list[dict] = []
    compute_errors = 0
    compute = plan["compute"]
    trigger = plan["trigger"]
    attribute = plan.get("attribute")
    if plan.get("aggregate"):
        groups: dict[str, list[dict]] = {}
        for row in population:
            groups.setdefault(str(row.get(group_by)), []).append(row)
        for key, group in sorted(groups.items()):
            try:
                value = _aggregate(compute, group, params)
            except EvaluationError:
                # sparse data (e.g. a rate field absent on this row) — the group is
                # skipped and COUNTED, never silently absorbed into a wrong figure.
                compute_errors += 1
                continue
            if _trigger_fires(trigger, value):
                entry = {"key": key, "value": value}
                if attribute is not None:
                    entry[attribute["name"]] = _eval_expr(attribute["expr"], group[0], params, value)
                matched.append(entry)
    else:
        for row in population:
            try:
                value = _eval_expr(compute, row, params)
            except EvaluationError:
                compute_errors += 1
                continue
            if _trigger_fires(trigger, value):
                entry = {"key": str(row.get(group_by)), "value": value}
                if attribute is not None:
                    entry[attribute["name"]] = _eval_expr(attribute["expr"], row, params, value)
                matched.append(entry)

    result = {"matched": matched, "matched_count": len(matched),
              "evaluated_rows": len(population)}
    if compute_errors:
        result["compute_error_rows"] = compute_errors
    # Round 9 task 10d — an empty result says WHICH kind of empty it is:
    # "no rows matched the population filter" and "rows matched but none met
    # the trigger" demand different next actions (fix the filter/scope vs fix
    # the threshold) and were previously indistinguishable.
    # ``empty_kind`` marks these as TRUE-ZERO diagnostics (the evaluation ran
    # and found nothing), distinct from structural reasons like the baseline
    # guard above — consumers that surface "the count is qualified" notes
    # (account_lifecycle_counts) skip these; diagnostic surfaces (the rule
    # preview) show them.
    if not matched:
        if not population:
            pushed = ("".join(f" (after the pushed-down filter "
                              f"{f} = {v!r})" for f, v in pushdown.items())
                      if pushdown else "")
            result["empty_kind"] = "no_population"
            result["empty_reason"] = (
                f"no rows matched the population filter — {len(rows)} row(s) "
                f"were in scope for {vertex}{pushed}, none passed the "
                f"filters")
        else:
            groups_n = len({str(r.get(group_by)) for r in population}) \
                if plan.get("aggregate") else len(population)
            unit = "group(s)" if plan.get("aggregate") else "row(s)"
            result["empty_kind"] = "trigger_not_met"
            result["empty_reason"] = (
                f"{len(population)} row(s) matched the population filter "
                f"({groups_n} {unit} evaluated) but none met the trigger "
                f"({trigger['op']} {trigger['value']})")
    return result


def _aggregate(compute: dict, group: list[dict], params: dict) -> float:
    name, arg = compute["name"], compute["arg"]
    if name == "count":
        return float(len(group))
    if name == "count_distinct":
        return float(len({_eval_expr(arg, row, params) for row in group}))
    values = [_eval_expr(arg, row, params) for row in group]
    if not values:
        return 0.0
    if name == "sum":
        return float(sum(values))
    if name == "avg":
        return float(sum(values) / len(values))
    if name == "min":
        return float(min(values))
    return float(max(values))
