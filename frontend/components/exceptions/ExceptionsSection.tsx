"use client";

/** Round A2B 4.4 + Round 3 Task 10 (§H) / Task 3.2 — the dashboard's
 * Exceptions card.
 *
 * Two altitudes:
 *   1. FIRM VIEW (Task 3.2) — one row per RULE from GET /api/exceptions/firm:
 *      "9 of 156 managed accounts · 5.77% firm-wide · 2 advisors flagged ·
 *      $…", each with a [Drill in ›] expanding the per-rule advisor ranking
 *      (GET /api/exceptions/rule/{rule_key}, ranked by RATE, rate vs cohort
 *      median, flagged state, suppressed reason).
 *   2. WORKLIST — the per-finding rows from /api/insights/exceptions.
 *      H3: defaults to ONE advisor (the first with exceptions) so the
 *      expensive full query runs only on demand via the "All Advisors"
 *      toggle. H4: the advisor dropdown lists ONLY advisors that actually
 *      have exceptions. H2: plus a name/SID search. H1: real pagination.
 *
 * API clients live in lib/exceptionsApi.ts (this round's new file).
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import AdvisorLink from "@/components/AdvisorLink";
import { Delta } from "@/components/Num";
import EmptyState from "@/components/EmptyState";
import { Pager, usePager } from "@/components/Pager";
import RuleCitationLine from "@/components/RuleCitation";
import { useTerm } from "@/components/Term";
import { money, percent } from "@/lib/format";
import {
  type ExceptionAdvisor,
  type ExceptionsResponseFull,
  type FirmExceptionRule,
  type FirmExceptionsResponse,
  type RuleExceptionsResponse,
  type Severity,
  getExceptionAdvisors,
  getExceptionsWorklist,
  getFirmExceptions,
  getRuleExceptions,
} from "@/lib/exceptionsApi";

export interface ExceptionsSectionProps {
  fromMonth: string;
  toMonth: string;
  monthName: (id: string) => string;
}

const SEVERITIES: Severity[] = ["CRITICAL", "HIGH", "MODERATE", "LOW", "INFO"];

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

// ---------------------------------------------------------------- firm view (Task 3.2)

/** One firm-level rule row: the headline sentence plus the drill-in ranking. */
function FirmRuleRow({ rule, month }: { rule: FirmExceptionRule; month: string }) {
  const [open, setOpen] = useState(false);
  const [ranking, setRanking] = useState<RuleExceptionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const drillIn = () => {
    const next = !open;
    setOpen(next);
    if (next && !ranking && !loading) {
      setLoading(true);
      getRuleExceptions(rule.rule_key, month)
        .then((r) => setRanking(r))
        .catch((e) => setError(String((e as Error)?.message || e)))
        .finally(() => setLoading(false));
    }
  };

  const firm = rule.firm;

  // Round 10 task 3 — a rule NEITHER model can evaluate (a PRACTICE rule
  // without a numeric trigger): its own state, showing the engine's remedy
  // note. Never folded into the rate row or the "none matched" banner — a
  // rule that could not be evaluated is not a rule that found nothing.
  if (rule.model === "unsupported") {
    return (
      <div style={{ borderBottom: "1px solid var(--rule-2)", padding: "10px 18px" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          {rule.severity ? <SevChip level={rule.severity as Severity} /> : null}
          <span className="rowhead">{rule.rule_name}</span>
          <span style={{ fontSize: "12.5px" }}>
            <b style={{ color: "var(--dn, #b3261e)" }}>not evaluable</b> — no exception model applies
          </span>
        </div>
        <div style={{ fontSize: 11.5, color: "var(--slate)", marginTop: 2 }}>
          {firm.note || "This rule fits neither the cohort rate model nor the absolute firm-level threshold model."}
        </div>
      </div>
    );
  }

  // Round 8 task 4 — an absolute firm-level threshold (PRACTICE rule): there
  // is no peer cohort at firm level, so no rate/median/drill-in — the row
  // states the observed value against the threshold, fired or not.
  if (rule.model === "absolute_threshold") {
    // $0 observed is a REAL figure here (it tells the operator whether the
    // threshold discriminates) — never folded into the em-dash convention.
    const fmtAbs = (v: number | null | undefined) =>
      v == null
        ? "—"
        : firm.is_monetary
          ? v === 0
            ? "$0"
            : money(v)
          : v.toLocaleString("en-US");
    return (
      <div style={{ borderBottom: "1px solid var(--rule-2)", padding: "10px 18px" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          {rule.severity ? <SevChip level={rule.severity as Severity} /> : null}
          <span className="rowhead">{rule.rule_name}</span>
          <span style={{ fontSize: "12.5px" }}>
            {firm.error ? (
              <span style={{ color: "var(--slate)" }}>evaluation failed — {firm.error}</span>
            ) : (
              <>
                {fmtAbs(firm.observed_value)} observed vs the {fmtAbs(firm.threshold)} threshold —{" "}
                {firm.fired ? (
                  <b className="dn">fired</b>
                ) : (
                  <span>did not fire</span>
                )}
              </>
            )}
          </span>
        </div>
        <div style={{ fontSize: 11.5, color: "var(--slate)", marginTop: 2 }}>
          Absolute firm-level threshold — no peer cohort at firm level, so no rate or advisor
          breakdown applies. The threshold is editable on Rules → Exceptions.
        </div>
      </div>
    );
  }

  const isMoney = rule.config.denominator_kind === "revenue";
  const headline = [
    `${isMoney ? money(firm.affected) : firm.affected.toLocaleString("en-US")} of ${
      isMoney ? money(firm.denominator) : firm.denominator.toLocaleString("en-US")
    } ${rule.config.denominator_label}`,
    firm.rate_pct !== null ? `${percent(firm.rate_pct)} firm-wide` : null,
    `${firm.advisors_flagged.toLocaleString("en-US")} advisor${firm.advisors_flagged === 1 ? "" : "s"} flagged`,
    firm.impact_amt !== null ? money(firm.impact_amt) : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div style={{ borderBottom: "1px solid var(--rule-2)", padding: "10px 18px" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        {rule.severity ? <SevChip level={rule.severity as Severity} /> : null}
        <span className="rowhead">{rule.rule_name}</span>
        <span style={{ fontSize: "12.5px" }}>{headline}</span>
        <button type="button" className="btn sm" onClick={drillIn} aria-expanded={open}>
          {open ? "Close ‹" : "Drill in ›"}
        </button>
      </div>
      <div style={{ fontSize: 11.5, color: "var(--slate)", marginTop: 2 }}>
        {rule.config.product_scope_applied}
        {rule.cohort.median_pct !== null
          ? ` · cohort median ${percent(rule.cohort.median_pct)}`
          : ""}
        {rule.cohort.flag_threshold_pct !== null
          ? ` · flag threshold ${percent(rule.cohort.flag_threshold_pct)}`
          : ""}
        {` · ${rule.cohort.in_scope_advisors.toLocaleString("en-US")} advisors in scope`}
      </div>
      {open ? (
        loading ? (
          <p style={{ color: "var(--slate)", fontSize: "12.5px", margin: "10px 0 0" }}>Loading…</p>
        ) : error ? (
          <p style={{ color: "var(--slate)", fontSize: "12.5px", margin: "10px 0 0" }}>{error}</p>
        ) : ranking ? (
          <RuleRanking ranking={ranking} isMoney={isMoney} />
        ) : null
      ) : null}
    </div>
  );
}

/** The per-rule advisor ranking — ranked by RATE (the server's order). */
function RuleRanking({ ranking, isMoney }: { ranking: RuleExceptionsResponse; isMoney: boolean }) {
  const pager = usePager(ranking.advisors);
  const fmt = (v: number) => (isMoney ? money(v) : v.toLocaleString("en-US"));
  return (
    <div style={{ marginTop: 8, overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>Advisor</th>
            <th className="num">Affected</th>
            <th className="num">Of</th>
            <th className="num">Rate</th>
            <th className="num">Cohort Median</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {pager.rows.map((a) => (
            <tr key={a.advisor_sid}>
              <td>
                <AdvisorLink sid={a.advisor_sid} name={a.advisor_name || null} />
              </td>
              <td className="num">{fmt(a.affected)}</td>
              <td className="num">{fmt(a.denominator)}</td>
              <td className="num">
                <span className={a.flagged ? "dn" : undefined}>{percent(a.rate_pct)}</span>
              </td>
              <td className="num">
                {a.cohort_median_pct === null ? "—" : percent(a.cohort_median_pct)}
              </td>
              <td style={{ fontSize: 12 }}>
                {a.suppressed_reason ? (
                  <span style={{ color: "var(--slate)" }}>{a.suppressed_reason}</span>
                ) : a.flagged ? (
                  <span className="dn">Flagged — above the cohort threshold</span>
                ) : (
                  <span style={{ color: "var(--slate)" }}>Within cohort range</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pager {...pager} noun="advisors" />
    </div>
  );
}

function FirmView({ month, monthLabel }: { month: string; monthLabel: string }) {
  const [data, setData] = useState<FirmExceptionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    getFirmExceptions(month)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(String((e as Error)?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [month]);
  return (
    <div style={{ borderBottom: "1px solid var(--rule)" }}>
      <div className="sec-h" style={{ padding: "12px 18px 6px" }}>
        Firm view — one row per rule · {monthLabel}
      </div>
      {error ? (
        <div style={{ padding: "0 18px 12px" }}>
          <EmptyState title="Firm view failed to load" message={error} />
        </div>
      ) : !data ? (
        <p style={{ color: "var(--slate)", fontSize: "12.5px", margin: 0, padding: "0 18px 12px" }}>
          Loading…
        </p>
      ) : data.published_version == null ? (
        /* Round 8 task 2 — NO published rules: the AI cannot substitute here.
           An exception needs the policy, which needs a rule, which needs a
           document. */
        <div style={{ padding: "0 18px 14px", fontSize: "12.5px" }}>
          <b>No exception rules are active.</b> An exception measures an advisor against a policy
          your plan documents define — so it needs a published rule. Publish a rule and enable it
          as an exception on the Rules → Exceptions tab.
          <div style={{ marginTop: 6 }}>
            <Link className="btn sm" href="/documents?tab=exceptions" style={{ textDecoration: "none" }}>
              Go to Exceptions
            </Link>
          </div>
        </div>
      ) : !data.rules.length ? (
        /* Round 8 task 3 — rules exist but none is exception-enabled: looks
           like working software producing nothing, so it says so. */
        <div style={{ padding: "0 18px 14px", fontSize: "12.5px" }}>
          <b>
            {data.published_rule_count ?? 0} published rule
            {(data.published_rule_count ?? 0) === 1 ? "" : "s"}, none enabled as exceptions.
          </b>{" "}
          Enable a rule as an exception to surface advisors who fall outside it.
          <div style={{ marginTop: 6 }}>
            <Link className="btn sm" href="/documents?tab=exceptions" style={{ textDecoration: "none" }}>
              Go to Exceptions
            </Link>
          </div>
        </div>
      ) : (
        <>
          {/* Round 8 verify 4 — exceptions enabled that matched nothing is a
              RESULT, not a problem, and never dressed up as an empty state.
              Round 10 task 3 — an "unsupported" rule was NOT evaluated, so it
              can never contribute to (or hide inside) "every enabled rule
              evaluated and none matched": its presence suppresses the banner
              and its own row states the remedy. */}
          {data.rules.every(
            (r) =>
              (r.model === "absolute_threshold" && !r.firm.fired) ||
              (r.model !== "absolute_threshold" &&
                r.model !== "unsupported" &&
                r.firm.advisors_with_exceptions === 0),
          ) ? (
            <p style={{ color: "var(--slate)", fontSize: "12.5px", margin: 0, padding: "0 18px 8px" }}>
              No exceptions this period — every enabled rule evaluated and none matched.
            </p>
          ) : null}
          {data.rules.map((rule) => (
            <FirmRuleRow key={rule.rule_key} rule={rule} month={month} />
          ))}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- worklist (§H)

export default function ExceptionsSection({ fromMonth, toMonth, monthName }: ExceptionsSectionProps) {
  // "" = all; "CRITICAL,HIGH" = the combined preset; else one level
  const [severity, setSeverity] = useState("");
  // H3/H4 — advisors that actually have exceptions; default to the first
  const [advisors, setAdvisors] = useState<ExceptionAdvisor[] | null>(null);
  const [scope, setScope] = useState<"one" | "all">("one");
  const [advisor, setAdvisor] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [data, setData] = useState<ExceptionsResponseFull | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // H4 — the dropdown's population: only advisors with exceptions
  useEffect(() => {
    let cancelled = false;
    setAdvisors(null);
    setAdvisor(null);
    setScope("one");
    getExceptionAdvisors(fromMonth, toMonth)
      .then((r) => {
        if (cancelled) return;
        setAdvisors(r.advisors);
        // H3 — default to the FIRST advisor with exceptions, never the full set
        setAdvisor(r.advisors[0]?.advisor_sid ?? null);
        if (!r.advisors.length) setScope("all"); // nothing to scope to — the full (empty) set is cheap
      })
      .catch((e) => {
        if (cancelled) return;
        setAdvisors([]);
        setScope("all");
        setError(String((e as Error)?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [fromMonth, toMonth]);

  // the worklist fetch — scoped to one advisor unless "All Advisors" was asked for
  useEffect(() => {
    if (advisors === null) return; // wait for the advisor list
    if (scope === "one" && advisor === null && advisors.length) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getExceptionsWorklist(fromMonth, toMonth, {
      severity: severity || undefined,
      advisor: scope === "one" && advisor ? advisor : undefined,
    })
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
  }, [fromMonth, toMonth, severity, scope, advisor, advisors]);

  // H2 — search filters the loaded rows by name or SID (like the advisor page's)
  const rows = useMemo(() => {
    const all = data?.exceptions ?? [];
    const q = search.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (x) =>
        x.advisor_sid.toLowerCase().includes(q) ||
        (x.advisor_name || "").toLowerCase().includes(q),
    );
  }, [data, search]);

  // H1 — real pagination
  const pager = usePager(rows);

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
        <div className="ctl" style={{ flexWrap: "wrap" }}>
          {/* H3 — the one segmented toggle: one advisor vs the full set */}
          <div className="pivot" role="tablist" aria-label="Advisor scope">
            <button
              aria-selected={scope === "one"}
              onClick={() => setScope("one")}
              disabled={!advisors?.length}
            >
              One Advisor
            </button>
            <button aria-selected={scope === "all"} onClick={() => setScope("all")}>
              All Advisors
            </button>
          </div>
          {/* H4 — only advisors that actually have exceptions */}
          {scope === "one" && advisors?.length ? (
            <select
              value={advisor ?? ""}
              onChange={(e) => setAdvisor(e.target.value)}
              aria-label="Advisor"
            >
              {advisors.map((a) => (
                <option key={a.advisor_sid} value={a.advisor_sid}>
                  {a.advisor_name ? `${a.advisor_name} (${a.advisor_sid})` : a.advisor_sid} ·{" "}
                  {a.exception_count} exception{a.exception_count === 1 ? "" : "s"}
                </option>
              ))}
            </select>
          ) : null}
          {/* H2 — search bar matching the advisor page's */}
          <input
            className="filter"
            type="text"
            placeholder="Search name or SID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search exceptions by advisor"
            style={{ width: 180 }}
          />
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
        {/* Task 3.2 — the firm altitude sits above the worklist */}
        <FirmView month={toMonth} monthLabel={monthName(toMonth)} />

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
              title={
                search
                  ? "No exceptions match the search"
                  : severity
                    ? "No exceptions at this severity"
                    : "No open exceptions"
              }
              message={
                search
                  ? "No loaded exception matches that name or SID."
                  : severity
                    ? "Nothing on this transition matches the selected severity filter."
                    : "Exceptions come from each advisor's latest stored run on this transition — generate AI Insights first."
              }
            />
          </div>
        ) : null}
        {rows.length && !loading ? (
          <>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th style={{ width: "9%" }}>Severity</th>
                    <th style={{ width: "17%" }}>Advisor</th>
                    <th>Issue</th>
                    <th className="num">Impact</th>
                    {/* Review F8 — the source column carries the prefix */}
                    <th style={{ width: "22%" }}>Source / Citation</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {pager.rows.map((x, i) => (
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
            <div style={{ padding: "0 18px" }}>
              <Pager {...pager} noun="exceptions" />
            </div>
            <div className="note">
              {rows.length.toLocaleString("en-US")} exception{rows.length === 1 ? "" : "s"}
              {scope === "one" && advisor ? " for the selected advisor" : ""} across{" "}
              {data?.advisor_count ?? 0} advisor{data?.advisor_count === 1 ? "" : "s"}
              {severity ? " (filtered by severity)" : ""}
              {search ? " (filtered by search)" : ""}.
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
