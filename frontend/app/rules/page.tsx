"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  type NeverFiredResponse,
  type RuleDetail,
  type RuleVersion,
  getNeverFired,
  getRuleVersions,
  getRulesDetailed,
} from "@/lib/api";
import { RulesApiError, setRuleActive } from "@/lib/rulesApi";
import Chip from "@/components/Chip";
import EmptyState from "@/components/EmptyState";
import { Pager, usePager } from "@/components/Pager";
import PageHeader from "@/components/PageHeader";
import RuleCitationLine from "@/components/RuleCitation";
import AppliesToChip from "@/components/rules/AppliesToChip";
import ProvenanceChip from "@/components/rules/ProvenanceChip";
import ReasonModal from "@/components/rules/ReasonModal";
import RuleEditDialog from "@/components/rules/RuleEditDialog";
import SeverityChip from "@/components/rules/SeverityChip";
import StatusChip from "@/components/rules/StatusChip";
import PlanView from "@/components/rules/PlanView";
import VersionCompare from "@/components/rules/VersionCompare";

/** Rule Set Versions — Round C (docs/rules) task 7.
 * 7.1 EVERY version (v0 and superseded ones included) expands to its full
 *     rules — statement, worked example, provenance, applies_to scope,
 *     severity, driver, citation, compiled plan with explanation — and every
 *     rule is editable; an edit mints a NEW version, never a mutation.
 * 7.2 Editing runs through RuleEditDialog; active state through ReasonModal
 *     (mandatory reason, who/when/why recorded).
 * 7.3 Selecting two versions compares them client-side (VersionCompare).
 * 7.4 The Round H never-fired card stays. */
export default function RuleVersionsPage() {
  const [versions, setVersions] = useState<RuleVersion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rulesByVersion, setRulesByVersion] = useState<Record<string, RuleDetail[]>>({});
  const [openVersion, setOpenVersion] = useState<string | null>(null);
  const [editing, setEditing] = useState<RuleDetail | null>(null);
  const [togglingActive, setTogglingActive] = useState<RuleDetail | null>(null);
  const [activeBusy, setActiveBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // 7.3 — the two version ids picked for comparison, oldest-first when shown
  const [compareSel, setCompareSel] = useState<string[]>([]);
  // Round H 2.4/4.3: rules with zero matches across the whole period
  const [neverFired, setNeverFired] = useState<NeverFiredResponse | null>(null);
  const [neverFiredError, setNeverFiredError] = useState<string | null>(null);

  useEffect(() => {
    getNeverFired("latest")
      .then((r) => {
        setNeverFired(r);
        setNeverFiredError(null);
      })
      .catch((e) =>
        setNeverFiredError(
          e instanceof ApiError && e.status === 404
            ? "No published rule set to check yet."
            : String((e as Error)?.message || e),
        ),
      );
  }, []);

  const reload = useCallback(() => {
    getRuleVersions()
      .then((res) => {
        setVersions([...(res.versions ?? [])].sort((a, b) => b.version_no - a.version_no));
        setError(null);
      })
      .catch((e) => {
        setVersions(null);
        setError(
          e instanceof ApiError && e.status === 404
            ? "The rule service (B3) is not available yet."
            : String(e?.message || e),
        );
      });
  }, []);

  useEffect(reload, [reload]);

  const toggle = (versionId: string) => {
    if (openVersion === versionId) {
      setOpenVersion(null);
      return;
    }
    setOpenVersion(versionId);
    if (!rulesByVersion[versionId]) {
      getRulesDetailed(versionId)
        .then((res) => setRulesByVersion((prev) => ({ ...prev, [versionId]: res.rules })))
        .catch((e) => setError(String(e?.message || e)));
    }
  };

  const toggleCompare = (versionId: string) => {
    setCompareSel((prev) =>
      prev.includes(versionId)
        ? prev.filter((v) => v !== versionId)
        : prev.length >= 2
          ? [prev[1], versionId] // keep the most recent pick, add the new one
          : [...prev, versionId],
    );
  };

  const afterMutation = (message: string, refresh: boolean) => {
    setNotice(message);
    setEditing(null);
    setTogglingActive(null);
    if (refresh) {
      setRulesByVersion({});
      setOpenVersion(null);
      setCompareSel([]);
      reload();
    }
  };

  const submitActive = async (rule: RuleDetail, reason: string) => {
    const deactivating = rule.active !== false;
    setActiveBusy(true);
    try {
      const { version, note } = await setRuleActive(
        rule.rule_key ?? rule.rule_code,
        !deactivating,
        reason,
      );
      afterMutation(
        version
          ? `${rule.rule_code} is now ${deactivating ? "inactive" : "active"} — v${version.version_no} ` +
              "published with the who/when/why recorded; the prior version is unchanged."
          : note || `${rule.rule_code} updated (draft pool — a version mints at publish).`,
        true,
      );
    } catch (e) {
      setNotice(
        `${deactivating ? "Deactivate" : "Reactivate"} failed: ` +
          String((e as RulesApiError | Error)?.message || e),
      );
      setTogglingActive(null);
    } finally {
      setActiveBusy(false);
    }
  };

  // Task 12b — the versions list paginates (5/10/20, default 5); v0 sits on
  // the last page and is fully expandable and editable like any other version.
  const verPager = usePager(versions ?? []);
  // Task 12b — the never-fired list paginates too
  const neverFiredPager = usePager(neverFired?.never_fired ?? []);

  // Resolve the compare pair oldest → newest by version_no
  const comparePair =
    compareSel.length === 2 && versions
      ? ([...compareSel]
          .map((id) => versions.find((v) => (v.version_id ?? String(v.version_no)) === id))
          .filter(Boolean) as RuleVersion[]).sort((a, b) => a.version_no - b.version_no)
      : null;

  return (
    <section>
      <PageHeader title="Rule Set Versions" meta="Every insight records the version that produced it" />
      <div className="card">
        <div className="card-h">
          <div>
            <h2>Rule Set Versions</h2>
            <p>
              Expand any version — v0 and superseded ones included — to see every rule it
              contains. Versions are superseded, never deleted; edits mint a new version. Tick two
              versions to compare them.
            </p>
          </div>
        </div>
        <div className="card-b">
          {notice ? (
            <div className="note" style={{ marginBottom: 12, border: "1px solid var(--rule)", borderRadius: 5 }}>
              {notice}
            </div>
          ) : null}
          {versions && versions.length ? (
            <ul className="vers">
              {verPager.rows.map((v) => {
                const versionId = v.version_id ?? String(v.version_no);
                const status = (v.status || "").toUpperCase();
                const current = status === "PUBLISHED";
                const open = openVersion === versionId;
                const rules = rulesByVersion[versionId];
                return (
                  <li key={versionId} className={current ? "cur" : undefined} style={{ display: "block" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 14, alignItems: "flex-start" }}>
                      <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                        {versions.length > 1 ? (
                          <input
                            type="checkbox"
                            title="Select two versions to compare"
                            checked={compareSel.includes(versionId)}
                            onChange={() => toggleCompare(versionId)}
                            style={{ marginTop: 3 }}
                          />
                        ) : null}
                        <div>
                          <b>
                            v{v.version_no}
                            {v.published_at ? ` · Published ${v.published_at}` : v.created_at ? ` · ${v.created_at}` : ""}
                          </b>
                          <div className="meta">
                            {[
                              v.rule_count != null ? `${v.rule_count} rules` : null,
                              v.approved_by ? `approved by ${v.approved_by}` : null,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                            {v.notes ? (
                              <>
                                <br />
                                {v.notes}
                              </>
                            ) : null}
                          </div>
                        </div>
                      </div>
                      <div style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        {current ? (
                          <Chip variant="pos">In Use</Chip>
                        ) : (
                          <Chip variant="tag">Superseded</Chip>
                        )}
                        {v.version_no === 0 ? <Chip variant="derived">v0 Seed</Chip> : null}
                        <div style={{ marginTop: 6 }}>
                          <button className="btn" onClick={() => toggle(versionId)}>
                            {open ? "Collapse" : `View ${v.rule_count ?? ""} rules`}
                          </button>
                        </div>
                      </div>
                    </div>
                    {open ? (
                      rules ? (
                        // Task 12b — per-version rule lists paginate; keyed so
                        // the pager resets when a different version is opened
                        <VersionRules
                          key={versionId}
                          rules={rules}
                          currentVersion={current}
                          onEdit={setEditing}
                          onToggleActive={setTogglingActive}
                        />
                      ) : (
                        <div className="meta" style={{ marginTop: 10 }}>
                          Loading rules…
                        </div>
                      )
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState
              title={error ? "Versions Unavailable" : "No Rule Set Versions Yet"}
              message={error ?? "Published rule set versions will appear here."}
            />
          )}
          {versions && versions.length ? <Pager {...verPager} noun="versions" /> : null}
        </div>
      </div>

      {/* 7.3 — what changed between two versions, at a glance */}
      {comparePair && comparePair.length === 2 ? (
        <div className="card">
          <div className="card-h">
            <div>
              <h2>Version Comparison</h2>
              <p>
                Rules added, removed and modified between the two selected versions, with the
                specific fields that differ. Identity churn (rule keys, timestamps, compile stats)
                is ignored — only meaningful changes show.
              </p>
            </div>
            <button className="btn" onClick={() => setCompareSel([])}>
              Clear selection
            </button>
          </div>
          <div className="card-b">
            <VersionCompare
              olderVersionId={comparePair[0].version_id ?? String(comparePair[0].version_no)}
              olderLabel={`v${comparePair[0].version_no}`}
              newerVersionId={comparePair[1].version_id ?? String(comparePair[1].version_no)}
              newerLabel={`v${comparePair[1].version_no}`}
            />
          </div>
        </div>
      ) : compareSel.length === 1 ? (
        <div className="note" style={{ margin: "0 0 14px" }}>
          One version selected — tick a second one to compare.
        </div>
      ) : null}

      {/* Round H 2.4/4.3 — a rule that never fires is either wrong or
          inapplicable; it must be obvious here, not need a code read. */}
      <div className="card">
        <div className="card-h">
          <div>
            <h2>Rules That Never Fired</h2>
            <p>
              Every rule in the latest published version, evaluated at practice scope and per
              advisor across every month in the data. Zero matches everywhere means the rule is
              either wrong or inapplicable to this data.
            </p>
          </div>
          {neverFired ? (
            <span className={`chip ${neverFired.never_fired.length ? "neg" : "pos"}`}>
              {neverFired.never_fired.length
                ? `${neverFired.never_fired.length} Never Fired`
                : "All Rules Fired"}
            </span>
          ) : null}
        </div>
        <div className="card-b">
          {neverFired ? (
            neverFired.never_fired.length ? (
              <>
                {neverFiredPager.rows.map((r) => (
                  <div key={r.rule_code} className="rule conflict">
                    <div className="rule-h">
                      <div>
                        <div className="rule-t">
                          {r.rule_name || r.rule_code} <span className="pfx">({r.rule_code})</span>
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                        {r.scopes.map((s) => (
                          <Chip key={s} variant="tag">
                            {s}
                          </Chip>
                        ))}
                        <Chip variant="neg">0 matches</Chip>
                      </div>
                    </div>
                    <div className="rule-d">{r.note}</div>
                  </div>
                ))}
                <Pager {...neverFiredPager} noun="rules" />
                <div className="note" style={{ border: "1px solid var(--rule)", borderRadius: 5 }}>
                  Checked {neverFired.months.length} month
                  {neverFired.months.length === 1 ? "" : "s"} ({neverFired.months[0]} –{" "}
                  {neverFired.months[neverFired.months.length - 1]}) across{" "}
                  {neverFired.advisors_checked} advisors plus the practice scope.
                </div>
              </>
            ) : (
              <EmptyState
                title="Every rule fired at least once in the period"
                message={`All rules in ${neverFired.version_id} matched at least one entity across ${neverFired.months.length} months and ${neverFired.advisors_checked} advisors (practice scope included).`}
              />
            )
          ) : neverFiredError ? (
            <EmptyState title="Never-fired check unavailable" message={neverFiredError} />
          ) : (
            <div className="meta" style={{ color: "var(--slate)", fontSize: "12.5px" }}>
              Evaluating every rule across every month and scope…
            </div>
          )}
        </div>
      </div>

      {/* 7.2 — the edit dialog; every save mints a new version */}
      {editing ? (
        <RuleEditDialog
          rule={editing}
          open={true}
          onClose={() => setEditing(null)}
          onDone={afterMutation}
        />
      ) : null}

      {/* 2.1/7.2 — deactivate/reactivate with the MANDATORY reason */}
      {togglingActive ? (
        <ReasonModal
          open={true}
          title={
            togglingActive.active !== false
              ? `Deactivate ${togglingActive.rule_code}`
              : `Reactivate ${togglingActive.rule_code}`
          }
          prompt={
            togglingActive.active !== false ? (
              <>
                An inactive rule stops feeding NEW insight generation but stays queryable, and
                prior insights that cited it stay valid with their version. This mints a new rule
                set version; who, when and why are recorded.
              </>
            ) : (
              <>
                Reactivating puts the rule back into new insight generation. It equally changes
                what the next run produces, so it mints a version and the reason is recorded.
              </>
            )
          }
          confirmLabel={togglingActive.active !== false ? "Deactivate" : "Reactivate"}
          busy={activeBusy}
          onConfirm={(reason) => submitActive(togglingActive, reason)}
          onCancel={() => setTogglingActive(null)}
        />
      ) : null}
    </section>
  );
}

/** Task 12b — an expanded version's rules, paginated 5/10/20 (default 5).
 * Every version's rules — v0 included — render in full detail with the Edit
 * action; an edit mints a new version, never a mutation. */
function VersionRules({
  rules,
  currentVersion,
  onEdit,
  onToggleActive,
}: {
  rules: RuleDetail[];
  currentVersion: boolean;
  onEdit: (rule: RuleDetail) => void;
  onToggleActive: (rule: RuleDetail) => void;
}) {
  const pager = usePager(rules);
  return (
    <div style={{ marginTop: 12 }}>
      {pager.rows.map((r) => (
        <RuleRow
          key={r.rule_key ?? r.rule_code}
          rule={r}
          currentVersion={currentVersion}
          onEdit={() => onEdit(r)}
          onToggleActive={() => onToggleActive(r)}
        />
      ))}
      <Pager {...pager} noun="rules" />
    </div>
  );
}

/** One rule inside an expanded version — the full 7.1 detail set. */
function RuleRow({
  rule,
  currentVersion,
  onEdit,
  onToggleActive,
}: {
  rule: RuleDetail;
  currentVersion: boolean;
  onEdit: () => void;
  onToggleActive: () => void;
}) {
  const status = (rule.status || "").toUpperCase();
  const inactive = rule.active === false;
  return (
    <div className={`rule${status === "NEEDS_INPUT" ? " needs" : ""}`} style={inactive ? { opacity: 0.85 } : undefined}>
      <div className="rule-h">
        <div>
          <div className="rule-t">
            {rule.rule_name} <span className="pfx">({rule.rule_code})</span>
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
          <ProvenanceChip provenance={rule.provenance} provenanceLabel={rule.provenance_label} />
          <AppliesToChip appliesTo={rule.applies_to} appliesToKey={rule.applies_to_key} />
          <SeverityChip severity={rule.severity} />
          <StatusChip status={rule.status} active={rule.active} activeReason={rule.active_reason} />
          <button className="btn" onClick={onEdit} title="Editing mints a new version — this one is never mutated">
            Edit → new version
          </button>
          {currentVersion ? (
            <button
              className="btn"
              onClick={onToggleActive}
              title={
                inactive
                  ? "Put the rule back into new insight generation (reason required)"
                  : "Stop the rule feeding new insight generation without superseding it (reason required)"
              }
            >
              {inactive ? "Reactivate" : "Deactivate"}
            </button>
          ) : null}
        </div>
      </div>
      {/* 2.1 — the recorded who/when/why, distinct from Superseded */}
      {inactive ? (
        <div className="eg" style={{ borderLeft: "3px solid var(--amber, #B7791F)", paddingLeft: 8 }}>
          <b>Inactive</b> — not evaluated in new insight runs; still queryable, and prior insights
          citing it stay valid.
          <br />
          {rule.active_reason ? (
            <>
              Reason: <i>{rule.active_reason}</i>
            </>
          ) : (
            "No reason recorded."
          )}
          {rule.active_changed_by ? ` · by ${rule.active_changed_by}` : ""}
          {rule.active_changed_at ? ` · ${rule.active_changed_at}` : ""}
        </div>
      ) : null}
      {/* 7.1: the rule's plain-English statement */}
      <div className="rule-d">{rule.statement || rule.plain_description}</div>
      {/* Driver: label + definition (label is a read-time registry) */}
      {rule.driver_label ? (
        <div className="eg">
          <b>Driver:</b> {rule.driver_label}
          {rule.driver_definition ? ` — ${rule.driver_definition}` : ""}
        </div>
      ) : null}
      {/* Round H task 1/4.3: exclusion is declared ON the rule and shown here */}
      {rule.exclude_matched_of?.length ? (
        <div className="eg">
          <b>Excludes accounts matched by:</b> {rule.exclude_matched_of.join(", ")}
        </div>
      ) : null}
      {rule.worked_example ? (
        <div className="eg">
          Example — <b>{rule.worked_example}</b>
        </div>
      ) : null}
      {/* Citation where one exists; a tech-written rule says so explicitly */}
      <div className="eg">
        <RuleCitationLine
          ruleKey={rule.rule_key ?? rule.rule_code}
          ruleName={rule.rule_name}
          citation={rule.citations?.[0] ?? null}
          provenance={rule.provenance}
        />
      </div>
      {/* 7.1: the compiled plan with its plain-English explanation */}
      <details className="tech">
        <summary>Query this compiles to</summary>
        <PlanView
          plan={rule.plan}
          explanation={rule.explanation}
          naturalLanguageOnly={rule.natural_language_only === true}
        />
      </details>
      {rule.needs_data_reason ? (
        <div className="eg">
          <b>Needs data we don&rsquo;t have:</b> {rule.needs_data_reason}
        </div>
      ) : null}
      {rule.missing ? (
        <div className="eg">
          <b>Needs a value:</b> {rule.missing}
        </div>
      ) : null}
    </div>
  );
}
