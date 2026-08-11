"""B3.6 — rule + rule-set-version storage and versioning.

Persistence model (documented decision):
- The store keeps the FULL rule dicts (including fields the graph schema does
  not carry: driver_tag, citations, unclear_notes, evaluation_order,
  worked-example provenance extras) in-process, and MIRRORS the
  schema-catalogued subset to the graph as ``phx_dm_pce_rule`` /
  ``phx_dm_pce_rule_set_version`` vertices through the tiered graph client on
  every write. In mock mode that lands in the local FoundationGraphStore
  (process-local, like every runtime mock write); against a live TigerGraph the
  same upsert path persists the vertices for real. This is the "internal store
  inside app/rules/ backed by the graph client" option the track allows.

Invariants:
- Rules are IMMUTABLE — an edit creates a new rule row; nothing is ever deleted.
- publish() mints a new phx_dm_pce_rule_set_version with version_no incremented;
  the previous PUBLISHED version becomes SUPERSEDED. Approved drafts are COPIED
  into the new version (new rule_key); carried-forward rules are copied too.
- Both old and new versions stay queryable forever.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from app.rules.compiler import compile_status
from app.shared.logging import get_logger

_log = get_logger("app.rules.store")

RULE_VERTEX = "phx_dm_pce_rule"
VERSION_VERTEX = "phx_dm_pce_rule_set_version"

# graph-schema attributes of each vertex (identity column first).
_RULE_GRAPH_ATTRS = (
    "rule_key", "version_id", "rule_code", "rule_name", "plain_description",
    "worked_example", "population_expr", "compute_expr", "trigger_expr",
    "attribute_expr", "grain", "provenance", "confidence", "status",
)
_VERSION_GRAPH_ATTRS = (
    "version_id", "version_no", "status", "rule_count", "approved_by", "approved_at", "notes",
)

RULE_STATUSES = ("DRAFT", "PUBLISHED", "SUPERSEDED", "NEEDS_INPUT", "REJECTED")


class RuleStoreError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _entry(target: str, id_column: str, attrs: tuple[str, ...]) -> dict:
    return {
        "kind": "vertex",
        "target": target,
        "id_column": id_column,
        "file": f"runtime:{target}",
        "columns": {name: name for name in attrs if name != id_column},
    }


class RuleStore:
    """In-process source of truth for rules + versions, mirrored to the graph."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.rules: dict[str, dict] = {}      # rule_key -> full rule dict
        self.versions: dict[str, dict] = {}   # version_id -> version dict
        self._draft_seq = 0

    # ----- graph mirroring -----

    def _graph(self):
        from app.graph.client import get_graph_client

        return get_graph_client()

    def _mirror_rule(self, rule: dict) -> None:
        row = {name: ("" if rule.get(name) is None else rule.get(name))
               for name in _RULE_GRAPH_ATTRS}
        try:
            self._graph().upsert(_entry(RULE_VERTEX, "rule_key", _RULE_GRAPH_ATTRS), [row])
        except Exception as exc:  # noqa: BLE001 — the store stays authoritative; log loudly
            _log.error("graph mirror of rule %s failed: %s", rule.get("rule_key"), exc)

    def _mirror_version(self, version: dict) -> None:
        row = {name: ("" if version.get(name) is None else version.get(name))
               for name in _VERSION_GRAPH_ATTRS}
        try:
            self._graph().upsert(_entry(VERSION_VERTEX, "version_id", _VERSION_GRAPH_ATTRS), [row])
        except Exception as exc:  # noqa: BLE001
            _log.error("graph mirror of version %s failed: %s", version.get("version_id"), exc)

    # ----- versions -----

    def create_version(self, version_no: int, status: str, notes: str = "",
                       approved_by: str = "") -> dict:
        with self._lock:
            version_id = f"RSV_v{version_no}"
            if version_id in self.versions:
                raise RuleStoreError(f"version {version_id} already exists")
            version = {
                "version_id": version_id, "version_no": version_no, "status": status,
                "rule_count": 0, "approved_by": approved_by,
                "approved_at": _now() if status == "PUBLISHED" else "",
                "notes": notes,
            }
            self.versions[version_id] = version
            self._mirror_version(version)
            return version

    def latest_version(self, status: str | None = "PUBLISHED") -> dict | None:
        with self._lock:
            candidates = [v for v in self.versions.values()
                          if status is None or v["status"] == status]
            if not candidates:
                return None
            return max(candidates, key=lambda v: v["version_no"])

    def version(self, version_id: str) -> dict | None:
        if version_id == "latest":
            return self.latest_version()
        return self.versions.get(version_id)

    def list_versions(self) -> list[dict]:
        with self._lock:
            return sorted(self.versions.values(), key=lambda v: v["version_no"])

    def _set_version_status(self, version_id: str, status: str) -> None:
        version = self.versions[version_id]
        version["status"] = status
        self._mirror_version(version)

    # ----- rules -----

    def add_rule(self, rule: dict, version_id: str | None = None) -> dict:
        """Insert one immutable rule row. version_id=None keeps it in the draft
        pool (version_id == "")."""
        with self._lock:
            rule = dict(rule)
            rule.setdefault("status", "DRAFT")
            if rule["status"] not in RULE_STATUSES:
                raise RuleStoreError(f"unknown rule status {rule['status']!r}")
            rule["version_id"] = version_id or ""
            if not rule.get("rule_key"):
                if version_id:
                    rule["rule_key"] = f"R_{rule['rule_code']}_{version_id}"
                else:
                    self._draft_seq += 1
                    rule["rule_key"] = f"DRAFT_{rule['rule_code']}_{self._draft_seq:04d}"
            if rule["rule_key"] in self.rules:
                raise RuleStoreError(f"rule_key {rule['rule_key']} already exists — rules are immutable")
            # canonical expression storage under *_expr; keep B3.1 aliases readable
            for short, long in (("population", "population_expr"), ("compute", "compute_expr"),
                                ("trigger", "trigger_expr"), ("attribute", "attribute_expr")):
                if long not in rule and short in rule:
                    rule[long] = rule.pop(short)
                rule.pop(short, None)
            rule.setdefault("created_at", _now())
            self.rules[rule["rule_key"]] = rule
            if version_id:
                version = self.versions[version_id]
                version["rule_count"] = sum(
                    1 for r in self.rules.values() if r["version_id"] == version_id
                )
                self._mirror_version(version)
            self._mirror_rule(rule)
            return rule

    def get(self, rule_key: str) -> dict | None:
        return self.rules.get(rule_key)

    def version_rules(self, version_id: str) -> list[dict]:
        with self._lock:
            rules = [r for r in self.rules.values() if r["version_id"] == version_id]
            return sorted(rules, key=lambda r: (r.get("evaluation_order") or 999, r["rule_code"]))

    def drafts(self, statuses: tuple[str, ...] = ("DRAFT", "NEEDS_INPUT")) -> list[dict]:
        with self._lock:
            return sorted(
                (r for r in self.rules.values() if not r["version_id"] and r["status"] in statuses),
                key=lambda r: r["rule_key"],
            )

    def _update_rule_fields(self, rule_key: str, **fields) -> dict:
        """Status/flag transitions only — expression content never mutates."""
        with self._lock:
            rule = self.rules[rule_key]
            rule.update(fields)
            self._mirror_rule(rule)
            return rule

    # ----- lifecycle operations -----

    def approve(self, rule_key: str, approved_by: str = "") -> dict:
        """Mark a draft approved for the next publish. An uncompilable rule
        cannot be approved (B3.3); a NEEDS_INPUT rule cannot be approved either."""
        with self._lock:
            rule = self.rules.get(rule_key)
            if rule is None:
                raise RuleStoreError(f"unknown rule_key {rule_key!r}")
            if rule["version_id"]:
                raise RuleStoreError(f"{rule_key} already belongs to version {rule['version_id']}")
            if rule["status"] == "NEEDS_INPUT":
                raise RuleStoreError(
                    f"{rule_key} is NEEDS_INPUT ({rule.get('unclear_notes') or 'missing input'}) "
                    f"— resolve it before approving"
                )
            status = compile_status(rule)
            if not status["compiled"]:
                raise RuleStoreError(
                    f"{rule_key} does not compile and cannot be approved: {status['compile_error']}"
                )
            return self._update_rule_fields(rule_key, approved=True,
                                            approved_by=approved_by, approved_at=_now())

    def edit(self, rule_key: str, changes: dict) -> dict:
        """Rules are immutable — an edit creates a NEW draft rule row carrying
        the changes; the original row is untouched."""
        with self._lock:
            original = self.rules.get(rule_key)
            if original is None:
                raise RuleStoreError(f"unknown rule_key {rule_key!r}")
            editable = {
                "rule_code", "rule_name", "plain_description", "worked_example",
                "population", "compute", "trigger", "attribute",
                "population_expr", "compute_expr", "trigger_expr", "attribute_expr",
                "grain", "driver_tag", "confidence", "unclear_notes", "evaluation_order",
            }
            rejected = sorted(set(changes) - editable)
            if rejected:
                raise RuleStoreError(f"fields not editable: {', '.join(rejected)}")
            # normalise B3.1 short aliases to the stored *_expr keys so an edit
            # like {"trigger": "value > 12"} replaces the inherited trigger_expr.
            changes = dict(changes)
            for short in ("population", "compute", "trigger", "attribute"):
                if short in changes:
                    changes[f"{short}_expr"] = changes.pop(short)
            draft = {k: v for k, v in original.items()
                     if k not in ("rule_key", "version_id", "status", "approved",
                                  "approved_by", "approved_at", "created_at", "published_as")}
            draft.update(changes)
            draft["status"] = "DRAFT"
            draft["supersedes_rule_key"] = rule_key
            return self.add_rule(draft, version_id=None)

    def publish(self, approved_by: str = "", notes: str = "") -> dict:
        """Mint the next version: carried-forward copies of the latest PUBLISHED
        version's rules (minus ones superseded by an approved edit) plus copies
        of every approved draft. Previous version becomes SUPERSEDED."""
        with self._lock:
            approved_drafts = [r for r in self.drafts(statuses=("DRAFT",)) if r.get("approved")]
            if not approved_drafts:
                raise RuleStoreError("nothing to publish — no approved drafts")
            previous = self.latest_version("PUBLISHED")
            highest = self.latest_version(None)
            next_no = (highest["version_no"] + 1) if highest else 0
            version = self.create_version(next_no, "PUBLISHED",
                                          notes=notes, approved_by=approved_by)

            superseded_keys = {d.get("supersedes_rule_key") for d in approved_drafts}
            replaced_codes = {d["rule_code"] for d in approved_drafts}
            copied = 0
            if previous is not None:
                for rule in self.version_rules(previous["version_id"]):
                    if rule["rule_key"] in superseded_keys or rule["rule_code"] in replaced_codes:
                        continue
                    carry = {k: v for k, v in rule.items()
                             if k not in ("rule_key", "version_id", "created_at")}
                    carry["carried_from"] = rule["rule_key"]
                    carry["status"] = "PUBLISHED"
                    self.add_rule(carry, version_id=version["version_id"])
                    copied += 1
            for draft in approved_drafts:
                published = {k: v for k, v in draft.items()
                             if k not in ("rule_key", "version_id", "created_at", "approved")}
                published["status"] = "PUBLISHED"
                published["published_from_draft"] = draft["rule_key"]
                new_rule = self.add_rule(published, version_id=version["version_id"])
                # the draft row stays (nothing deleted) — marked as absorbed.
                self._update_rule_fields(draft["rule_key"], status="SUPERSEDED",
                                         published_as=new_rule["rule_key"])
                copied += 1
            if previous is not None:
                self._set_version_status(previous["version_id"], "SUPERSEDED")
            _log.info("published %s with %d rules (previous: %s)",
                      version["version_id"], copied,
                      previous["version_id"] if previous else "none")
            return version


_store: RuleStore | None = None
_store_lock = threading.Lock()


def get_rule_store() -> RuleStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = RuleStore()
        return _store


def reset_rule_store() -> None:
    global _store
    with _store_lock:
        _store = None
