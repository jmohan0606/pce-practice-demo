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

import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  type ExtractionSummary,
  type RuleDetail,
  type RuleVersion,
  getDocuments,
  getExtractionSummary,
  getRulesDetailed,
} from "@/lib/api";
import {
  type CompileAttempt,
  RulesApiError,
  deleteRules,
  recompileRule,
  setRuleActive,
} from "@/lib/rulesApi";
import { Pager, usePager } from "@/components/Pager";
import { useGlossary } from "@/components/Term";
import AppliesToChip from "@/components/rules/AppliesToChip";
import AttemptCompare from "@/components/rules/AttemptCompare";
import PlanView from "@/components/rules/PlanView";
import ProvenanceChip from "@/components/rules/ProvenanceChip";
import ReasonModal from "@/components/rules/ReasonModal";
import SeverityChip from "@/components/rules/SeverityChip";
import StatusChip from "@/components/rules/StatusChip";

/** Round 5 task 12 — the collapsible status sections, in review order.
 * INACTIVE is a FLAG not a status: any rule with active=false lands in the
 * Inactive section (never under Published), so what is actually running is
 * unambiguous. Labels and one-line meanings come from the glossary
 * (rule_status.<KEY>) — never hardcoded here. */
const SECTION_ORDER = [
  "DRAFT",
  "NEEDS_INPUT",
  "NEEDS_DATA",
  "COMPILED",
  "PUBLISHED",
  "INACTIVE",
  "SUPERSEDED",
  "REJECTED",
] as const;
type SectionId = (typeof SECTION_ORDER)[number];

/** The page opens on the work: what needs attention expands, what is already
 * working (or historical) collapses. Empty sections are hidden entirely. */
const DEFAULT_EXPANDED: ReadonlySet<SectionId> = new Set([
  "DRAFT",
  "NEEDS_INPUT",
  "NEEDS_DATA",
  "COMPILED",
]);

/** Sections whose rules are draft-pool (selectable for delete). */
const SELECTABLE_SECTIONS: ReadonlySet<SectionId> = new Set([
  "DRAFT",
  "NEEDS_INPUT",
  "NEEDS_DATA",
  "COMPILED",
  "REJECTED",
]);

const SEVERITY_ORDER = ["CRITICAL", "HIGH", "MODERATE", "LOW", "INFO"];

/** Round 5 task 13.2/13.3 — preset filters handed over from a document row's
 * count links. `token` forces re-application when the same link is clicked
 * twice. */
export interface RulesPreset {
  documentId?: string;
  status?: string;
  token?: number;
}

function keyOf(rule: RuleDetail): string {
  return rule.rule_key || rule.rule_code;
}

/** Compile attempts are serialized on draft rules; lib/api's RuleDetail does
 * not declare them, so read structurally. */
type WithAttempts = RuleDetail & {
  compile_attempts?: CompileAttempt[];
  picked_attempt_no?: number | null;
};

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
  archived: RuleDetail[];
  version: RuleVersion | null;
}

function errText(e: unknown): string {
  if (e instanceof ApiError || e instanceof RulesApiError) return e.message;
  return String((e as Error)?.message || e);
}

/** One collapsible status section: header with count + plain-English meaning,
 * pagination WITHIN the section, per-section select-all on draft-pool rules.
 * Top-level component so its pager state survives parent re-renders. */
function StatusSection({
  label,
  meaning,
  rules,
  expanded,
  onToggle,
  renderRow,
  selectable,
  selected,
  onToggleAll,
}: {
  label: string;
  meaning: string | null;
  rules: RuleDetail[];
  expanded: boolean;
  onToggle: () => void;
  renderRow: (rule: RuleDetail, selectable: boolean) => ReactNode;
  selectable: boolean;
  selected: Set<string>;
  onToggleAll: (rules: RuleDetail[], on: boolean) => void;
}) {
  const pager = usePager(rules);
  if (!rules.length) return null; // empty sections are hidden entirely
  const allSelected = rules.every((r) => selected.has(r.rule_key || r.rule_code));
  return (
    <div style={{ marginBottom: 10, border: "1px solid var(--rule)", borderRadius: 6 }}>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle();
          }
        }}
        style={{
          display: "flex",
          gap: 10,
          alignItems: "baseline",
          flexWrap: "wrap",
          padding: "8px 10px",
          cursor: "pointer",
        }}
      >
        <b style={{ fontSize: 13, whiteSpace: "nowrap" }}>
          <span aria-hidden="true" style={{ display: "inline-block", width: 14 }}>
            {expanded ? "▾" : "▸"}
          </span>
          {label} ({rules.length})
        </b>
        {meaning ? (
          <span style={{ fontSize: 12, color: "var(--slate)", minWidth: 0 }}>{meaning}</span>
        ) : null}
      </div>
      {expanded ? (
        <div style={{ padding: "0 10px 8px" }}>
          {selectable && rules.length > 1 ? (
            <div
              style={{
                display: "flex",
                gap: 10,
                alignItems: "center",
                padding: "4px 0 8px",
                borderBottom: "1px solid var(--rule)",
                marginBottom: 8,
              }}
            >
              <input
                type="checkbox"
                checked={allSelected}
                onChange={(e) => onToggleAll(rules, e.target.checked)}
                aria-label={`Select every ${label} rule matching the current filters`}
              />
              <span style={{ fontSize: 12, color: "var(--slate)" }}>
                Select all {rules.length} (every match, not just this page)
              </span>
            </div>
          ) : null}
          {pager.rows.map((r) => renderRow(r, selectable))}
          <Pager {...pager} noun="rules" />
        </div>
      ) : null}
    </div>
  );
}

export default function RuleListManager({ preset }: { preset?: RulesPreset | null }) {
  const [pools, setPools] = useState<Pools | null>(null);
  const [summary, setSummary] = useState<ExtractionSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reasonFor, setReasonFor] = useState<RuleDetail | null>(null);
  const [busy, setBusy] = useState(false);
  // Task 12a — retry query generation, moved here from the old page column
  const [retryFor, setRetryFor] = useState<string | null>(null);
  const [retryNote, setRetryNote] = useState("");
  const [retryBusy, setRetryBusy] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  // filters — "" means All. fStatus COLLAPSES the other sections rather than
  // hiding rows (task 12); the other filters narrow rows within sections.
  const [fStatus, setFStatus] = useState("");
  const [fProvenance, setFProvenance] = useState("");
  const [fScope, setFScope] = useState("");
  const [fSeverity, setFSeverity] = useState("");
  const [fDocument, setFDocument] = useState("");
  // per-section expand/collapse overrides on top of the defaults
  const [sectionOverrides, setSectionOverrides] = useState<Partial<Record<SectionId, boolean>>>({});
  // document_id -> display name (13.3: options derive from the data)
  const [docNames, setDocNames] = useState<Record<string, string>>({});
  const glossary = useGlossary();

  const refresh = useCallback(() => {
    getExtractionSummary()
      .then(setSummary)
      .catch(() => setSummary(null));
    getDocuments()
      .then((res) => {
        const names: Record<string, string> = {};
        for (const d of res.documents ?? []) names[d.document_id] = d.document_name;
        setDocNames(names);
      })
      .catch(() => setDocNames({}));
    Promise.all([
      getRulesDetailed("drafts"),
      // no published version yet is a normal state, not an error
      getRulesDetailed("latest").catch((e) => {
        if (e instanceof ApiError && e.status === 404) return { version: null, rules: [] };
        throw e;
      }),
      // superseded/rejected history — absent endpoint is not a page-breaker
      getRulesDetailed("archived").catch(() => ({ version: null, rules: [] })),
    ])
      .then(([draftRes, latestRes, archivedRes]) => {
        setPools({
          drafts: draftRes.rules ?? [],
          published: (latestRes.rules ?? []).filter((r) => r.status !== "SUPERSEDED"),
          archived: archivedRes.rules ?? [],
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

  // 13.3 — a preset from a document row's count link applies on arrival (and
  // re-applies when the same link is clicked again — the token changes).
  useEffect(() => {
    if (!preset) return;
    setFDocument(preset.documentId ?? "");
    setFStatus(preset.status ?? "");
    setSectionOverrides({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset?.documentId, preset?.status, preset?.token]);

  const allRules = useMemo(
    () => (pools ? [...pools.drafts, ...pools.published, ...pools.archived] : []),
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
  // 13.3 — document filter options: every document_id present on a rule,
  // resolved to the document's display name where the catalog knows it.
  const documentOptions = useMemo(() => {
    const ids = [...new Set(allRules.map((r) => r.document_id).filter(Boolean))] as string[];
    return ids
      .map((id) => [id, docNames[id] || id] as [string, string])
      .sort((a, b) => a[1].localeCompare(b[1]));
  }, [allRules, docNames]);

  /** Which section a rule lives in. Inactive is a FLAG, not a status — a
   * PUBLISHED rule with active=false appears under Inactive, never under
   * Published, so what is actually running is unambiguous. (A superseded or
   * draft-pool rule keeps its status section: it is not running for a
   * different reason, and Inactive would mask that.) */
  const sectionOf = (r: RuleDetail): SectionId => {
    const s = (r.status || "DRAFT") as SectionId;
    if (s === "PUBLISHED" && r.active === false) return "INACTIVE";
    return (SECTION_ORDER as readonly string[]).includes(s) ? s : "DRAFT";
  };

  // Row-narrowing filters. Status is NOT here — selecting a status collapses
  // the other sections rather than hiding their rules (task 12).
  const matchesFilters = useCallback(
    (r: RuleDetail) =>
      (!fProvenance || r.provenance === fProvenance) &&
      (!fScope || (r.applies_to || "ALL") === fScope) &&
      (!fSeverity || (r.severity || "").toUpperCase() === fSeverity) &&
      (!fDocument || r.document_id === fDocument),
    [fProvenance, fScope, fSeverity, fDocument],
  );

  const sectionRules = useMemo(() => {
    const grouped: Record<SectionId, RuleDetail[]> = {
      DRAFT: [], NEEDS_INPUT: [], NEEDS_DATA: [], COMPILED: [],
      PUBLISHED: [], INACTIVE: [], SUPERSEDED: [], REJECTED: [],
    };
    for (const r of allRules.filter(matchesFilters)) grouped[sectionOf(r)].push(r);
    for (const key of SECTION_ORDER) {
      grouped[key].sort((a, b) => a.rule_code.localeCompare(b.rule_code));
    }
    return grouped;
  }, [allRules, matchesFilters]);

  // status dropdown options = sections that exist in the (row-filtered) data,
  // Inactive included as its own entry
  const statusOptions = useMemo(
    () => SECTION_ORDER.filter((s) => sectionRules[s].length > 0),
    [sectionRules],
  );

  /** Default expansion reflects what needs attention; a status filter
   * collapses every other section; a header click overrides either. */
  const isExpanded = (section: SectionId): boolean => {
    const override = sectionOverrides[section];
    if (override !== undefined) return override;
    if (fStatus) return section === fStatus;
    return DEFAULT_EXPANDED.has(section);
  };

  const sectionLabel = (section: SectionId): string =>
    glossary?.terms?.[`rule_status.${section}`]?.term ||
    section.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const sectionMeaning = (section: SectionId): string | null =>
    glossary?.terms?.[`rule_status.${section}`]?.definition || null;

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

  const runRetry = async (ruleKey: string) => {
    setRetryBusy(true);
    setRetryError(null);
    try {
      await recompileRule(ruleKey, retryNote);
      setRetryFor(null);
      setRetryNote("");
      refresh();
    } catch (e) {
      setRetryError(
        e instanceof RulesApiError && (e.status === 0 || e.status === 404)
          ? "The recompile service is not reachable."
          : errText(e),
      );
    } finally {
      setRetryBusy(false);
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
        {/* Task 12a / C2 — compiled query COLLAPSED by default, expand to view */}
        {rule.plan || rule.natural_language_only ? (
          <details className="tech" style={{ marginTop: 6 }}>
            <summary>Query this compiles to</summary>
            <PlanView
              plan={rule.plan}
              explanation={rule.explanation}
              naturalLanguageOnly={rule.natural_language_only === true}
            />
          </details>
        ) : null}
        {/* Task 12a / C2 — attempts open ON CLICK, never inline-always */}
        {rule.rule_key && ((rule as WithAttempts).compile_attempts?.length ?? 0) > 0 ? (
          <details className="tech" style={{ marginTop: 6 }}>
            <summary>
              {(rule as WithAttempts).compile_attempts?.length} compile attempt
              {((rule as WithAttempts).compile_attempts?.length ?? 0) === 1 ? "" : "s"} — open to
              compare and pick
            </summary>
            <AttemptCompare
              ruleKey={rule.rule_key}
              attempts={(rule as WithAttempts).compile_attempts ?? []}
              pickedAttemptNo={(rule as WithAttempts).picked_attempt_no}
              onPicked={refresh}
            />
          </details>
        ) : null}
        {/* Task 12a — retry / generate query on unapproved computed rules */}
        {!approved &&
        rule.rule_key &&
        ["DRAFT", "COMPILED", "NEEDS_DATA"].includes((rule.status || "DRAFT").toUpperCase()) &&
        !rule.natural_language_only ? (
          <div style={{ marginTop: 6 }}>
            {retryFor === rule.rule_key ? (
              <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                <input
                  className="filter"
                  style={{ flex: 1, minWidth: 220 }}
                  placeholder="Optional note for the compiler — e.g. “this should be at RPG level, not account”"
                  value={retryNote}
                  onChange={(e) => setRetryNote(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !retryBusy) runRetry(rule.rule_key as string);
                    if (e.key === "Escape") setRetryFor(null);
                  }}
                />
                <button className="btn primary" disabled={retryBusy} onClick={() => runRetry(rule.rule_key as string)}>
                  {retryBusy ? "Compiling…" : "Ask for another plan"}
                </button>
                <button className="btn" disabled={retryBusy} onClick={() => setRetryFor(null)}>
                  Cancel
                </button>
              </div>
            ) : (
              <button
                className="btn"
                onClick={() => {
                  setRetryFor(rule.rule_key as string);
                  setRetryNote("");
                  setRetryError(null);
                }}
              >
                {rule.plan ? "Retry query generation" : "Generate query"}
              </button>
            )}
            {retryError && retryFor === rule.rule_key ? (
              <div style={{ color: "var(--neg, #B3261E)", fontSize: 12.5, marginTop: 4 }}>{retryError}</div>
            ) : null}
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
        <select
          value={fStatus}
          onChange={(e) => {
            // task 12: isolating one status COLLAPSES the other sections
            // rather than hiding them; clearing restores the defaults
            setFStatus(e.target.value);
            setSectionOverrides({});
          }}
          aria-label="Filter by status"
        >
          <option value="">All Statuses</option>
          {statusOptions.map((s) => (
            <option key={s} value={s}>
              {sectionLabel(s)}
            </option>
          ))}
        </select>
        <select
          value={fDocument}
          onChange={(e) => setFDocument(e.target.value)}
          aria-label="Filter by document"
        >
          <option value="">All Documents</option>
          {documentOptions.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
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

      {/* Round 5 task 12 — collapsible sections grouped by status, counts +
          plain-English meanings (from the glossary) in the headers, pagination
          WITHIN each section, empty sections hidden. */}
      {pools.version?.version_no != null ? (
        <div style={{ fontSize: 12, color: "var(--slate)", marginBottom: 8 }}>
          Draft pool + published v{pools.version.version_no} — only Published rules affect insight
          generation.
        </div>
      ) : null}
      {SECTION_ORDER.map((section) => (
        <StatusSection
          key={section}
          label={sectionLabel(section)}
          meaning={sectionMeaning(section)}
          rules={sectionRules[section]}
          expanded={isExpanded(section)}
          onToggle={() =>
            setSectionOverrides((prev) => ({ ...prev, [section]: !isExpanded(section) }))
          }
          renderRow={ruleRow}
          selectable={SELECTABLE_SECTIONS.has(section)}
          selected={selected}
          onToggleAll={toggleGroup}
        />
      ))}
      {SECTION_ORDER.every((s) => sectionRules[s].length === 0) ? (
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
