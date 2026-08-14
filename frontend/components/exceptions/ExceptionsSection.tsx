"use client";

/** Round A2B 4.4 — the dashboard's Exceptions card.
 *
 * Self-contained: fetches `/api/exceptions?from=&to=&severity=` for the
 * selected transition on mount / prop change and renders its own empty state.
 *
 * Props (the common section contract — the main thread composes this into
 * `app/page.tsx`):
 *   - `fromMonth: string`  — from-month id, e.g. "202604"
 *   - `toMonth: string`    — to-month id, e.g. "202605"
 *   - `monthName: (id: string) => string` — month id -> display name
 *
 * Behaviour:
 *   - Server sorts Critical → Info then |impact|; the severity filter
 *     refetches with the `severity` param (server-side filter): All /
 *     "Critical & High only" / each individual level.
 *   - Columns: Severity (`.sev` chip, tooltip from glossary
 *     `severity.<LEVEL>`) · Advisor (`<AdvisorLink>`) · Issue (title + slate
 *     detail) · Impact (`<Delta>`, em dash when null — an observation, not a
 *     movement) · Source (`<RuleCitation>`; source_kind="observation" rows
 *     show "Pattern — no rule matched" / "Observation" slate text, per the
 *     mockup) · a "›" link to `/advisor?sid=<sid>`.
 *
 * api.ts gap (reported, worked around locally): `getExceptions` has no
 * `severity` param and `ExceptionRow` lacks `severity`/`source_kind`, both of
 * which the backend serves — this file carries a typed local wrapper.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, type ExceptionRow, type ExceptionsResponse } from "@/lib/api";
import AdvisorLink from "@/components/AdvisorLink";
import { Delta } from "@/components/Num";
import EmptyState from "@/components/EmptyState";
import RuleCitationLine from "@/components/RuleCitation";
import { useTerm } from "@/components/Term";

export interface ExceptionsSectionProps {
  fromMonth: string;
  toMonth: string;
  monthName: (id: string) => string;
}

// ---- typed local wrapper (api.ts gap — see file JSDoc) --------------------

export type Severity = "CRITICAL" | "HIGH" | "MODERATE" | "LOW" | "INFO";
const SEVERITIES: Severity[] = ["CRITICAL", "HIGH", "MODERATE", "LOW", "INFO"];

/** The row the backend actually serves (ExceptionRow + Round A1 fields). */
export interface ExceptionRowFull extends ExceptionRow {
  severity: Severity;
  source_kind: "rule" | "observation";
}
export interface ExceptionsResponseFull extends ExceptionsResponse {
  exceptions: ExceptionRowFull[];
}

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8002";

async function getExceptionsFiltered(
  from: string,
  to: string,
  severity: string,
): Promise<ExceptionsResponseFull> {
  const params = new URLSearchParams({ from, to });
  if (severity) params.set("severity", severity);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/exceptions?${params.toString()}`, { cache: "no-store" });
  } catch {
    throw new ApiError(0, `API unreachable at ${API_BASE}`);
  }
  if (!response.ok) throw new ApiError(response.status, `${response.status} for /api/exceptions`);
  return (await response.json()) as ExceptionsResponseFull;
}

// ---- severity chip --------------------------------------------------------

const SEV_CLASS: Record<Severity, string> = {
  CRITICAL: "crit",
  HIGH: "high",
  MODERATE: "mod",
  LOW: "low",
  INFO: "info",
};

/** `.sev` chip; label and tooltip resolve from glossary `severity.<LEVEL>`. */
function SevChip({ level }: { level: Severity }) {
  const term = useTerm(`severity.${level}`);
  return (
    <span className={`sev ${SEV_CLASS[level] ?? "info"}`} title={term?.definition}>
      {term?.term ?? level}
    </span>
  );
}

/** Filter option label from the glossary where it exists. */
function SevOption({ level }: { level: Severity }) {
  const term = useTerm(`severity.${level}`);
  return <option value={level}>{term?.term ?? level}</option>;
}

export default function ExceptionsSection({ fromMonth, toMonth, monthName }: ExceptionsSectionProps) {
  // "" = all; "CRITICAL,HIGH" = the combined preset; else one level
  const [severity, setSeverity] = useState("");
  const [data, setData] = useState<ExceptionsResponseFull | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getExceptionsFiltered(fromMonth, toMonth, severity)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setData(null);
        setError(String((e as Error)?.message || e));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fromMonth, toMonth, severity]);

  const rows = data?.exceptions ?? [];

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <h2>Exceptions</h2>
          <p>
            Where the plan expects something the data does not show ·{" "}
            {monthName(fromMonth)} → {monthName(toMonth)}
          </p>
        </div>
        <div className="ctl">
          <select value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label="Severity filter">
            <option value="">All severities</option>
            <option value="CRITICAL,HIGH">Critical &amp; High only</option>
            {SEVERITIES.map((level) => (
              <SevOption key={level} level={level} />
            ))}
          </select>
        </div>
      </div>
      <div className="card-b flush" style={{ padding: 0 }}>
        {error ? (
          <div style={{ padding: 18 }}>
            <EmptyState title="Exceptions failed to load" message={error} />
          </div>
        ) : null}
        {loading ? (
          <p style={{ color: "var(--slate)", fontSize: "12.5px", margin: 0, padding: "14px 18px" }}>
            Loading…
          </p>
        ) : null}
        {data && !rows.length && !loading ? (
          <div style={{ padding: 18 }}>
            <EmptyState
              title={severity ? "No exceptions at this severity" : "No open exceptions"}
              message={
                severity
                  ? "Nothing on this transition matches the selected severity filter."
                  : "Exceptions come from each advisor's latest stored run on this transition — generate AI Insights first."
              }
            />
          </div>
        ) : null}
        {rows.length ? (
          <>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th style={{ width: "9%" }}>Severity</th>
                    <th style={{ width: "17%" }}>Advisor</th>
                    <th>Issue</th>
                    <th className="num">Impact</th>
                    <th style={{ width: "22%" }}>Source</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((x, i) => (
                    <tr key={`${x.run_id}-${i}`}>
                      <td>
                        <SevChip level={x.severity} />
                      </td>
                      <td>
                        <AdvisorLink sid={x.advisor_sid} name={x.advisor_name || null} />
                      </td>
                      <td>
                        <div>{x.issue}</div>
                        {x.detail ? (
                          <div style={{ color: "var(--slate)", fontSize: 12, marginTop: 2 }}>
                            {x.detail}
                          </div>
                        ) : null}
                      </td>
                      <td className="num">
                        {/* em dash when null — an observation, not a movement */}
                        <Delta value={x.impact_amt} />
                      </td>
                      <td>
                        {x.source_kind === "rule" && x.citation ? (
                          <RuleCitationLine
                            ruleKey={x.citation.rule_key || x.rule_key}
                            ruleName={x.citation.rule_name || x.citation.rule_code}
                            citation={x.citation.citation}
                          />
                        ) : (
                          <span style={{ fontSize: "11.5px", color: "var(--slate)" }}>
                            {x.impact_amt !== null ? "Pattern — no rule matched" : "Observation"}
                          </span>
                        )}
                      </td>
                      <td>
                        <Link
                          className="btn sm"
                          href={`/advisor?sid=${encodeURIComponent(x.advisor_sid)}`}
                          style={{ textDecoration: "none" }}
                          aria-label={`Open ${x.advisor_sid}`}
                        >
                          ›
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="note">
              Showing {rows.length} exception{rows.length === 1 ? "" : "s"} across{" "}
              {data?.advisor_count ?? 0} advisor{data?.advisor_count === 1 ? "" : "s"}
              {severity ? " (filtered by severity)" : ""}.
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
