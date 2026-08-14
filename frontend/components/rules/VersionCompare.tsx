"use client";

import { useEffect, useState } from "react";
import { ApiError, type RuleDetail, getRulesDetailed } from "@/lib/api";
import Chip from "@/components/Chip";

/** Round C (docs/rules) 7.3 — version comparison, computed CLIENT-SIDE from
 * two GET /api/rules?version= responses. Rules are matched by rule_code
 * (rule_key changes on every mint — it is identity churn, not a change).
 * Only MEANINGFUL fields are compared; bookkeeping that changes on every
 * version (rule_key, version_id, created_at, carried_from, compile stats…)
 * is deliberately ignored so "what changed between v3 and v4" is answerable
 * at a glance rather than drowned in churn. */

/** Fields whose difference between two versions is a real change. */
export const COMPARED_FIELDS = [
  "rule_name",
  "statement",
  "worked_example",
  "severity",
  "severity_reason",
  "applies_to",
  "applies_to_key",
  "active",
  "active_reason",
  "driver_label",
  "driver_definition",
  "plan", // deep compare
  "provenance",
  "scopes",
  "evaluation_order",
  "exclude_matched_of",
] as const;
export type ComparedField = (typeof COMPARED_FIELDS)[number];

/** Bookkeeping fields that differ between versions by construction — listed
 * here as documentation of what the diff IGNORES. */
export const IGNORED_FIELDS = [
  "rule_key",
  "version_id",
  "status",
  "created_at",
  "carried_from",
  "supersedes_rule_key",
  "published_from_draft",
  "published_as",
  "approved",
  "approved_by",
  "approved_at",
  "compiled_at",
  "compiled_evaluated_rows",
  "compiled_matched_count",
  "compile_error",
  "explanation",
  "provenance_label", // derived from provenance
  "plain_description", // mirror of statement
  "driver_tag", // mirror of driver_label
] as const;

export interface FieldChange {
  field: ComparedField;
  from: unknown;
  to: unknown;
}
export interface ModifiedRule {
  rule_code: string;
  rule_name: string;
  changes: FieldChange[];
}
export interface VersionDiff {
  added: RuleDetail[];
  removed: RuleDetail[];
  modified: ModifiedRule[];
  unchanged: string[]; // rule_codes
}

/** Stable stringify (sorted object keys) so plan deep-compare is order-safe. */
function canonical(value: unknown): string {
  if (value === undefined || value === null) return "null";
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : 1));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

/** Normalise a field so absent-vs-default never reads as a change. */
function fieldValue(rule: RuleDetail, field: ComparedField): unknown {
  const raw = (rule as unknown as Record<string, unknown>)[field];
  switch (field) {
    case "active":
      return raw === undefined || raw === null ? true : raw;
    case "applies_to":
      return raw || "ALL";
    case "statement":
      return raw ?? rule.plain_description ?? "";
    case "scopes":
    case "exclude_matched_of":
      return [...((raw as string[] | undefined) ?? [])].sort();
    case "severity_reason":
    case "active_reason":
    case "applies_to_key":
    case "worked_example":
    case "driver_definition":
      return raw ?? null;
    default:
      return raw ?? null;
  }
}

/** Diff two versions' rule lists (older first, newer second). Pure — exported
 * so it can be exercised without a browser. */
export function diffVersions(older: RuleDetail[], newer: RuleDetail[]): VersionDiff {
  const byCodeOld = new Map(older.map((r) => [r.rule_code, r]));
  const byCodeNew = new Map(newer.map((r) => [r.rule_code, r]));
  const added = newer.filter((r) => !byCodeOld.has(r.rule_code));
  const removed = older.filter((r) => !byCodeNew.has(r.rule_code));
  const modified: ModifiedRule[] = [];
  const unchanged: string[] = [];
  for (const oldRule of older) {
    const newRule = byCodeNew.get(oldRule.rule_code);
    if (!newRule) continue;
    const changes: FieldChange[] = [];
    for (const field of COMPARED_FIELDS) {
      const from = fieldValue(oldRule, field);
      const to = fieldValue(newRule, field);
      if (canonical(from) !== canonical(to)) changes.push({ field, from, to });
    }
    if (changes.length) {
      modified.push({ rule_code: oldRule.rule_code, rule_name: newRule.rule_name, changes });
    } else {
      unchanged.push(oldRule.rule_code);
    }
  }
  return { added, removed, modified, unchanged };
}

function short(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return value.length > 90 ? `${value.slice(0, 87)}…` : value;
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  return "(see plan JSON)";
}

function ChangeRow({ change }: { change: FieldChange }) {
  if (change.field === "plan") {
    return (
      <div className="eg" style={{ marginBottom: 6 }}>
        <b>plan</b> — the compiled query changed
        <details className="tech" style={{ marginTop: 4 }}>
          <summary>Before / after plan JSON</summary>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 6 }}>
            {[change.from, change.to].map((plan, i) => (
              <pre key={i} style={{ fontSize: 10.5, overflowX: "auto", margin: 0 }}>
                {plan ? JSON.stringify(plan, null, 2) : "no plan"}
              </pre>
            ))}
          </div>
        </details>
      </div>
    );
  }
  return (
    <div className="eg" style={{ marginBottom: 6 }}>
      <b>{change.field}</b>:{" "}
      <span style={{ textDecoration: "line-through", color: "var(--slate)" }}>{short(change.from)}</span>{" "}
      → <b>{short(change.to)}</b>
    </div>
  );
}

/** The comparison card body. Fetches both versions and renders added /
 * removed / modified with the specific fields that differ. */
export default function VersionCompare({
  olderVersionId,
  olderLabel,
  newerVersionId,
  newerLabel,
}: {
  olderVersionId: string;
  olderLabel: string;
  newerVersionId: string;
  newerLabel: string;
}) {
  const [diff, setDiff] = useState<VersionDiff | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDiff(null);
    setError(null);
    Promise.all([getRulesDetailed(olderVersionId), getRulesDetailed(newerVersionId)])
      .then(([a, b]) => {
        if (!cancelled) setDiff(diffVersions(a.rules, b.rules));
      })
      .catch((e) => {
        if (!cancelled)
          setError(
            e instanceof ApiError
              ? `Could not load both versions: ${e.message}`
              : String((e as Error)?.message || e),
          );
      });
    return () => {
      cancelled = true;
    };
  }, [olderVersionId, newerVersionId]);

  if (error) return <div className="note">{error}</div>;
  if (!diff) return <div className="meta">Comparing {olderLabel} → {newerLabel}…</div>;

  const nothing = !diff.added.length && !diff.removed.length && !diff.modified.length;
  return (
    <div>
      <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
        <b style={{ fontSize: 13 }}>
          {olderLabel} → {newerLabel}
        </b>
        <Chip variant={diff.added.length ? "pos" : "tag"}>{diff.added.length} added</Chip>
        <Chip variant={diff.removed.length ? "neg" : "tag"}>{diff.removed.length} removed</Chip>
        <Chip variant={diff.modified.length ? "derived" : "tag"}>{diff.modified.length} modified</Chip>
        <Chip variant="tag">{diff.unchanged.length} unchanged</Chip>
      </div>
      {nothing ? (
        <div className="meta">No meaningful differences — every rule carries the same fields in both versions.</div>
      ) : null}
      {diff.added.map((r) => (
        <div key={`a-${r.rule_code}`} className="rule">
          <div className="rule-h">
            <div className="rule-t">
              {r.rule_name} <span className="pfx">({r.rule_code})</span>
            </div>
            <Chip variant="pos">Added</Chip>
          </div>
          <div className="rule-d">{r.statement || r.plain_description}</div>
        </div>
      ))}
      {diff.removed.map((r) => (
        <div key={`r-${r.rule_code}`} className="rule conflict">
          <div className="rule-h">
            <div className="rule-t">
              {r.rule_name} <span className="pfx">({r.rule_code})</span>
            </div>
            <Chip variant="neg">Removed</Chip>
          </div>
          <div className="rule-d">{r.statement || r.plain_description}</div>
        </div>
      ))}
      {diff.modified.map((m) => (
        <div key={`m-${m.rule_code}`} className="rule">
          <div className="rule-h">
            <div className="rule-t">
              {m.rule_name} <span className="pfx">({m.rule_code})</span>
            </div>
            <Chip variant="derived">
              {m.changes.length} field{m.changes.length === 1 ? "" : "s"} changed
            </Chip>
          </div>
          <div style={{ marginTop: 6 }}>
            {m.changes.map((c) => (
              <ChangeRow key={c.field} change={c} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
