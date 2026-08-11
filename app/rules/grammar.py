"""B3.2 — the deliberately narrow rule expression grammar.

This module defines and validates the ONLY expression language rules may use.
Anything outside it fails to parse with a precise ``GrammarError`` — free SQL,
subqueries, joins and unknown functions are rejected, never guessed at.

    population : condition (AND|OR condition)* | parenthesised
    condition  : field OP literal | field IN (list) | field IS [NOT] NULL
    OP         : = != > >= < <= LIKE
    compute    : agg( expr ) | expr
    agg        : sum | count | count_distinct | avg | min | max
    expr       : field | number | expr (+|-|*|/) expr | round(expr) | abs(expr)
                 | min(expr,expr) | max(expr,expr)
    trigger    : value OP number
    attribute  : name = expr
    field      : a vertex attribute name from schema_catalog.json
    :param     : month | advisor_sid | from_month | to_month | threshold

Parsers return plain JSON-serialisable dict nodes so the compiler can embed
them directly in a query plan.
"""
from __future__ import annotations

import re
from typing import Any

# The grammar text, verbatim, for inlining into the extractor system prompt (B3.4).
GRAMMAR_TEXT = """population : condition (AND|OR condition)* | parenthesised
condition  : field OP literal | field IN (list) | field IS [NOT] NULL
OP         : = != > >= < <= LIKE
compute    : agg( expr ) | expr
agg        : sum | count | count_distinct | avg | min | max
expr       : field | number | expr (+|-|*|/) expr | round(expr) | abs(expr)
             | min(expr,expr) | max(expr,expr)
trigger    : value OP number
attribute  : name = expr
field      : a vertex attribute name from the provided field list
:param     : month | advisor_sid | from_month | to_month | threshold

No subqueries, no joins, no free SQL, no function calls outside the list above."""

AGGREGATES = ("sum", "count", "count_distinct", "avg", "min", "max")
SCALAR_FUNCTIONS = ("round", "abs", "min", "max")  # min/max are 2-arg scalar forms inside expr
COMPARISON_OPS = ("=", "!=", ">", ">=", "<", "<=", "LIKE")
ALLOWED_PARAMS = ("month", "advisor_sid", "from_month", "to_month", "threshold")

# Words that signal free SQL / subqueries — rejected with a targeted message.
_SQL_WORDS = {"select", "from", "join", "where", "group", "having", "union",
              "insert", "update", "delete", "exists", "case", "when", "then", "over"}
_KEYWORDS = {"and", "or", "in", "is", "not", "null", "like", "true", "false"}


class GrammarError(ValueError):
    """A rule expression fell outside the narrow grammar. The message is the
    readable parse error that travels with a NEEDS_INPUT rule."""


_TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<param>:[A-Za-z_][A-Za-z0-9_]*)
      | (?P<number>\d+\.\d+|\d+)
      | (?P<string>'[^']*'|"[^"]*")
      | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
      | (?P<op>>=|<=|!=|<>|=|>|<)
      | (?P<punct>[(),*+\-/%])
    )""",
    re.VERBOSE,
)


def _tokenize(text: str, what: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if match is None:
            remainder = text[pos:].lstrip()
            if not remainder:
                break
            raise GrammarError(
                f"{what}: unexpected character {remainder[0]!r} at position {pos} — "
                f"only the narrow rule grammar is allowed (no free SQL)"
            )
        pos = match.end()
        for kind in ("param", "number", "string", "ident", "op", "punct"):
            value = match.group(kind)
            if value is not None:
                tokens.append((kind, value))
                break
    # Free-SQL / subquery rejection, before any parsing: name the offending word.
    for kind, value in tokens:
        if kind == "ident" and value.lower() in _SQL_WORDS:
            raise GrammarError(
                f"{what}: free SQL / subqueries are not allowed in rule expressions "
                f"(found {value!r}); use only the narrow rule grammar"
            )
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], what: str) -> None:
        self.tokens = tokens
        self.pos = 0
        self.what = what

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> tuple[str, str]:
        token = self.peek()
        if token is None:
            raise GrammarError(f"{self.what}: unexpected end of expression")
        self.pos += 1
        return token

    def expect_punct(self, char: str) -> None:
        token = self.peek()
        if token is None or token != ("punct", char):
            found = token[1] if token else "end of expression"
            raise GrammarError(f"{self.what}: expected {char!r}, found {found!r}")
        self.pos += 1

    def at_end(self) -> bool:
        return self.pos >= len(self.tokens)

    def done_or_fail(self) -> None:
        if not self.at_end():
            raise GrammarError(
                f"{self.what}: unexpected trailing content starting at {self.peek()[1]!r}"
            )

    # ----- shared literal / expr parsing -----

    def parse_literal(self) -> dict:
        kind, value = self.next()
        if kind == "number":
            return {"type": "number", "value": float(value) if "." in value else int(value)}
        if kind == "string":
            return {"type": "string", "value": value[1:-1]}
        if kind == "param":
            name = value[1:]
            if name not in ALLOWED_PARAMS:
                raise GrammarError(
                    f"{self.what}: unknown parameter :{name} — allowed: "
                    + ", ".join(f":{p}" for p in ALLOWED_PARAMS)
                )
            return {"type": "param", "name": name}
        if kind == "ident" and value.lower() in ("true", "false"):
            return {"type": "bool", "value": value.lower() == "true"}
        if kind == "punct" and value == "-":
            follow = self.next()
            if follow[0] != "number":
                raise GrammarError(f"{self.what}: expected a number after unary '-'")
            number = follow[1]
            return {"type": "number", "value": -(float(number) if "." in number else int(number))}
        raise GrammarError(
            f"{self.what}: expected a literal (number, 'string', true/false or :param), "
            f"found {value!r}"
        )

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
            raise GrammarError(f"{self.what}: unexpected end of expression")
        kind, value = token
        if kind == "punct" and value == "(":
            self.next()
            node = self.parse_expr()
            self.expect_punct(")")
            return node
        if kind == "punct" and value == "-":
            self.next()
            return {"type": "binop", "op": "-",
                    "left": {"type": "number", "value": 0},
                    "right": self.parse_factor()}
        if kind == "number":
            self.next()
            return {"type": "number", "value": float(value) if "." in value else int(value)}
        if kind == "param":
            return self.parse_literal()
        if kind == "ident":
            self.next()
            lowered = value.lower()
            if self.peek() == ("punct", "("):
                if lowered not in SCALAR_FUNCTIONS:
                    raise GrammarError(
                        f"{self.what}: unknown function {value!r} — allowed functions: "
                        + ", ".join(sorted(set(SCALAR_FUNCTIONS) | set(AGGREGATES)))
                    )
                self.next()  # consume '('
                args = [self.parse_expr()]
                while self.peek() == ("punct", ","):
                    self.next()
                    args.append(self.parse_expr())
                self.expect_punct(")")
                expected = 1 if lowered in ("round", "abs") else 2
                if len(args) != expected:
                    raise GrammarError(
                        f"{self.what}: {lowered}() takes {expected} argument(s), got {len(args)}"
                    )
                return {"type": "func", "name": lowered, "args": args}
            if lowered == "value":
                return {"type": "valueref"}
            if lowered in ("true", "false"):
                return {"type": "bool", "value": lowered == "true"}
            return {"type": "field", "name": value}
        raise GrammarError(f"{self.what}: unexpected token {value!r} in expression")

    # ----- population -----

    def parse_population(self) -> dict:
        node = self.parse_or()
        self.done_or_fail()
        return node

    def parse_or(self) -> dict:
        items = [self.parse_and()]
        while self._keyword("or"):
            items.append(self.parse_and())
        return items[0] if len(items) == 1 else {"type": "or", "items": items}

    def parse_and(self) -> dict:
        items = [self.parse_condition_group()]
        while self._keyword("and"):
            items.append(self.parse_condition_group())
        return items[0] if len(items) == 1 else {"type": "and", "items": items}

    def _keyword(self, word: str) -> bool:
        token = self.peek()
        if token is not None and token[0] == "ident" and token[1].lower() == word:
            self.pos += 1
            return True
        return False

    def parse_condition_group(self) -> dict:
        if self.peek() == ("punct", "("):
            self.next()
            node = self.parse_or()
            self.expect_punct(")")
            return node
        return self.parse_condition()

    def parse_condition(self) -> dict:
        kind, value = self.next()
        if kind != "ident" or value.lower() in _KEYWORDS:
            raise GrammarError(
                f"{self.what}: expected a field name to start a condition, found {value!r}"
            )
        field = value
        token = self.peek()
        if token is None:
            raise GrammarError(f"{self.what}: condition on {field!r} is missing an operator")
        if token[0] == "ident" and token[1].lower() == "in":
            self.next()
            self.expect_punct("(")
            values = [self.parse_literal()]
            while self.peek() == ("punct", ","):
                self.next()
                values.append(self.parse_literal())
            self.expect_punct(")")
            return {"type": "in", "field": field, "values": values}
        if token[0] == "ident" and token[1].lower() == "is":
            self.next()
            negated = self._keyword("not")
            if not self._keyword("null"):
                raise GrammarError(f"{self.what}: expected NULL after IS [NOT] on {field!r}")
            return {"type": "isnull", "field": field, "negated": negated}
        if token[0] == "ident" and token[1].lower() == "like":
            self.next()
            literal = self.parse_literal()
            if literal["type"] != "string":
                raise GrammarError(f"{self.what}: LIKE on {field!r} requires a string literal")
            return {"type": "cond", "field": field, "op": "LIKE", "value": literal}
        if token[0] == "op":
            op = self.next()[1]
            if op == "<>":
                op = "!="
            return {"type": "cond", "field": field, "op": op, "value": self.parse_literal()}
        raise GrammarError(
            f"{self.what}: expected an operator (= != > >= < <= LIKE IN IS) after "
            f"{field!r}, found {token[1]!r}"
        )


def parse_population(text: str) -> dict:
    """Parse a population expression. Raises GrammarError outside the grammar."""
    what = "population"
    if not (text or "").strip():
        raise GrammarError("population: expression is empty — every rule must declare one")
    return _Parser(_tokenize(text, what), what).parse_population()


def parse_compute(text: str) -> dict:
    """Parse compute: agg(expr) | agg(*) for count | plain expr."""
    what = "compute"
    if not (text or "").strip():
        raise GrammarError("compute: expression is empty — every rule must declare one")
    tokens = _tokenize(text, what)
    parser = _Parser(tokens, what)
    token = parser.peek()
    if token is not None and token[0] == "ident" and token[1].lower() in AGGREGATES \
            and parser.pos + 1 < len(tokens) and tokens[parser.pos + 1] == ("punct", "("):
        agg = parser.next()[1].lower()
        parser.expect_punct("(")
        if parser.peek() == ("punct", "*"):
            if agg != "count":
                raise GrammarError(f"compute: {agg}(*) is not allowed — only count(*)")
            parser.next()
            arg: dict = {"type": "star"}
        else:
            arg = parser.parse_expr()
        parser.expect_punct(")")
        parser.done_or_fail()
        return {"type": "agg", "name": agg, "arg": arg}
    node = parser.parse_expr()
    parser.done_or_fail()
    return node


def parse_trigger(text: str) -> dict:
    """Parse trigger: value OP number."""
    what = "trigger"
    if not (text or "").strip():
        raise GrammarError("trigger: expression is empty — every rule must declare one")
    parser = _Parser(_tokenize(text, what), what)
    kind, word = parser.next()
    if kind != "ident" or word.lower() != "value":
        raise GrammarError(f"trigger: must start with 'value', found {word!r}")
    token = parser.next()
    if token[0] != "op" or token[1] not in ("=", "!=", ">", ">=", "<", "<="):
        raise GrammarError(f"trigger: expected an operator after 'value', found {token[1]!r}")
    op = "!=" if token[1] == "<>" else token[1]
    literal = parser.parse_literal()
    if literal["type"] != "number":
        raise GrammarError("trigger: the right-hand side must be a number")
    parser.done_or_fail()
    return {"type": "trigger", "op": op, "value": literal["value"]}


def parse_attribute(text: str | None) -> dict | None:
    """Parse attribute: name = expr. Blank/None → None (attribute is optional)."""
    what = "attribute"
    if not (text or "").strip():
        return None
    parser = _Parser(_tokenize(text, what), what)
    kind, name = parser.next()
    if kind != "ident" or name.lower() in _KEYWORDS:
        raise GrammarError(f"attribute: expected a name to assign, found {name!r}")
    token = parser.next()
    if token != ("op", "="):
        raise GrammarError(f"attribute: expected '=' after {name!r}, found {token[1]!r}")
    expr = parser.parse_expr()
    parser.done_or_fail()
    return {"type": "attribute", "name": name, "expr": expr}


def collect_fields(node: Any) -> set[str]:
    """Every field name referenced anywhere in a parsed node tree."""
    fields: set[str] = set()
    if isinstance(node, dict):
        if node.get("type") == "field":
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
    """Every :param referenced anywhere in a parsed node tree."""
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
