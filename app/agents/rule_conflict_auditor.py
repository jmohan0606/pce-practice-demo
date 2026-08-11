"""B3.5 — the Rule Conflict Auditor.

Runs before publishing, over {new drafts} x {live PUBLISHED rules}. A conflict
exists when ANY of:
  1. same rule_code
  2. same grain AND population field sets overlap AND triggers can both fire
     on one row
  3. same driver_tag and overlapping population

Detection is DETERMINISTIC (never left to a model). The proposed resolution and
reasoning are enriched by the rule_conflict_auditor LLM role when its output is
parseable; otherwise the deterministic proposal stands (logged, honest). The
precedence order — later effective date wins, explicit supersession language
wins over date, a plan document outranks an FAQ — is stated to the model as a
PROPOSAL INPUT only.

THE AUDITOR NEVER APPLIES A RESOLUTION. It proposes; a human approves.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from app.llm.roles import build_role_llm
from app.rules.grammar import GrammarError, collect_fields, parse_population, parse_trigger
from app.shared.logging import get_logger

_log = get_logger("app.agents.rule_conflict_auditor")

_PRECEDENCE_NOTE = (
    "Precedence order (proposal input ONLY, never automatic): a later effective "
    "date wins; explicit supersession language wins over date; a plan document "
    "outranks an FAQ."
)


def _population_fields(rule: dict) -> set[str]:
    text = rule.get("population", rule.get("population_expr", "")) or ""
    try:
        return collect_fields(parse_population(text))
    except GrammarError:
        # unparseable population — conservative: no field overlap claim.
        return set()


def _trigger_interval(rule: dict) -> tuple[float, float, bool, bool] | None:
    """(low, high, low_inclusive, high_inclusive) satisfied-value interval, or
    None when the trigger is unparseable / '!=' (treated as always-overlapping)."""
    text = rule.get("trigger", rule.get("trigger_expr", "")) or ""
    try:
        trigger = parse_trigger(text)
    except GrammarError:
        return None
    op, threshold = trigger["op"], float(trigger["value"])
    inf = float("inf")
    return {
        "=": (threshold, threshold, True, True),
        ">": (threshold, inf, False, True),
        ">=": (threshold, inf, True, True),
        "<": (-inf, threshold, True, False),
        "<=": (-inf, threshold, True, True),
        "!=": None,
    }[op]


def triggers_can_both_fire(rule_a: dict, rule_b: dict) -> bool:
    """Conservative interval intersection of the two triggers' satisfied-value
    ranges (unparseable / '!=' counts as overlapping)."""
    interval_a = _trigger_interval(rule_a)
    interval_b = _trigger_interval(rule_b)
    if interval_a is None or interval_b is None:
        return True
    low = max(interval_a[0], interval_b[0])
    high = min(interval_a[1], interval_b[1])
    if low < high:
        return True
    if low == high:
        low_ok = (interval_a[2] if interval_a[0] == low else True) and \
                 (interval_b[2] if interval_b[0] == low else True)
        high_ok = (interval_a[3] if interval_a[1] == high else True) and \
                  (interval_b[3] if interval_b[1] == high else True)
        return low_ok and high_ok
    return False


def _first_citation(rule: dict) -> dict:
    citations = rule.get("citations") or []
    return citations[0] if citations else {"note": f"{rule.get('provenance', '?')} rule — no document citation"}


def detect_conflicts(new_rules: list[dict], published_rules: list[dict]) -> list[dict]:
    """Deterministic {new drafts} x {live PUBLISHED} conflict detection with a
    deterministic default proposal per conflict."""
    conflicts = []
    for new_rule in new_rules:
        new_fields = _population_fields(new_rule)
        for existing in published_rules:
            conflict_type = None
            reasoning = None
            proposal = "COEXIST"
            if new_rule.get("rule_code") and new_rule.get("rule_code") == existing.get("rule_code"):
                conflict_type = "SAME_RULE_CODE"
                proposal = "SUPERSEDE"
                reasoning = (
                    f"Draft {new_rule['rule_code']!r} reuses the rule_code of a live "
                    f"PUBLISHED rule. Default proposal: the newer document-derived "
                    f"provision supersedes the existing rule in the next version. "
                    f"{_PRECEDENCE_NOTE}"
                )
            else:
                existing_fields = _population_fields(existing)
                overlap = new_fields & existing_fields
                if (new_rule.get("grain") == existing.get("grain") and overlap
                        and triggers_can_both_fire(new_rule, existing)):
                    conflict_type = "OVERLAPPING_POPULATION_TRIGGER"
                    proposal = "MERGE"
                    reasoning = (
                        f"Both rules run at grain {new_rule.get('grain')!r}, their "
                        f"populations share field(s) {sorted(overlap)} and their triggers "
                        f"can both fire on one row — the same row could be attributed "
                        f"twice. Default proposal: merge or scope the populations apart. "
                        f"{_PRECEDENCE_NOTE}"
                    )
                elif (new_rule.get("driver_tag") and
                      new_rule.get("driver_tag") == existing.get("driver_tag") and overlap):
                    conflict_type = "SAME_DRIVER_TAG"
                    proposal = "COEXIST"
                    reasoning = (
                        f"Both rules carry driver_tag {new_rule['driver_tag']!r} with "
                        f"overlapping population field(s) {sorted(overlap)} — findings "
                        f"would attribute the same driver twice. Default proposal: "
                        f"coexist with distinct scopes, reviewer to confirm. "
                        f"{_PRECEDENCE_NOTE}"
                    )
            if conflict_type is None:
                continue
            conflicts.append({
                "conflict_type": conflict_type,
                "new_rule": new_rule.get("rule_key") or new_rule.get("rule_code"),
                "existing_rule": existing.get("rule_key") or existing.get("rule_code"),
                "proposed_resolution": proposal,
                "reasoning": reasoning,
                "new_citation": _first_citation(new_rule),
                "existing_citation": _first_citation(existing),
            })
    return conflicts


def _llm_enrich(conflicts: list[dict], new_rules: list[dict], published_rules: list[dict],
                generate: Callable[[str, dict], str]) -> list[dict]:
    """Ask the auditor LLM to refine proposed_resolution/reasoning. Unparseable
    output leaves the deterministic proposals untouched (logged) — the auditor
    never guesses and NEVER applies anything."""
    by_pair = {(c["new_rule"], c["existing_rule"]): c for c in conflicts}
    prompt = (
        "Review these detected rule conflicts and refine each proposed_resolution "
        "(SUPERSEDE|COEXIST|MERGE) and reasoning. " + _PRECEDENCE_NOTE +
        " You PROPOSE only; a human approves. Return a JSON array of objects with "
        "keys new_rule, existing_rule, proposed_resolution, reasoning. No prose, "
        "no markdown fences.\n\nConflicts:\n" + json.dumps(conflicts, default=str) +
        "\n\nNew draft rules:\n" + json.dumps(new_rules, default=str) +
        "\n\nExisting published rules:\n" + json.dumps(published_rules, default=str)
    )
    try:
        raw = generate(prompt, {"system_prompt":
                                "You are the Rule Conflict Auditor for a compensation rules "
                                "engine. You propose conflict resolutions; you never apply "
                                "them. Return a JSON array only."})
    except Exception as exc:  # noqa: BLE001
        _log.warning("conflict auditor LLM call failed — deterministic proposals stand: %s", exc)
        return conflicts
    text = (raw or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        refined = json.loads(text)
        assert isinstance(refined, list)
    except Exception:  # noqa: BLE001 — mock LLM output lands here; honest fallback
        _log.info("conflict auditor LLM output not a JSON array — deterministic proposals stand")
        return conflicts
    for item in refined:
        if not isinstance(item, dict):
            continue
        key = (item.get("new_rule"), item.get("existing_rule"))
        target = by_pair.get(key)
        if target is None:
            continue  # the model may not invent conflicts — detection is deterministic
        if item.get("proposed_resolution") in ("SUPERSEDE", "COEXIST", "MERGE"):
            target["proposed_resolution"] = item["proposed_resolution"]
        if item.get("reasoning"):
            target["reasoning"] = str(item["reasoning"])
        target["llm_reviewed"] = True
    return conflicts


def audit_conflicts(new_rules: list[dict], published_rules: list[dict] | None = None,
                    llm: Callable[[str, dict], str] | None = None,
                    use_llm: bool = True) -> list[dict]:
    """Detect + propose. `published_rules=None` pulls the latest PUBLISHED
    version from the rule store. Returns conflict dicts (B3.5 shape) — and
    changes NOTHING: no rule status is touched here."""
    if published_rules is None:
        from app.rules.store import get_rule_store

        store = get_rule_store()
        latest = store.latest_version("PUBLISHED")
        published_rules = store.version_rules(latest["version_id"]) if latest else []
    conflicts = detect_conflicts(new_rules, published_rules)
    if not conflicts or not use_llm:
        return conflicts
    generate = llm
    if generate is None:
        try:
            role = build_role_llm("rule_conflict_auditor")
            if role is not None:
                generate = role.generate
            else:
                from app.llm.client import get_llm_client

                generate = get_llm_client().generate
        except Exception as exc:  # noqa: BLE001 — enrichment is optional; detection is not
            _log.warning("no LLM available for conflict-audit enrichment — "
                         "deterministic proposals stand: %s", exc)
            return conflicts
    return _llm_enrich(conflicts, new_rules, published_rules, generate)
