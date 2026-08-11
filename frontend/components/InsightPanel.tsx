"use client";

import { useState } from "react";
import type { Finding, InsightRun } from "@/lib/api";
import Chip from "@/components/Chip";
import SourceLink from "@/components/SourceLink";
import { money, percent } from "@/lib/format";

/** Renders **bold** markdown-lite the reporter emits — nothing else. */
export function Bold({ text }: { text: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return (
    <>
      {parts.map((part, i) => (i % 2 === 1 ? <b key={i}>{part}</b> : <span key={i}>{part}</span>))}
    </>
  );
}

/** The AI-generated narrative block: two paragraphs then four bullets. */
export function NarrativeBlock({ run }: { run: InsightRun }) {
  return (
    <div className="narr">
      <Chip variant="aigen">◆ AI Generated</Chip>
      {run.narrative.split(/\n\n+/).map((p, i) => (
        <p key={i} style={i === 0 ? { marginTop: 10 } : undefined}>
          <Bold text={p} />
        </p>
      ))}
      {run.bullets.length ? (
        <ul>
          {run.bullets.map((b, i) => (
            <li key={i}>
              <Bold text={b} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function cell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

function FindingRow({ finding, defaultOpen }: { finding: Finding; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(Boolean(defaultOpen));
  const impact = finding.impact_amt;
  const columns = finding.evidence_columns.length
    ? finding.evidence_columns
    : Object.keys(finding.evidence_rows[0] ?? {});
  const citation = finding.rule_citation?.citation;
  return (
    <div className={`finding${open ? " open" : ""}`}>
      <div className="finding-h" onClick={() => setOpen((o) => !o)}>
        <div>
          <div className="finding-t">{finding.title}</div>
          <div className="finding-m">{finding.summary}</div>
          <span className="evlink">View evidence ›</span>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className={`num ${impact !== null && impact < 0 ? "dn" : impact !== null ? "up" : ""}`}>
            {impact === null ? "—" : money(impact)}
          </div>
          <div className="chips">
            <Chip variant={finding.provenance === "REAL" ? "real" : "derived"}>
              {finding.provenance === "REAL" ? "Real" : "Derived"}
            </Chip>
            <Chip variant="tag">{finding.driver_tag}</Chip>
          </div>
        </div>
      </div>
      <div className="finding-b">
        {finding.rule_citation ? (
          <SourceLink>
            {finding.rule_citation.rule_name || finding.rule_citation.rule_code}
            {citation?.page_no ? ` · p. ${citation.page_no}` : ""}
            {citation?.section_path ? ` · ${citation.section_path}` : ""}
          </SourceLink>
        ) : null}
        <div className="ev">
          {finding.evidence_rows.length ? (
            <>
              <h4>Evidence</h4>
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      {columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {finding.evidence_rows.map((row, i) => (
                      <tr key={i}>
                        {columns.map((c) => (
                          <td key={c} className={typeof row[c] === "number" ? "num" : undefined}>
                            {cell(row[c])}
                          </td>
                        ))}
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
            <p style={{ color: "var(--slate)", fontSize: "12.5px", margin: 0 }}>
              {finding.evidence_reason || "No evidence rows for this finding."}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/** One transition card: tinted header (the transition's real totals) + ranked findings. */
export function TransitionCard({
  run,
  transition,
  monthLabel,
  groupBy,
}: {
  run: InsightRun;
  transition?: { change_amt: number; change_pct: number | null; txn_count: number } | null;
  monthLabel: (id: string) => string;
  groupBy?: "driver" | "product";
}) {
  const first = run.findings[0];
  const changeUp = (transition?.change_amt ?? 0) >= 0;
  // pivot regroups the SAME findings — it never refetches
  const groups = new Map<string, Finding[]>();
  for (const f of run.findings) {
    const key =
      groupBy === "product" ? f.group_id || "No product" : f.driver_tag || "Other";
    groups.set(key, [...(groups.get(key) ?? []), f]);
  }
  return (
    <div className={`tcard ${changeUp ? "p" : "n"}`}>
      <div className="tcard-h">
        <div>
          <div className="mm">
            {monthLabel(run.from_month_id)} → {monthLabel(run.to_month_id)}
          </div>
          {transition ? (
            <div className={`amt ${changeUp ? "up" : "dn"}`}>
              {changeUp ? "▲" : "▼"} {money(transition.change_amt)}{" "}
              {percent(transition.change_pct)}
            </div>
          ) : null}
        </div>
        <div style={{ fontSize: 12, color: "var(--slate)" }}>
          {transition ? `${transition.txn_count.toLocaleString()} transactions` : ""}
          {run.budget_hit ? " · query budget hit" : ""}
        </div>
      </div>
      {groupBy
        ? Array.from(groups.entries()).map(([label, findings]) => (
            <div key={label}>
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
              {findings.map((f, i) => (
                <FindingRow key={f.finding_id ?? i} finding={f} defaultOpen={f === first} />
              ))}
            </div>
          ))
        : run.findings.map((f, i) => (
            <FindingRow key={f.finding_id ?? i} finding={f} defaultOpen={i === 0} />
          ))}
      {!run.findings.length ? (
        <div style={{ padding: "14px 15px", color: "var(--slate)", fontSize: "12.5px" }}>
          No findings for this transition.
        </div>
      ) : null}
    </div>
  );
}
