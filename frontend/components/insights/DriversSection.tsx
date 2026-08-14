"use client";

/** Round A2B 4.2 — the dashboard's Drivers card.
 *
 * Self-contained: fetches the SAME stored run as the AI Insights section but
 * independently (no shared loading gate), and renders its own empty state.
 *
 * Props (the common section contract — the main thread composes this into
 * `app/page.tsx`):
 *   - `fromMonth: string`  — from-month id, e.g. "202604"
 *   - `toMonth: string`    — to-month id, e.g. "202605"
 *   - `monthName: (id: string) => string` — month id -> display name
 *
 * Behaviour:
 *   - Findings ranked by |impact_amt|. "By Driver" / "By Product" pivot
 *     regroups CLIENT-SIDE without refetching: By Driver groups on
 *     driver_code; By Product groups on the finding's product group where
 *     determinable (finding.group_id, else group_id/group_name on evidence
 *     rows), else an honest "No product attribution" group.
 *   - Each entry is a `.finding` accordion: title, `<DriverChip>` (definition
 *     from the matched rule's statement or the glossary), rule citation line,
 *     impact `<Delta>` with provenance chips (Dummy whenever any evidence row
 *     has data_source='DUMMY'); expands to the evidence table with advisor
 *     columns rendered through `<AdvisorLink>` and "Showing N of M" honesty
 *     from evidence_total.
 */

import { useMemo, useState } from "react";
import type { Finding } from "@/lib/api";
import AdvisorLink from "@/components/AdvisorLink";
import Chip from "@/components/Chip";
import EmptyState from "@/components/EmptyState";
import { Money, NarrativeText } from "@/components/Num";
import RuleCitationLine from "@/components/RuleCitation";
import { money } from "@/lib/format";
import { FindingDriverChip } from "@/components/insights/InsightsSection";
import { driverCode, rankFindings, useInsightRun } from "@/components/insights/shared";

export interface DriversSectionProps {
  fromMonth: string;
  toMonth: string;
  monthName: (id: string) => string;
}

type Pivot = "driver" | "product";

/** The product group a finding belongs to, where determinable. */
function productGroup(f: Finding): string | null {
  if (f.group_id) return f.group_id;
  for (const row of f.evidence_rows) {
    const g = row["group_name"] ?? row["group_id"];
    if (typeof g === "string" && g) return g;
  }
  return null;
}

export default function DriversSection({ fromMonth, toMonth, monthName }: DriversSectionProps) {
  const { run, notGenerated, error, loading } = useInsightRun(fromMonth, toMonth);
  const [pivot, setPivot] = useState<Pivot>("driver");

  const complete = run && run.status === "COMPLETE" ? run : null;
  const ranked = useMemo(() => (complete ? rankFindings(complete.findings) : []), [complete]);

  // pivot regroups the SAME ranked findings — it never refetches
  const groups = useMemo(() => {
    const map = new Map<string, { label: string; findings: Finding[] }>();
    for (const f of ranked) {
      const key =
        pivot === "driver"
          ? driverCode(f)
          : productGroup(f) ?? "No product attribution";
      const label =
        pivot === "driver" ? f.driver_tag || key : productGroup(f) ?? "No product attribution";
      const entry = map.get(key) ?? { label, findings: [] };
      entry.findings.push(f);
      map.set(key, entry);
    }
    return Array.from(map.values());
  }, [ranked, pivot]);

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <h2>Drivers</h2>
          <p>
            What moved the number, ranked by impact · {monthName(fromMonth)} → {monthName(toMonth)}
          </p>
        </div>
        <div className="pivot">
          <button aria-selected={pivot === "driver"} onClick={() => setPivot("driver")}>
            By Driver
          </button>
          <button aria-selected={pivot === "product"} onClick={() => setPivot("product")}>
            By Product
          </button>
        </div>
      </div>
      <div className="card-b flush" style={{ padding: 0 }}>
        {error ? (
          <div style={{ padding: 18 }}>
            <EmptyState title="Drivers failed to load" message={error} />
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
              message="Drivers come from the same stored run as the AI Insights section — generate it there."
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
                      fontWeight: 600,
                      fontSize: 12,
                      color: "var(--slate)",
                      borderBottom: "1px solid var(--rule-2)",
                    }}
                  >
                    {label}
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

function cellText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString("en-US") : value.toFixed(2);
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

const MONEY_COL = /amt|amount|value|revenue|credited/i;

/** One driver entry: `.finding` accordion with the evidence table. */
function DriverFinding({ finding, defaultOpen }: { finding: Finding; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(Boolean(defaultOpen));
  const impact = finding.impact_amt;
  const hasDummy = finding.evidence_rows.some((r) => r["data_source"] === "DUMMY");

  const rawColumns = finding.evidence_columns.length
    ? finding.evidence_columns
    : Object.keys(finding.evidence_rows[0] ?? {});
  // advisor_sid renders as one <AdvisorLink> cell; the name column folds into it
  const hasAdvisor = rawColumns.includes("advisor_sid");
  const columns = hasAdvisor ? rawColumns.filter((c) => c !== "advisor_name") : rawColumns;

  return (
    <div className={`finding${open ? " open" : ""}`}>
      <div className="finding-h" onClick={() => setOpen((o) => !o)}>
        <div>
          <div className="finding-t">{finding.title}</div>
          <div className="finding-m">
            <NarrativeText text={finding.summary} />
          </div>
          {finding.rule_citation ? (
            <RuleCitationLine
              ruleKey={finding.rule_citation.rule_key}
              ruleName={finding.rule_citation.rule_name || finding.rule_citation.rule_code}
              citation={finding.rule_citation.citation}
            />
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
            <Chip variant={finding.provenance === "REAL" ? "real" : "derived"}>
              {finding.provenance === "REAL" ? "Real" : "Derived"}
            </Chip>
            {hasDummy ? <Chip variant="dummy">Dummy Data</Chip> : null}
            <FindingDriverChip
              code={driverCode(finding)}
              label={finding.driver_tag}
              statement={finding.rule_citation?.statement ?? null}
            />
          </div>
        </div>
      </div>
      <div className="finding-b">
        {finding.evidence_rows.length ? (
          <>
            <div style={{ overflowX: "auto" }}>
              <table style={{ marginTop: 10 }}>
                <thead>
                  <tr>
                    {columns.map((c) => (
                      <th key={c} className={MONEY_COL.test(c) ? "num" : undefined}>
                        {c === "advisor_sid" ? "Advisor" : c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {finding.evidence_rows.map((row, i) => (
                    <tr key={i}>
                      {columns.map((c) => {
                        if (c === "advisor_sid" && typeof row["advisor_sid"] === "string") {
                          return (
                            <td key={c}>
                              <AdvisorLink
                                sid={row["advisor_sid"] as string}
                                name={(row["advisor_name"] as string | undefined) ?? null}
                              />
                            </td>
                          );
                        }
                        if (MONEY_COL.test(c) && typeof row[c] === "number") {
                          return (
                            <td key={c} className="num">
                              <Money value={row[c] as number} />
                            </td>
                          );
                        }
                        return (
                          <td key={c} className={typeof row[c] === "number" ? "num" : undefined}>
                            {cellText(row[c])}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {finding.evidence_total > finding.evidence_rows.length ? (
              <div className="ev-more">
                Showing {finding.evidence_rows.length} of {finding.evidence_total}
              </div>
            ) : null}
          </>
        ) : (
          <p style={{ color: "var(--slate)", fontSize: "12.5px", margin: "10px 0 0" }}>
            {finding.evidence_reason || "No evidence rows for this finding."}
          </p>
        )}
      </div>
    </div>
  );
}
