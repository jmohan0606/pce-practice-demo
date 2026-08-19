"use client";

/** Round 3 Task 12a / batch 2 §E — the Exceptions tab on Documents & Rules.
 *
 * Every rule of the SERVED version is listed with two INDEPENDENT toggles —
 * driver_enabled and exception_enabled — plus the per-rule materiality
 * configuration (denominator, floor + unit, sensitivity, product scope with
 * its provenance line). Edits go through PATCH
 * /api/rules/{rule_key}/exception-config, which mints and publishes a new
 * version in one call; the list is refetched after every save because
 * rule_keys change per mint.
 *
 * Honest-null: where the document states nothing the value is null and the UI
 * renders an em dash — never an invented number.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  type RuleDetail,
  type RuleVersion,
  getRulesDetailed,
} from "@/lib/api";
import {
  type ExceptionConfigChanges,
  RulesApiError,
  setExceptionConfig,
  setTriggerThreshold,
} from "@/lib/rulesApi";
import EmptyState from "@/components/EmptyState";
import { Pager, usePager } from "@/components/Pager";
import ProvenanceChip from "@/components/rules/ProvenanceChip";
import SeverityChip from "@/components/rules/SeverityChip";

/** The eight exception fields are serialized on every rule; lib/api's
 * RuleDetail (main-thread owned) does not declare them, so read structurally. */
type ExceptionRule = RuleDetail & {
  rule_key?: string;
  driver_enabled?: boolean;
  exception_enabled?: boolean;
  exception_denominator?: string | null;
  exception_floor?: number | null;
  exception_floor_unit?: string | null;
  exception_sensitivity?: number | null;
  product_scope?: string | null;
  product_scope_source?: string | null;
};

const DASH = "—";

function keyOf(rule: ExceptionRule): string {
  return rule.rule_key || rule.rule_code;
}

function errText(e: unknown): string {
  if (e instanceof ApiError || e instanceof RulesApiError) return e.message;
  return String((e as Error)?.message || e);
}

/** A stated value or an em dash — never an invented one. */
function stated(v: string | number | null | undefined, suffix = ""): string {
  if (v === null || v === undefined || v === "" || v === "NOT STATED") return DASH;
  return `${v}${suffix}`;
}

/** Draft state for the per-rule materiality edit form (strings while typing). */
interface EditDraft {
  exception_denominator: string;
  exception_floor: string;
  exception_floor_unit: string;
  exception_sensitivity: string;
  product_scope: string;
  product_scope_source: string;
  reason: string;
}

function draftFrom(rule: ExceptionRule): EditDraft {
  return {
    exception_denominator: rule.exception_denominator ?? "",
    exception_floor: rule.exception_floor != null ? String(rule.exception_floor) : "",
    exception_floor_unit: rule.exception_floor_unit ?? "",
    exception_sensitivity:
      rule.exception_sensitivity != null ? String(rule.exception_sensitivity) : "",
    product_scope: rule.product_scope ?? "",
    product_scope_source:
      rule.product_scope_source && rule.product_scope_source !== "NOT STATED"
        ? rule.product_scope_source
        : "",
    reason: "",
  };
}

export default function ExceptionsTab() {
  const [rules, setRules] = useState<ExceptionRule[] | null>(null);
  const [version, setVersion] = useState<RuleVersion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // rule_code of the rule whose materiality form is open (stable across mints)
  const [editingCode, setEditingCode] = useState<string | null>(null);
  const [draft, setDraft] = useState<EditDraft | null>(null);
  // Round 8 task 4 — the trigger-threshold editor (absolute firm-level rules)
  const [thresholdCode, setThresholdCode] = useState<string | null>(null);
  const [thresholdValue, setThresholdValue] = useState("");
  const [thresholdReason, setThresholdReason] = useState("");

  const reload = useCallback(() => {
    getRulesDetailed("latest")
      .then((res) => {
        setRules(
          ((res.rules ?? []) as ExceptionRule[]).filter((r) => r.status !== "SUPERSEDED"),
        );
        setVersion(res.version ?? null);
        setError(null);
      })
      .catch((e) => {
        setRules(null);
        setError(
          e instanceof ApiError && e.status === 404
            ? "No published rule set yet — publish a version to configure exceptions."
            : errText(e),
        );
      });
  }, []);

  useEffect(reload, [reload]);

  const sorted = useMemo(
    () => (rules ? [...rules].sort((a, b) => a.rule_code.localeCompare(b.rule_code)) : []),
    [rules],
  );
  const pager = usePager(sorted);

  const save = async (rule: ExceptionRule, changes: ExceptionConfigChanges, doneMsg: string) => {
    setBusyKey(keyOf(rule));
    setSaveError(null);
    try {
      const res = await setExceptionConfig(keyOf(rule), changes);
      setNotice(
        res.version
          ? `${rule.rule_code}: ${doneMsg} — v${res.version.version_no} minted and published.`
          : res.note || `${rule.rule_code}: ${doneMsg}.`,
      );
      setEditingCode(null);
      setDraft(null);
      reload(); // rule_keys change per mint — always refetch
    } catch (e) {
      setSaveError(`${rule.rule_code}: ${errText(e)}`);
    } finally {
      setBusyKey(null);
    }
  };

  // Round 8 task 4 — a PRACTICE-applies rule with a numeric trigger is an
  // ABSOLUTE firm-level threshold (no cohort, no rate); its threshold is
  // edited here and the edit mints a version like any rule change. Nothing is
  // keyed on a rule_code — any qualifying rule gets the editor.
  const triggerValue = (rule: ExceptionRule): number | null => {
    const t = (rule.plan as { trigger?: { value?: unknown } } | null)?.trigger?.value;
    return typeof t === "number" ? t : null;
  };

  const saveThreshold = async (rule: ExceptionRule) => {
    const value = Number(thresholdValue);
    if (thresholdValue.trim() === "" || Number.isNaN(value)) {
      setSaveError(`${rule.rule_code}: the threshold must be a number.`);
      return;
    }
    setBusyKey(keyOf(rule));
    setSaveError(null);
    try {
      const res = await setTriggerThreshold(keyOf(rule), value, thresholdReason.trim());
      setNotice(
        res.version
          ? `${rule.rule_code}: trigger threshold changed — v${res.version.version_no} minted and published.`
          : res.note || `${rule.rule_code}: trigger threshold changed.`,
      );
      setThresholdCode(null);
      setThresholdValue("");
      setThresholdReason("");
      reload();
    } catch (e) {
      setSaveError(`${rule.rule_code}: ${errText(e)}`);
    } finally {
      setBusyKey(null);
    }
  };

  const saveDraft = (rule: ExceptionRule) => {
    if (!draft) return;
    const num = (s: string): number | null => (s.trim() === "" ? null : Number(s));
    const floor = num(draft.exception_floor);
    const sensitivity = num(draft.exception_sensitivity);
    if ((floor !== null && Number.isNaN(floor)) || (sensitivity !== null && Number.isNaN(sensitivity))) {
      setSaveError(`${rule.rule_code}: floor and sensitivity must be numbers (or blank for null).`);
      return;
    }
    save(
      rule,
      {
        exception_denominator: draft.exception_denominator.trim() || null,
        exception_floor: floor,
        exception_floor_unit: draft.exception_floor_unit || null,
        exception_sensitivity: sensitivity,
        product_scope: draft.product_scope.trim() || null,
        product_scope_source: draft.product_scope_source.trim() || null,
        reason: draft.reason.trim(),
      },
      "materiality configuration updated",
    );
  };

  if (error) {
    return <EmptyState title="Exceptions unavailable" message={error} />;
  }
  if (!rules) return null; // first load in flight

  return (
    <div>
      {/* the model in one paragraph — why there are TWO toggles */}
      <div className="note" style={{ border: "1px solid var(--rule)", borderRadius: 5, marginBottom: 14 }}>
        <b>Driver and exception are independent.</b> A rule can be a valuable driver and a poor
        exception — New Billing explains a revenue movement but accounts beginning to bill is
        normal business, not a problem. The <b>driver</b> toggle controls whether the rule feeds
        revenue attribution; the <b>exception</b> toggle controls whether it flags advisors. The
        materiality settings govern the exception side only: rate = affected / denominator, the
        floor suppresses tiny populations, sensitivity sets how far above the cohort an advisor
        must sit, and product scope narrows both the denominator and the comparison cohort. Where
        the document states nothing the value is {DASH} — nothing is invented.
      </div>
      {version ? (
        <div className="meta" style={{ marginBottom: 10 }}>
          Configuring v{version.version_no} (the served version) — every save mints and publishes a
          new version with the change recorded.
        </div>
      ) : null}
      {notice ? (
        <div className="note" style={{ border: "1px solid var(--rule)", borderRadius: 5, marginBottom: 12 }}>
          {notice}
        </div>
      ) : null}
      {saveError ? (
        <div className="note" style={{ border: "1px solid var(--neg-br, var(--rule))", borderRadius: 5, marginBottom: 12 }}>
          {saveError}
        </div>
      ) : null}

      {pager.rows.map((rule) => {
        const k = keyOf(rule);
        const busy = busyKey === k;
        const editing = editingCode === rule.rule_code && draft;
        const scopeSource =
          rule.product_scope_source && rule.product_scope_source !== "NOT STATED"
            ? rule.product_scope_source
            : null;
        return (
          <div className="rule" key={k}>
            <div className="rule-h">
              <div style={{ minWidth: 0 }}>
                <div className="rule-t">{rule.rule_name || rule.rule_code}</div>
                <div style={{ fontSize: 11.5, color: "var(--slate)", marginTop: 2 }}>{rule.rule_code}</div>
              </div>
              <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
                <SeverityChip severity={rule.severity} />
                <ProvenanceChip provenance={rule.provenance} provenanceLabel={rule.provenance_label} />
              </div>
            </div>
            {rule.statement || rule.plain_description ? (
              <div className="rule-d">{rule.statement || rule.plain_description}</div>
            ) : null}

            {/* the two INDEPENDENT toggles — on/off switches keep checkbox styling (batch 2 B5 exception) */}
            <div style={{ display: "flex", gap: 18, alignItems: "center", flexWrap: "wrap", margin: "8px 0 2px" }}>
              <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12.5, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={rule.driver_enabled !== false}
                  disabled={busy}
                  onChange={(e) =>
                    save(rule, { driver_enabled: e.target.checked, reason: "driver toggle" },
                      `driver ${e.target.checked ? "enabled" : "disabled"}`)
                  }
                />
                <b>Driver</b>
                <span style={{ color: "var(--slate)" }}>feeds revenue attribution</span>
              </label>
              <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12.5, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={rule.exception_enabled === true}
                  disabled={busy}
                  onChange={(e) =>
                    save(rule, { exception_enabled: e.target.checked, reason: "exception toggle" },
                      `exception ${e.target.checked ? "enabled" : "disabled"}`)
                  }
                />
                <b>Exception</b>
                <span style={{ color: "var(--slate)" }}>flags advisors</span>
              </label>
              {busy ? <span style={{ fontSize: 12, color: "var(--slate)" }}>Saving…</span> : null}
            </div>

            {editing ? (
              <div className="eg" style={{ marginTop: 8 }}>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
                  <label style={{ fontSize: 12 }}>
                    Denominator
                    <input
                      className="filter"
                      style={{ width: "100%", marginTop: 3 }}
                      placeholder="e.g. managed accounts (blank = not stated)"
                      value={draft.exception_denominator}
                      onChange={(e) => setDraft({ ...draft, exception_denominator: e.target.value })}
                    />
                  </label>
                  <label style={{ fontSize: 12 }}>
                    Floor
                    <input
                      className="filter"
                      style={{ width: "100%", marginTop: 3 }}
                      inputMode="decimal"
                      placeholder="blank = not stated"
                      value={draft.exception_floor}
                      onChange={(e) => setDraft({ ...draft, exception_floor: e.target.value })}
                    />
                  </label>
                  <label style={{ fontSize: 12 }}>
                    Floor unit
                    <select
                      style={{ width: "100%", marginTop: 3 }}
                      value={draft.exception_floor_unit}
                      onChange={(e) => setDraft({ ...draft, exception_floor_unit: e.target.value })}
                    >
                      <option value="">{DASH} not stated</option>
                      <option value="accounts">accounts</option>
                      <option value="dollars">dollars</option>
                    </select>
                  </label>
                  <label style={{ fontSize: 12 }}>
                    Sensitivity
                    <input
                      className="filter"
                      style={{ width: "100%", marginTop: 3 }}
                      inputMode="decimal"
                      placeholder="blank = not stated"
                      value={draft.exception_sensitivity}
                      onChange={(e) => setDraft({ ...draft, exception_sensitivity: e.target.value })}
                    />
                  </label>
                  <label style={{ fontSize: 12 }}>
                    Product scope
                    <input
                      className="filter"
                      style={{ width: "100%", marginTop: 3 }}
                      placeholder="blank = not stated"
                      value={draft.product_scope}
                      onChange={(e) => setDraft({ ...draft, product_scope: e.target.value })}
                    />
                  </label>
                  <label style={{ fontSize: 12 }}>
                    Scope source (citation)
                    <input
                      className="filter"
                      style={{ width: "100%", marginTop: 3 }}
                      placeholder="where the document states the scope"
                      value={draft.product_scope_source}
                      onChange={(e) => setDraft({ ...draft, product_scope_source: e.target.value })}
                    />
                  </label>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10, flexWrap: "wrap" }}>
                  <input
                    className="filter"
                    style={{ flex: 1, minWidth: 200 }}
                    placeholder="Reason for the change (recorded on the minted version)"
                    value={draft.reason}
                    onChange={(e) => setDraft({ ...draft, reason: e.target.value })}
                  />
                  <button className="btn primary" disabled={busy} onClick={() => saveDraft(rule)}>
                    {busy ? "Saving…" : "Save — mints a version"}
                  </button>
                  <button className="btn" disabled={busy} onClick={() => { setEditingCode(null); setDraft(null); }}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <>
                {rule.applies_to === "PRACTICE" && triggerValue(rule) !== null ? (
                  <div className="eg" style={{ marginTop: 6 }}>
                    <b>Trigger threshold:</b>{" "}
                    {triggerValue(rule)!.toLocaleString("en-US")}{" "}
                    <span style={{ color: "var(--slate)" }}>
                      — an absolute firm-level threshold (no peer cohort at firm
                      level, so no rate, floor or sensitivity applies). A starting
                      value, not a constant.
                    </span>{" "}
                    {thresholdCode === rule.rule_code ? (
                      <span style={{ display: "inline-flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginTop: 4 }}>
                        <input
                          className="filter"
                          style={{ width: 140 }}
                          inputMode="decimal"
                          aria-label="New trigger threshold"
                          value={thresholdValue}
                          onChange={(e) => setThresholdValue(e.target.value)}
                        />
                        <input
                          className="filter"
                          style={{ width: 260 }}
                          placeholder="Reason (recorded on the minted version)"
                          value={thresholdReason}
                          onChange={(e) => setThresholdReason(e.target.value)}
                        />
                        <button className="btn primary" disabled={busy} onClick={() => saveThreshold(rule)}>
                          {busy ? "Saving…" : "Save — mints a version"}
                        </button>
                        <button className="btn" disabled={busy} onClick={() => setThresholdCode(null)}>
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        className="btn"
                        style={{ padding: "2px 8px" }}
                        disabled={busy}
                        onClick={() => {
                          setSaveError(null);
                          setThresholdCode(rule.rule_code);
                          setThresholdValue(String(triggerValue(rule)));
                          setThresholdReason("");
                        }}
                      >
                        Edit threshold
                      </button>
                    )}
                  </div>
                ) : null}
                <div className="eg" style={{ marginTop: 6 }}>
                  <b>Materiality:</b> denominator {stated(rule.exception_denominator)} · floor{" "}
                  {stated(rule.exception_floor, rule.exception_floor != null && rule.exception_floor_unit ? ` ${rule.exception_floor_unit}` : "")}{" "}
                  · sensitivity {stated(rule.exception_sensitivity)} · product scope{" "}
                  {stated(rule.product_scope)}
                </div>
                <div className="rule-f" style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                  <span style={{ fontSize: 11.5, color: "var(--slate)" }}>
                    {scopeSource ? (
                      <>Scope source: {scopeSource}</>
                    ) : (
                      <>Scope source: {DASH} (the document states nothing)</>
                    )}
                  </span>
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() => {
                      setSaveError(null);
                      setEditingCode(rule.rule_code);
                      setDraft(draftFrom(rule));
                    }}
                  >
                    Edit materiality
                  </button>
                </div>
              </>
            )}
          </div>
        );
      })}
      {!sorted.length ? (
        <EmptyState
          title="No rules in the served version"
          message="Publish a rule set version to configure its exceptions."
        />
      ) : null}
      <Pager {...pager} noun="rules" />
    </div>
  );
}
