"use client";

/** Round A2B 4.2 + Round 3 Task 10 (§E/F) — the dashboard's Revenue Drivers
 * card.
 *
 * Self-contained: fetches the SAME stored run as the AI Insights section but
 * independently (no shared loading gate), and renders its own empty state.
 * Revenue Drivers speaks for the individual drivers, purely rule-driven; the
 * AI Insights section is the cross-cutting firm-level narrative — the two are
 * deliberately NOT merged (review §E).
 *
 * Props (the common section contract — the main thread composes this into
 * `app/page.tsx`):
 *   - `fromMonth: string`  — from-month id, e.g. "202604"
 *   - `toMonth: string`    — to-month id, e.g. "202605"
 *   - `monthName: (id: string) => string` — month id -> display name
 *
 * Behaviour:
 *   - Findings ranked by |impact_amt|. "By Driver" / "By Product" pivot
 *     regroups CLIENT-SIDE without refetching. Review F2 fix: By Product
 *     groups on the finding's group_id but LABELS with the served group_name
 *     (never the raw id); findings with no attribution go under "No product
 *     attribution".
 *   - Each entry is a `.finding` accordion: title, driver tag (bold,
 *     unwrapped — F9; provenance REAL/DUMMY chips removed per Task 8),
 *     impact, a "Source / Citation" rule line (F8), and the SHARED
 *     <EvidenceTable> (F3–F7: collapsed with a note, labelized headers,
 *     paginated, shrinks to content, footer totals).
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { type Finding, getRuleVersions } from "@/lib/api";
import Chip from "@/components/Chip";
import EmptyState from "@/components/EmptyState";
import { EvidenceTable } from "@/components/EvidenceTable";
import { NarrativeText } from "@/components/Num";
import RuleCitationLine from "@/components/RuleCitation";
import { useTerm } from "@/components/Term";
import { money } from "@/lib/format";
import { driverCode, rankFindings, useInsightRun } from "@/components/insights/shared";

export interface DriversSectionProps {
  fromMonth: string;
  toMonth: string;
  monthName: (id: string) => string;
}

type Pivot = "driver" | "product";

/** The API serializes group_name alongside group_id on every finding (Round 3
 * — the F2 fix); lib/api.ts's Finding type predates it, typed locally here
 * rather than editing the shared file (gap reported). */
type FindingWithGroup = Finding & { group_name?: string | null };

/** [key, label] of the product group a finding belongs to — key groups, the
 * served group_name labels (never the raw id). */
function productGroup(f: Finding): { key: string; label: string } | null {
  const fg = f as FindingWithGroup;
  if (f.group_id) return { key: f.group_id, label: fg.group_name || "No product attribution" };
  return null;
}

const NO_ATTRIBUTION = "No product attribution";

export default function DriversSection({ fromMonth, toMonth, monthName }: DriversSectionProps) {
  const { run, notGenerated, error, loading } = useInsightRun(fromMonth, toMonth);
  const [pivot, setPivot] = useState<Pivot>("driver");
  // Round 8 task 1 — with NO published rules this section cannot do its job
  // (it explains movements USING rules); the state is said plainly instead of
  // degrading silently. null = still checking (nothing is claimed either way).
  const [noPublishedRules, setNoPublishedRules] = useState<boolean | null>(null);
  useEffect(() => {
    getRuleVersions()
      .then((r) =>
        setNoPublishedRules(
          !(r.versions ?? []).some((v) => v.status === "PUBLISHED" && (v.rule_count ?? 0) > 0),
        ),
      )
      .catch(() => setNoPublishedRules(null));
  }, []);

  const complete = run && run.status === "COMPLETE" ? run : null;
  const ranked = useMemo(() => (complete ? rankFindings(complete.findings) : []), [complete]);

  // pivot regroups the SAME ranked findings — it never refetches
  const groups = useMemo(() => {
    const map = new Map<string, { label: string; findings: Finding[] }>();
    for (const f of ranked) {
      const product = productGroup(f);
      const key =
        pivot === "driver" ? driverCode(f) : product?.key ?? NO_ATTRIBUTION;
      const label =
        pivot === "driver" ? f.driver_tag || key : product?.label ?? NO_ATTRIBUTION;
      const entry = map.get(key) ?? { label, findings: [] };
      entry.findings.push(f);
      map.set(key, entry);
    }
    // Round 4 sweep — attributed product groups lead; the honest
    // "No product attribution" bucket renders last, never first.
    return Array.from(map.values()).sort(
      (a, b) => Number(a.label === NO_ATTRIBUTION) - Number(b.label === NO_ATTRIBUTION),
    );
  }, [ranked, pivot]);

  return (
    <div className="card">
      <div className="card-h">
        <div>
          {/* Review F1 — renamed from "Drivers" */}
          <h2>Revenue Drivers</h2>
          <p>
            What moved the number, ranked by impact · {monthName(fromMonth)} → {monthName(toMonth)}
          </p>
        </div>
        <div className="pivot" role="tablist" aria-label="Group findings">
          <button aria-selected={pivot === "driver"} onClick={() => setPivot("driver")}>
            By Driver
          </button>
          <button aria-selected={pivot === "product"} onClick={() => setPivot("product")}>
            By Product
          </button>
        </div>
      </div>
      <div className="card-b flush" style={{ padding: 0 }}>
        {noPublishedRules ? (
          /* Round 8 task 1 — the no-rules state, said plainly: any findings
             below (and the AI Insights above) are data-derived, not
             plan-derived. The app degrades, it does not fail. */
          <div style={{ padding: "14px 18px", fontSize: "12.5px", borderBottom: "1px solid var(--rule-2)" }}>
            <b>No published rules.</b> Revenue Drivers explains movements using rules extracted from
            your plan documents. Nothing is published yet, so the AI Insights above are derived
            entirely from the data rather than from plan provisions.
            <div style={{ marginTop: 6 }}>
              <Link className="btn sm" href="/documents" style={{ textDecoration: "none" }}>
                Upload a document
              </Link>
            </div>
          </div>
        ) : null}
        {error ? (
          <div style={{ padding: 18 }}>
            <EmptyState title="Revenue Drivers failed to load" message={error} />
          </div>
        ) : null}
        {loading ? (
          <p style={{ color: "var(--slate)", fontSize: "12.5px", margin: 0, padding: "14px 18px" }}>
            Loading…
          </p>
        ) : null}
        {notGenerated ? (
          <div style={{ padding: 18 }}>
            <EmptyState
              title="AI Insights not generated yet"
              message="Revenue Drivers come from the same stored run as the AI Insights section — generate it there."
            />
          </div>
        ) : null}
        {complete && !ranked.length ? (
          <div style={{ padding: "14px 18px", color: "var(--slate)", fontSize: "12.5px" }}>
            No findings for this transition.
          </div>
        ) : null}
        {complete
          ? groups.map(({ label, findings }) => (
              <div key={label}>
                {groups.length > 1 || pivot === "product" ? (
                  <div
                    style={{
                      padding: "8px 15px",
                      background: "var(--panel)",
                      fontSize: 12,
                      borderBottom: "1px solid var(--rule-2)",
                    }}
                  >
                    {/* Review F7 — product / driver group names are headers */}
                    <span className="rowhead">{label}</span>
                  </div>
                ) : null}
                {findings.map((f, i) => (
                  <DriverFinding key={f.finding_id ?? `${label}-${i}`} finding={f} defaultOpen={f === ranked[0]} />
                ))}
              </div>
            ))
          : null}
      </div>
    </div>
  );
}

/** One driver entry: `.finding` accordion over the SHARED evidence table. */
function DriverFinding({ finding, defaultOpen }: { finding: Finding; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(Boolean(defaultOpen));
  const impact = finding.impact_amt;
  const term = useTerm(`driver.${driverCode(finding)}`);

  const rawColumns = finding.evidence_columns.length
    ? finding.evidence_columns
    : Object.keys(finding.evidence_rows[0] ?? {});
  // Advisor identity folds to one "Name (SID)" column (A3 naming; the shared
  // EvidenceTable renders plain cells, so the name and SID merge as text)
  const hasAdvisor = rawColumns.includes("advisor_sid");
  const columns = hasAdvisor ? rawColumns.filter((c) => c !== "advisor_name") : rawColumns;
  const rows = useMemo(
    () =>
      hasAdvisor
        ? finding.evidence_rows.map((row) => {
            const sid = row["advisor_sid"];
            const name = row["advisor_name"];
            if (typeof sid === "string" && typeof name === "string" && name.trim()) {
              const merged: Record<string, unknown> = { ...row, advisor_sid: `${name.trim()} (${sid})` };
              delete merged["advisor_name"];
              return merged;
            }
            return row;
          })
        : finding.evidence_rows,
    [finding.evidence_rows, hasAdvisor],
  );

  return (
    <div className={`finding${open ? " open" : ""}`}>
      <div className="finding-h" onClick={() => setOpen((o) => !o)}>
        <div>
          {/* Review F7 — the driver/finding name is a header in the row */}
          <div className="finding-t rowhead">{finding.title}</div>
          <div className="finding-m">
            <NarrativeText text={finding.summary} />
          </div>
          {finding.rule_citation ? (
            <span style={{ display: "inline-flex", alignItems: "baseline", gap: 4 }}>
              {/* Review F8 — rule/document links prefixed "Source / Citation" */}
              <span style={{ fontSize: "11.5px", color: "var(--slate)" }}>Source / Citation:</span>
              <RuleCitationLine
                ruleKey={finding.rule_citation.rule_key}
                ruleName={finding.rule_citation.rule_name || finding.rule_citation.rule_code}
                citation={finding.rule_citation.citation}
              />
            </span>
          ) : null}
        </div>
        <div style={{ textAlign: "right" }}>
          <div
            className={`num ${impact !== null && impact < 0 ? "dn" : impact !== null ? "up" : ""}`}
            style={{ fontSize: 15 }}
          >
            {impact === null ? "—" : `${impact < 0 ? "▼" : "▲"} ${money(impact)}`}
          </div>
          <div className="chips">
            {/* Task 8 — REAL / DERIVED / DUMMY provenance chips removed.
                F9 — the driver tag stays: bold, never wrapped. */}
            <Chip
              variant="tag"
              title={finding.rule_citation?.statement || term?.definition || undefined}
            >
              <span style={{ whiteSpace: "nowrap", fontWeight: 700 }}>
                {finding.driver_tag || driverCode(finding)}
              </span>
            </Chip>
          </div>
        </div>
      </div>
      <div className="finding-b">
        {rows.length ? (
          // Review F3–F7 — the ONE shared evidence surface: collapsed by
          // default with a note, labelized headers, paginated, shrinks to
          // content, footer totals reconciling to the headline
          <EvidenceTable
            rows={rows}
            columns={columns}
            totals={finding.evidence_totals}
            total={finding.evidence_total}
          />
        ) : (
          <p style={{ color: "var(--slate)", fontSize: "12.5px", margin: "10px 0 0" }}>
            {finding.evidence_reason || "No evidence rows for this finding."}
          </p>
        )}
      </div>
    </div>
  );
}
