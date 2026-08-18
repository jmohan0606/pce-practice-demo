"use client";

import { useEffect, useState } from "react";
import {
  ApiError,
  type RuleDetail,
  approveRule,
  compileRule,
  editRule,
  publishRules,
} from "@/lib/api";

/** Round C (docs/rules) 7.2 — the rule edit dialog for the Rule Versions
 * screen. Editable: name, statement (offers a recompile — a changed statement
 * invalidates the plan), worked example, driver label, driver definition,
 * severity, applies_to scope. Everything except the driver LABEL mints a new
 * version through the immutable edit → (compile) → approve → publish flow;
 * the label is a read-time display registry (PATCH /driver-label) and applies
 * to historical findings immediately with no version. Active state is NOT
 * here — deactivate/reactivate has its own ReasonModal on the rule row. */

const SEVERITIES = ["CRITICAL", "HIGH", "MODERATE", "LOW", "INFO"] as const;
const APPLIES_TO = ["ALL", "PRACTICE", "ADVISOR", "PRODUCT", "COMPENSATION_ENGINE"] as const;

// PATCH /api/rules/{key}/driver-label has no client in lib/api.ts or
// lib/rulesApi.ts (main-thread owned — gap reported); same helper pattern.
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8002";

async function patchDriverLabel(ruleKey: string, driverLabel: string): Promise<void> {
  const response = await fetch(
    `${API_BASE}/api/rules/${encodeURIComponent(ruleKey)}/driver-label`,
    {
      method: "PATCH",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ driver_label: driverLabel }),
    },
  );
  if (!response.ok) {
    let detail = `driver-label PATCH failed (${response.status})`;
    try {
      const parsed = await response.json();
      if (parsed?.detail) detail = String(parsed.detail);
    } catch {
      /* keep status message */
    }
    throw new ApiError(response.status, detail);
  }
}

interface FormState {
  rule_name: string;
  statement: string;
  worked_example: string;
  driver_label: string;
  driver_definition: string;
  severity: string;
  applies_to: string;
  applies_to_key: string;
}

function initialForm(rule: RuleDetail): FormState {
  return {
    rule_name: rule.rule_name ?? "",
    statement: rule.statement ?? rule.plain_description ?? "",
    worked_example: rule.worked_example ?? "",
    driver_label: rule.driver_label ?? "",
    driver_definition: rule.driver_definition ?? "",
    severity: (rule.severity || "").toUpperCase(),
    applies_to: rule.applies_to || "ALL",
    applies_to_key: rule.applies_to_key ?? "",
  };
}

export default function RuleEditDialog({
  rule,
  open,
  onClose,
  onDone,
}: {
  rule: RuleDetail;
  open: boolean;
  onClose: () => void;
  /** Called after a successful save with a human notice; refresh=true when a
   * new version was published (the caller reloads the version list). */
  onDone: (notice: string, refresh: boolean) => void;
}) {
  const [form, setForm] = useState<FormState>(() => initialForm(rule));
  const [recompile, setRecompile] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setForm(initialForm(rule));
      setRecompile(true);
      setBusy(null);
      setError(null);
    }
  }, [open, rule]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  const set = (field: keyof FormState, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  const statementChanged = form.statement !== (rule.statement ?? rule.plain_description ?? "");
  const labelChanged = form.driver_label !== (rule.driver_label ?? "");

  /** Version-minting changes (driver label excluded — read-time registry). */
  const mintingChanges = (): Record<string, unknown> => {
    const changes: Record<string, unknown> = {};
    if (form.rule_name !== (rule.rule_name ?? "")) changes.rule_name = form.rule_name;
    if (statementChanged) changes.statement = form.statement;
    if (form.worked_example !== (rule.worked_example ?? ""))
      changes.worked_example = form.worked_example;
    if (form.driver_definition !== (rule.driver_definition ?? ""))
      changes.driver_definition = form.driver_definition;
    if (form.severity && form.severity !== (rule.severity || "").toUpperCase())
      changes.severity = form.severity;
    if (form.applies_to !== (rule.applies_to || "ALL")) changes.applies_to = form.applies_to;
    const key = form.applies_to === "ALL" ? "" : form.applies_to_key.trim();
    if ((key || null) !== (rule.applies_to_key ?? null)) changes.applies_to_key = key || null;
    return changes;
  };

  const save = async () => {
    setError(null);
    const ruleKey = rule.rule_key ?? rule.rule_code;
    const changes = mintingChanges();
    const notices: string[] = [];
    let publishedVersion = false;
    try {
      if (labelChanged) {
        setBusy("renaming the driver label (read-time registry)…");
        await patchDriverLabel(ruleKey, form.driver_label);
        notices.push(
          `Driver label is now “${form.driver_label}” — labels resolve at read time, so ` +
            "historical findings already show it; no version was minted for the rename.",
        );
      }
      if (Object.keys(changes).length) {
        setBusy("creating the new draft (rules are immutable)…");
        const { rule: draft } = await editRule(ruleKey, changes);
        const draftKey = draft.rule_key ?? draft.rule_code;
        if (statementChanged && !recompile) {
          notices.push(
            `Draft ${draft.rule_code} created with the new statement but NOT recompiled — ` +
              "it stays in the Documents & Rules draft pool until the Rule Compiler runs; " +
              "no version was published.",
          );
        } else {
          let toApprove = draft;
          if ((draft.status || "").toUpperCase() !== "COMPILED") {
            // A changed statement invalidates the plan — the Rule Compiler
            // agent compiles the new draft before it can be approved.
            setBusy("recompiling the new draft (Rule Compiler agent)…");
            const { rule: compiled } = await compileRule(draftKey);
            if ((compiled.status || "").toUpperCase() !== "COMPILED") {
              onDone(
                notices.concat(
                  `The edited draft did not compile (${compiled.status}): ` +
                    `${compiled.needs_data_reason || compiled.compile_error || "see the draft pool"}. ` +
                    "It stays in Documents & Rules until resolved — no version was published.",
                ).join(" "),
                false,
              );
              return;
            }
            toApprove = compiled;
          }
          setBusy("approving the new draft…");
          await approveRule(toApprove.rule_key ?? toApprove.rule_code);
          setBusy("publishing the next version…");
          const { version } = await publishRules("operator", `edit of ${rule.rule_code}`);
          publishedVersion = true;
          notices.push(
            `v${version.version_no} published with the edited ${rule.rule_code} — ` +
              "the version you edited is unchanged (rules are immutable).",
          );
        }
      }
      if (!notices.length) {
        setError("Nothing changed — edit a field first.");
        setBusy(null);
        return;
      }
      onDone(notices.join(" "), publishedVersion);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `Save failed: ${e.message}`
          : `Save failed: ${String((e as Error)?.message || e)}`,
      );
    } finally {
      setBusy(null);
    }
  };

  const fieldStyle = {
    width: "100%",
    font: "12px/1.5 ui-monospace,Menlo,Consolas,monospace",
    border: "1px solid var(--rule)",
    borderRadius: 4,
    padding: "6px 8px",
    marginTop: 3,
  } as const;
  const labelStyle = { fontSize: 12, color: "var(--slate)" } as const;

  return (
    <>
      <div className={`scrim${open ? " on" : ""}`} onClick={busy ? undefined : onClose}></div>
      <div
        className={`modal${open ? " on" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={`Edit ${rule.rule_code}`}
      >
        <div className="m-head">
          Edit {rule.rule_name} ({rule.rule_code}) → new version
        </div>
        <div className="m-body" style={{ display: "grid", gap: 10, maxHeight: "62vh", overflowY: "auto" }}>
          <p style={{ margin: 0, fontSize: 12.5, color: "var(--slate)" }}>
            Rules are immutable — saving creates a new draft, approves it and publishes the NEXT
            rule set version. The version you opened is never mutated. The driver label alone is a
            read-time display registry: renaming it changes every screen immediately without a
            version.
          </p>
          <label style={labelStyle}>
            Rule name
            <input type="text" style={fieldStyle} value={form.rule_name} onChange={(e) => set("rule_name", e.target.value)} />
          </label>
          <label style={labelStyle}>
            Statement (plain English — the Rule Compiler compiles this)
            <textarea rows={4} style={fieldStyle} value={form.statement} onChange={(e) => set("statement", e.target.value)} />
          </label>
          {statementChanged ? (
            <label style={{ ...labelStyle, display: "flex", gap: 6, alignItems: "flex-start" }}>
              <input
                type="checkbox"
                checked={recompile}
                onChange={(e) => setRecompile(e.target.checked)}
                style={{ marginTop: 2 }}
              />
              <span>
                <b>Recompile the plan</b> — the statement changed, which invalidates the compiled
                query; the Rule Compiler agent generates a new plan before approval. Unchecked, the
                draft is created but stays uncompiled in the draft pool and no version publishes.
              </span>
            </label>
          ) : null}
          <label style={labelStyle}>
            Worked example
            <textarea rows={2} style={fieldStyle} value={form.worked_example} onChange={(e) => set("worked_example", e.target.value)} />
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <label style={labelStyle}>
              Driver label (display registry — no version)
              <input type="text" style={fieldStyle} value={form.driver_label} onChange={(e) => set("driver_label", e.target.value)} />
            </label>
            <label style={labelStyle}>
              Severity
              <select style={fieldStyle} value={form.severity} onChange={(e) => set("severity", e.target.value)}>
                {!form.severity ? <option value="">(not set)</option> : null}
                {SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {s.charAt(0) + s.slice(1).toLowerCase()}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label style={labelStyle}>
            Driver definition
            <textarea rows={2} style={fieldStyle} value={form.driver_definition} onChange={(e) => set("driver_definition", e.target.value)} />
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <label style={labelStyle}>
              Applies to (which entities SHOULD this rule apply to)
              <select style={fieldStyle} value={form.applies_to} onChange={(e) => set("applies_to", e.target.value)}>
                {APPLIES_TO.map((s) => (
                  <option key={s} value={s}>
                    {s === "ALL" ? "All (default)" : s.charAt(0) + s.slice(1).toLowerCase()}
                  </option>
                ))}
              </select>
            </label>
            {form.applies_to === "ADVISOR" || form.applies_to === "PRODUCT" ? (
              <label style={labelStyle}>
                {form.applies_to === "ADVISOR" ? "Advisor SID" : "Product group id"}
                <input
                  type="text"
                  style={fieldStyle}
                  placeholder={form.applies_to === "ADVISOR" ? "e.g. V000002" : "e.g. G01"}
                  value={form.applies_to_key}
                  onChange={(e) => set("applies_to_key", e.target.value)}
                />
              </label>
            ) : null}
          </div>
          {error ? (
            <div className="note" style={{ border: "1px solid var(--rule)", borderRadius: 5 }}>
              {error}
            </div>
          ) : null}
        </div>
        <div className="m-foot">
          <button className="btn" onClick={onClose} disabled={busy !== null}>
            Cancel
          </button>
          <button className="btn primary" onClick={save} disabled={busy !== null}>
            {busy ?? "Save as new version"}
          </button>
        </div>
      </div>
    </>
  );
}
