"use client";

/** Round C (docs/rules) task 4 — rule list management on Documents & Rules.
 *
 * CONTRACT (main-thread authored): Subagent A fully implements this component
 * IN PLACE (it owns this file); Subagent B mounts it on
 * frontend/app/documents/page.tsx and never edits it. Self-contained: fetches
 * its own data (drafts + latest version via lib/api getRulesDetailed,
 * extraction summary; mutations via lib/rulesApi deleteRules/setRuleActive).
 *
 * Required behaviour (spec task 4): multi-select checkboxes on unapproved
 * rules with select-all per status group; Delete Selected with a confirm
 * listing what goes (disabled on a mixed selection); Deactivate/Reactivate on
 * approved rules via ReasonModal (mandatory reason); filters by status,
 * provenance tag, scope and severity; extraction counts line
 * ("38 extracted · 22 compiled · 4 need a value · 12 need data we don't
 * have") with each bucket expandable to its per-rule reasons.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  type ExtractionSummary,
  type RuleDetail,
  type RuleVersion,
  getExtractionSummary,
  getRulesDetailed,
} from "@/lib/api";
import { RulesApiError, deleteRules, setRuleActive } from "@/lib/rulesApi";
import AppliesToChip from "@/components/rules/AppliesToChip";
import ProvenanceChip from "@/components/rules/ProvenanceChip";
import ReasonModal from "@/components/rules/ReasonModal";
import SeverityChip from "@/components/rules/SeverityChip";
import StatusChip from "@/components/rules/StatusChip";

/** Draft-pool status groups, in review order. Approved (version-bound) rules
 * form their own group below. */
const DRAFT_GROUPS: { status: string; label: string }[] = [
  { status: "COMPILED", label: "Compiled — Awaiting Approval" },
  { status: "DRAFT", label: "Draft — Not Yet Compiled" },
  { status: "NEEDS_INPUT", label: "Need a Value" },
  { status: "NEEDS_DATA", label: "Need Data We Don't Have" },
];

const SEVERITY_ORDER = ["CRITICAL", "HIGH", "MODERATE", "LOW", "INFO"];

function keyOf(rule: RuleDetail): string {
  return rule.rule_key || rule.rule_code;
}

/** The API serializes version_id on every rule; lib/api's RuleDetail (main
 * thread owned) does not declare it yet, so read it structurally. */
function versionId(rule: RuleDetail): string | null {
  const v = (rule as RuleDetail & { version_id?: string | null }).version_id;
  return v || null;
}

/** Approved = version-bound or PUBLISHED/SUPERSEDED — mirrors the store's
 * delete refusal, so the UI disables exactly what the API would refuse. */
function isApproved(rule: RuleDetail): boolean {
  return Boolean(
    versionId(rule) || rule.status === "PUBLISHED" || rule.status === "SUPERSEDED",
  );
}

interface Pools {
  drafts: RuleDetail[];
  published: RuleDetail[];
  version: RuleVersion | null;
}

function errText(e: unknown): string {
  if (e instanceof ApiError || e instanceof RulesApiError) return e.message;
  return String((e as Error)?.message || e);
}

export default function RuleListManager() {
  const [pools, setPools] = useState<Pools | null>(null);
  const [summary, setSummary] = useState<ExtractionSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reasonFor, setReasonFor] = useState<RuleDetail | null>(null);
  const [busy, setBusy] = useState(false);
  // filters — "" means All
  const [fStatus, setFStatus] = useState("");
  const [fProvenance, setFProvenance] = useState("");
  const [fScope, setFScope] = useState("");
  const [fSeverity, setFSeverity] = useState("");

  const refresh = useCallback(() => {
    getExtractionSummary()
      .then(setSummary)
      .catch(() => setSummary(null));
    Promise.all([
      getRulesDetailed("drafts"),
      // no published version yet is a normal state, not an error
      getRulesDetailed("latest").catch((e) => {
        if (e instanceof ApiError && e.status === 404) return { version: null, rules: [] };
        throw e;
      }),
    ])
      .then(([draftRes, latestRes]) => {
        setPools({
          drafts: draftRes.rules ?? [],
          published: (latestRes.rules ?? []).filter((r) => r.status !== "SUPERSEDED"),
          version: latestRes.version ?? null,
        });
        setLoadError(null);
        setSelected(new Set());
      })
      .catch((e) => {
        setPools(null);
        setLoadError(errText(e));
      });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const allRules = useMemo(
    () => (pools ? [...pools.drafts, ...pools.published] : []),
    [pools],
  );

  // filter option sets come from the data — never a hardcoded list drifting
  // from the backend's
  const provenanceOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const r of allRules) {
      if (r.provenance) seen.set(r.provenance, r.provenance_label || r.provenance);
    }
    return [...seen.entries()];
  }, [allRules]);
  const scopeOptions = useMemo(
    () => [...new Set(allRules.map((r) => r.applies_to || "ALL"))].sort(),
    [allRules],
  );
  const severityOptions = useMemo(() => {
    const present = new Set(
      allRules.map((r) => (r.severity || "").toUpperCase()).filter(Boolean),
    );
    return SEVERITY_ORDER.filter((s) => present.has(s));
  }, [allRules]);
  const statusOptions = useMemo(
    () => [...new Set(allRules.map((r) => r.status || "DRAFT"))].sort(),
    [allRules],
  );

  const matchesFilters = useCallback(
    (r: RuleDetail) =>
      (!fStatus || (r.status || "DRAFT") === fStatus) &&
      (!fProvenance || r.provenance === fProvenance) &&
      (!fScope || (r.applies_to || "ALL") === fScope) &&
      (!fSeverity || (r.severity || "").toUpperCase() === fSeverity),
    [fStatus, fProvenance, fScope, fSeverity],
  );

  const filteredDrafts = useMemo(
    () => (pools?.drafts ?? []).filter(matchesFilters),
    [pools, matchesFilters],
  );
  const filteredPublished = useMemo(
    () => (pools?.published ?? []).filter(matchesFilters),
    [pools, matchesFilters],
  );

  const selectedRules = useMemo(
    () => allRules.filter((r) => selected.has(keyOf(r))),
    [allRules, selected],
  );
  const selectionHasApproved = selectedRules.some(isApproved);

  const toggle = (rule: RuleDetail) => {
    const k = keyOf(rule);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  };

  const toggleGroup = (rules: RuleDetail[], on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const r of rules) {
        if (on) next.add(keyOf(r));
        else next.delete(keyOf(r));
      }
      return next;
    });
  };

  const runDelete = async () => {
    setBusy(true);
    setActionError(null);
    try {
      await deleteRules(selectedRules.map(keyOf));
      setConfirmOpen(false);
      refresh();
    } catch (e) {
      setActionError(errText(e));
    } finally {
      setBusy(false);
    }
  };

  const runSetActive = async (reason: string) => {
    if (!reasonFor) return;
    setBusy(true);
    setActionError(null);
    try {
      await setRuleActive(keyOf(reasonFor), reasonFor.active === false, reason);
      setReasonFor(null);
      refresh();
    } catch (e) {
      setActionError(errText(e));
    } finally {
      setBusy(false);
    }
  };

  if (loadError) {
    return (
      <div className="note" style={{ border: "1px solid var(--rule)", borderRadius: 5 }}>
        Rule management unavailable — {loadError}{" "}
        <button className="btn" onClick={refresh}>
          Retry
        </button>
      </div>
    );
  }
  if (!pools) return null; // first load in flight — render nothing, never fake content

  const ruleRow = (rule: RuleDetail, selectable: boolean) => {
    const k = keyOf(rule);
    const approved = isApproved(rule);
    const statusClass =
      rule.status === "NEEDS_INPUT" || rule.status === "NEEDS_DATA" ? "needs" : "draft";
    return (
      <div className={`rule ${statusClass}`} key={k}>
        <div className="rule-h">
          <div style={{ display: "flex", gap: 10, alignItems: "flex-start", minWidth: 0 }}>
            {selectable ? (
              <input
                type="checkbox"
                checked={selected.has(k)}
                onChange={() => toggle(rule)}
                aria-label={`Select ${rule.rule_code}`}
                style={{ marginTop: 2 }}
              />
            ) : null}
            <div style={{ minWidth: 0 }}>
              <div className="rule-t">{rule.rule_name || rule.rule_code}</div>
              <div style={{ fontSize: 11.5, color: "var(--slate)", marginTop: 2 }}>
                {rule.rule_code}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
            <SeverityChip severity={rule.severity} />
            <AppliesToChip appliesTo={rule.applies_to} appliesToKey={rule.applies_to_key} />
            <ProvenanceChip provenance={rule.provenance} provenanceLabel={rule.provenance_label} />
            <StatusChip status={rule.status} active={rule.active} activeReason={rule.active_reason} />
          </div>
        </div>
        {rule.statement || rule.plain_description ? (
          <div className="rule-d">{rule.statement || rule.plain_description}</div>
        ) : null}
        {rule.status === "NEEDS_INPUT" && (rule.missing || rule.unclear_notes) ? (
          <div className="eg">
            <b>Needs a value:</b> {rule.missing || rule.unclear_notes}
          </div>
        ) : null}
        {rule.status === "NEEDS_DATA" && rule.needs_data_reason ? (
          <div className="eg">
            <b>Needs data we don&rsquo;t have:</b> {rule.needs_data_reason}
          </div>
        ) : null}
        {rule.active === false && rule.active_reason ? (
          <div className="eg">
            <b>Deactivated:</b> {rule.active_reason}
            {rule.active_changed_by ? ` — ${rule.active_changed_by}` : ""}
            {rule.active_changed_at ? `, ${rule.active_changed_at}` : ""}
          </div>
        ) : null}
        {approved ? (
          <div className="rule-f">
            <span className="techsrc">
              {versionId(rule) ? `Version ${versionId(rule)}` : rule.status}
            </span>
            <button
              className="btn"
              disabled={busy}
              onClick={() => {
                setActionError(null);
                setReasonFor(rule);
              }}
            >
              {rule.active === false ? "Reactivate" : "Deactivate"}
            </button>
          </div>
        ) : null}
      </div>
    );
  };

  const group = (label: string, rules: RuleDetail[], selectable: boolean) => {
    if (!rules.length) return null;
    const allOn = rules.every((r) => selected.has(keyOf(r)));
    return (
      <div key={label} style={{ marginBottom: 14 }}>
        <div
          style={{
            display: "flex",
            gap: 10,
            alignItems: "center",
            padding: "6px 0",
            borderBottom: "1px solid var(--rule)",
            marginBottom: 8,
          }}
        >
          {selectable ? (
            <input
              type="checkbox"
              checked={allOn}
              onChange={(e) => toggleGroup(rules, e.target.checked)}
              aria-label={`Select all in ${label}`}
            />
          ) : null}
          <b style={{ fontSize: 12.5 }}>{label}</b>
          <span style={{ fontSize: 12, color: "var(--slate)" }}>{rules.length}</span>
        </div>
        {rules.map((r) => ruleRow(r, selectable))}
      </div>
    );
  };

  const bucket = (title: string, rows: { key: string; code: string; reason: string | null }[]) =>
    rows.length ? (
      <details className="tech" style={{ marginTop: 6 }}>
        <summary>
          {rows.length} {title}
        </summary>
        <div style={{ marginTop: 6 }}>
          {rows.map((row) => (
            <div key={row.key} className="eg" style={{ marginBottom: 6 }}>
              <b>{row.code}</b>
              {row.reason ? <> — {row.reason}</> : null}
            </div>
          ))}
        </div>
      </details>
    ) : null;

  const draftByStatus = (status: string) =>
    (pools.drafts ?? []).filter((r) => (r.status || "DRAFT") === status);

  return (
    <div>
      {/* extraction counts — from the API, never hardcoded; each bucket expands */}
      {summary ? (
        <div className="note" style={{ border: "1px solid var(--rule)", borderRadius: 5, marginBottom: 14 }}>
          <b>
            {summary.extracted} extracted · {summary.compiled} compiled ·{" "}
            {summary.needs_input.length} need a value · {summary.needs_data.length} need data we
            don&rsquo;t have
          </b>
          {bucket(
            "extracted — in the draft pool awaiting review",
            (pools.drafts ?? []).map((r) => ({
              key: keyOf(r),
              code: r.rule_code,
              reason: r.statement || r.plain_description || null,
            })),
          )}
          {bucket(
            "compiled — plan generated, awaiting approval",
            draftByStatus("COMPILED").map((r) => ({
              key: keyOf(r),
              code: r.rule_code,
              reason: r.explanation || r.statement || null,
            })),
          )}
          {bucket(
            "need a value the document does not state",
            summary.needs_input.map((g) => ({
              key: g.rule_key,
              code: g.rule_code || g.rule_key,
              reason: g.reason || "no reason recorded",
            })),
          )}
          {bucket(
            "need data we don't have — each names its missing field",
            summary.needs_data.map((g) => ({
              key: g.rule_key,
              code: g.rule_code || g.rule_key,
              reason: g.reason || "no reason recorded",
            })),
          )}
        </div>
      ) : null}

      {/* filters + actions */}
      <div className="ctl" style={{ marginBottom: 12 }}>
        <select value={fStatus} onChange={(e) => setFStatus(e.target.value)} aria-label="Filter by status">
          <option value="">All Statuses</option>
          {statusOptions.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <select value={fProvenance} onChange={(e) => setFProvenance(e.target.value)} aria-label="Filter by provenance">
          <option value="">All Provenance</option>
          {provenanceOptions.map(([code, label]) => (
            <option key={code} value={code}>
              {label}
            </option>
          ))}
        </select>
        <select value={fScope} onChange={(e) => setFScope(e.target.value)} aria-label="Filter by scope">
          <option value="">All Scopes</option>
          {scopeOptions.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select value={fSeverity} onChange={(e) => setFSeverity(e.target.value)} aria-label="Filter by severity">
          <option value="">All Severities</option>
          {severityOptions.map((s) => (
            <option key={s} value={s}>
              {s.charAt(0) + s.slice(1).toLowerCase()}
            </option>
          ))}
        </select>
        <span style={{ flex: 1 }} />
        <button
          className="btn"
          disabled={busy || selected.size === 0 || selectionHasApproved}
          title={
            selectionHasApproved
              ? "Approved rules can never be deleted — only superseded or deactivated. Clear them from the selection."
              : undefined
          }
          onClick={() => {
            setActionError(null);
            setConfirmOpen(true);
          }}
        >
          Delete Selected{selected.size ? ` (${selected.size})` : ""}
        </button>
      </div>
      {selectionHasApproved ? (
        <div className="note" style={{ border: "1px solid var(--rule)", borderRadius: 5, marginBottom: 12 }}>
          The selection includes approved rules — approved rules can never be deleted, only
          superseded or deactivated, so Delete is disabled.
        </div>
      ) : null}
      {actionError && !confirmOpen && !reasonFor ? (
        <div className="note" style={{ border: "1px solid var(--neg-br)", borderRadius: 5, marginBottom: 12 }}>
          {actionError}
        </div>
      ) : null}

      {/* draft pool — selectable, grouped by status with select-all */}
      {DRAFT_GROUPS.map((g) =>
        group(g.label, draftByStatus(g.status).filter(matchesFilters), true),
      )}
      {/* approved rules — selectable so a mixed selection is honestly disabled,
          with deactivate/reactivate instead of delete */}
      {group(
        pools.version?.version_no != null
          ? `Published — Version ${pools.version.version_no}`
          : "Published",
        filteredPublished,
        true,
      )}
      {!filteredDrafts.length && !filteredPublished.length ? (
        <div className="note" style={{ border: "1px solid var(--rule)", borderRadius: 5 }}>
          No rules match the current filters.
        </div>
      ) : null}

      {/* delete confirm — lists exactly what will go */}
      <div className={`scrim${confirmOpen ? " on" : ""}`} onClick={() => setConfirmOpen(false)}></div>
      <div
        className={`modal narrow${confirmOpen ? " on" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label="Delete selected rules"
      >
        <div className="m-head">Delete {selectedRules.length} Rule{selectedRules.length === 1 ? "" : "s"}?</div>
        <div className="m-body">
          <p style={{ margin: "0 0 10px", fontSize: 13, color: "var(--slate)" }}>
            These unapproved rules will be permanently removed from the draft pool:
          </p>
          {selectedRules.map((r) => (
            <div key={keyOf(r)} className="eg" style={{ marginBottom: 6 }}>
              <b>{r.rule_code}</b> — {r.rule_name || "unnamed"} ({(r.status || "DRAFT").replace(/_/g, " ")})
            </div>
          ))}
          {actionError ? (
            <div className="note" style={{ border: "1px solid var(--neg-br)", borderRadius: 5, marginTop: 8 }}>
              {actionError}
            </div>
          ) : null}
        </div>
        <div className="m-foot">
          <button className="btn" onClick={() => setConfirmOpen(false)}>
            Cancel
          </button>
          <button className="btn primary" disabled={busy || selectionHasApproved} onClick={runDelete}>
            {busy ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>

      {/* deactivate / reactivate — mandatory reason (the API 400s without one) */}
      <ReasonModal
        open={reasonFor !== null}
        title={
          reasonFor?.active === false
            ? `Reactivate ${reasonFor?.rule_code ?? ""}`
            : `Deactivate ${reasonFor?.rule_code ?? ""}`
        }
        prompt={
          <>
            {reasonFor?.active === false
              ? "Reactivating puts this rule back into new insight runs."
              : "An inactive rule stops feeding new insight runs but remains queryable; prior insights citing it stay valid."}{" "}
            This mints a new rule-set version with who, when and why recorded.
            {actionError ? <> — {actionError}</> : null}
          </>
        }
        confirmLabel={reasonFor?.active === false ? "Reactivate" : "Deactivate"}
        busy={busy}
        onConfirm={runSetActive}
        onCancel={() => setReasonFor(null)}
      />
    </div>
  );
}
