"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type Advisor,
  type ExceptionsResponse,
  type Finding,
  type InsightRun,
  type MonthRow,
  type PracticeSummary,
  type RuleVersion,
  type Transition,
  type TraceSummary,
  generateInsights,
  getAdvisors,
  getExceptions,
  getInsightStatus,
  getInsights,
  getMonths,
  getPeerRank,
  getPracticeSummary,
  getRuleVersions,
  getTraceSummary,
  getTransitions,
} from "@/lib/api";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import SourceLink from "@/components/SourceLink";
import { FindingRow, NarrativeBlock, RecommendationsBlock } from "@/components/InsightPanel";
import { arrow, money, percent } from "@/lib/format";

/** AI Insights — one page, two views (Round E 6.1/6.2):
 *  The TRANSITION SELECTOR lives in this page's header — first control — and
 *  drives both views. This page never depends on state set on the Dashboard
 *  tab, and it does not duplicate the bar chart.
 *  Practice — KPI row, book-level narrative, exceptions worklist, findings.
 *  Advisor  — one advisor + the selected transition. Never fans out. */
export default function InsightsPage() {
  const [view, setView] = useState<"practice" | "advisor">("practice");
  const [advisorSid, setAdvisorSid] = useState<string>("");
  const [months, setMonths] = useState<MonthRow[]>([]);
  const [transitions, setTransitions] = useState<Transition[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [traceSummary, setTraceSummary] = useState<TraceSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getTraceSummary().then(setTraceSummary).catch(() => setTraceSummary(null));
    // 6.1: the page loads its own months + transitions — no Dashboard state
    Promise.all([getMonths("all"), getTransitions("all")])
      .then(([m, t]) => {
        setMonths(m.months);
        setTransitions(t.transitions);
        if (t.transitions.length)
          setSelected((cur) => cur || `${t.transitions[0].from_month_id}|${t.transitions[0].to_month_id}`);
      })
      .catch((e) => setError(String(e?.message || e)));
  }, []);

  const monthLabel = useCallback(
    (id: string) => months.find((m) => m.month_id === id)?.month_name ?? id,
    [months],
  );
  const transition = useMemo(
    () =>
      transitions.find((t) => `${t.from_month_id}|${t.to_month_id}` === selected) ??
      transitions[0] ??
      null,
    [transitions, selected],
  );

  const openAdvisor = useCallback((sid: string) => {
    setAdvisorSid(sid);
    setView("advisor");
  }, []);

  return (
    <section>
      <PageHeader title="AI Insights" meta="Practice-wide narrative or a single advisor — both generated from graph data">
        {/* 6.1: transition selector — the FIRST control, shows the change */}
        <select
          className="sel-strong"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          aria-label="Transition"
          style={{ fontWeight: 600, borderColor: "var(--navy-hi)", color: "var(--navy)" }}
        >
          {transitions.map((t) => (
            <option key={`${t.from_month_id}|${t.to_month_id}`} value={`${t.from_month_id}|${t.to_month_id}`}>
              {monthLabel(t.from_month_id)} → {monthLabel(t.to_month_id)}{"  "}
              {arrow(t.change_amt)} {money(t.change_amt)}
            </option>
          ))}
          {!transitions.length ? <option value="">No transitions</option> : null}
        </select>
        <div className="pivot">
          <button aria-selected={view === "practice"} onClick={() => setView("practice")}>
            Practice
          </button>
          <button aria-selected={view === "advisor"} onClick={() => setView("advisor")}>
            Advisor
          </button>
        </div>
      </PageHeader>
      {error ? <EmptyState title="Page failed to load" message={error} /> : null}
      {view === "practice" ? (
        <PracticeView
          transition={transition}
          monthLabel={monthLabel}
          traceSummary={traceSummary}
          onOpenAdvisor={openAdvisor}
        />
      ) : (
        <AdvisorView
          sid={advisorSid}
          onSidChange={setAdvisorSid}
          transition={transition}
          monthLabel={monthLabel}
          traceSummary={traceSummary}
        />
      )}
    </section>
  );
}

function projectionLine(
  traceSummary: TraceSummary | null,
  runCount: number,
  label: string,
): { text: string; hasHistory: boolean } {
  const avg = traceSummary?.projection.avg_run_cost_usd;
  const wallMs = traceSummary?.projection.avg_run_wall_ms ?? 0;
  if (avg == null) return { text: `${label} · no run history for a projection`, hasHistory: false };
  const minutes = Math.max(1, Math.round((wallMs * runCount) / 60000));
  return {
    text: `${label} · approx $${(avg * runCount).toFixed(2)}, approx ${minutes} min`,
    hasHistory: true,
  };
}

// --------------------------------------------------------------------------
// Practice view — 6.2: KPI row, book-level narrative, exceptions worklist
// --------------------------------------------------------------------------

/** No account numbers in the practice view — accounts belong to the advisor
 * view. Evidence columns that identify accounts are stripped; a finding whose
 * evidence was ONLY account-level says so instead of showing rows. */
function bookLevel(finding: Finding): Finding {
  const isAcct = (c: string) => /acct|account/i.test(c);
  const columns = (finding.evidence_columns.length
    ? finding.evidence_columns
    : Object.keys(finding.evidence_rows[0] ?? {})
  ).filter((c) => !isAcct(c));
  if (!columns.length && finding.evidence_rows.length) {
    return {
      ...finding,
      evidence_columns: [],
      evidence_rows: [],
      evidence_total: 0,
      evidence_reason: `${finding.evidence_total} account-level evidence rows — open this advisor's view for account detail.`,
    };
  }
  return {
    ...finding,
    evidence_columns: columns,
    evidence_rows: finding.evidence_rows.map((row) =>
      Object.fromEntries(Object.entries(row).filter(([k]) => !isAcct(k))),
    ),
  };
}

function PracticeView({
  transition,
  monthLabel,
  traceSummary,
  onOpenAdvisor,
}: {
  transition: Transition | null;
  monthLabel: (id: string) => string;
  traceSummary: TraceSummary | null;
  onOpenAdvisor: (sid: string) => void;
}) {
  const [versions, setVersions] = useState<RuleVersion[]>([]);
  const [version, setVersion] = useState("latest");
  const [run, setRun] = useState<InsightRun | null>(null);
  const [summary, setSummary] = useState<PracticeSummary | null>(null);
  const [exceptions, setExceptions] = useState<ExceptionsResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [pivot, setPivot] = useState<"none" | "driver" | "product">("none");
  const [error, setError] = useState<string | null>(null);
  const [cohortSize, setCohortSize] = useState<number | null>(null);

  useEffect(() => {
    getRuleVersions().then((r) => setVersions(r.versions ?? [])).catch(() => setVersions([]));
    getAdvisors()
      .then((r) => setCohortSize(r.cohort_count))
      .catch(() => setCohortSize(null));
  }, []);

  const load = useCallback(() => {
    if (!transition) return;
    const { from_month_id: from, to_month_id: to } = transition;
    getInsights("all", from, to, version).then(setRun).catch(() => setRun(null));
    getPracticeSummary(from, to).then(setSummary).catch(() => setSummary(null));
    getExceptions(from, to, version).then(setExceptions).catch(() => setExceptions(null));
  }, [transition, version]);

  useEffect(load, [load]);

  const batchRunCount = (cohortSize ?? 0) + 1;
  const projection = projectionLine(
    traceSummary,
    batchRunCount,
    `${cohortSize ?? "?"} advisors + book x 1 transition`,
  );

  // 4.2 (kept): the all-advisors batch belongs ONLY here, behind a confirm
  const regenerate = async () => {
    if (!transition) return;
    const confirmed = window.confirm(
      `Run the all-advisors batch for ${monthLabel(transition.from_month_id)} → ` +
        `${monthLabel(transition.to_month_id)}?\n\n${projection.text}\n\nThis starts ` +
        `${batchRunCount} runs (aggregate book + each advisor).`,
    );
    if (!confirmed) return;
    setBusy("starting…");
    setError(null);
    try {
      const { job_id } = await generateInsights("all", transition.from_month_id, transition.to_month_id);
      let status = await getInsightStatus(job_id);
      while (status.status === "running") {
        setBusy(`generating (${status.completed}/${status.total})…`);
        await new Promise((resolve) => setTimeout(resolve, 1500));
        status = await getInsightStatus(job_id);
      }
      load();
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy(null);
    }
  };

  const exportJson = () => {
    const blob = new Blob([JSON.stringify({ run, summary, exceptions }, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "insights.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const complete = run && run.status === "COMPLETE" ? run : null;
  const findings = useMemo(
    () => (complete ? complete.findings.map(bookLevel) : []),
    [complete],
  );
  const groups = useMemo(() => {
    const map = new Map<string, Finding[]>();
    if (pivot === "none") return map;
    for (const f of findings) {
      const key = pivot === "product" ? f.group_id || "No product" : f.driver_tag || "Other";
      map.set(key, [...(map.get(key) ?? []), f]);
    }
    return map;
  }, [findings, pivot]);

  const netFlows = summary?.flows.to;

  return (
    <>
      {/* -------- (a) Practice overview: KPI row + narrative -------- */}
      <div className="card">
        <div className="card-h">
          <div>
            <h2>Practice Overview</h2>
            <p>
              All {cohortSize ?? "…"} advisors ·{" "}
              {transition
                ? `${monthLabel(transition.from_month_id)} → ${monthLabel(transition.to_month_id)}`
                : "no transition"}
              {complete ? ` · generated ${complete.generated_at}` : ""}
            </p>
          </div>
          <div className="ctl">
            <span style={{ fontSize: "12.5px", color: "var(--slate)" }}>Rule Set</span>
            <select value={version} onChange={(e) => setVersion(e.target.value)}>
              <option value="latest">Latest</option>
              {versions.map((v) => (
                <option key={v.version_id ?? v.version_no} value={v.version_id ?? String(v.version_no)}>
                  v{v.version_no}
                  {v.published_at ? ` · ${v.published_at}` : ""}
                </option>
              ))}
            </select>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
              <button className="btn" onClick={regenerate} disabled={busy !== null || !transition}>
                {busy ? busy : "↻ Regenerate All"}
              </button>
              <span style={{ fontSize: "11px", color: projection.hasHistory ? "var(--slate)" : "var(--rule)" }}>
                {projection.text}
              </span>
            </div>
            <button className="btn" onClick={exportJson} disabled={!complete}>
              Export
            </button>
          </div>
        </div>
        <div className="card-b">
          {error ? <EmptyState title="Generation Failed" message={error} /> : null}

          {/* 6.2a — KPI row: credited revenue, AUM, net flows, open exceptions */}
          <div className="kpi">
            <div>
              <div className="k">CREDITED REVENUE</div>
              <div className="v">{summary ? money(summary.credited.to_amt) : "—"}</div>
              {summary ? (
                <div className={`sub ${summary.credited.change_amt < 0 ? "dn" : "up"}`}>
                  {arrow(summary.credited.change_amt)} {money(summary.credited.change_amt)} ·{" "}
                  {percent(summary.credited.change_pct)}
                </div>
              ) : null}
            </div>
            <div>
              <div className="k">AUM</div>
              <div className="v">{summary ? money(summary.aum.to_amt) : "—"}</div>
              {summary ? (
                <div className={`sub ${summary.aum.change_amt < 0 ? "dn" : "up"}`}>
                  {arrow(summary.aum.change_amt)} {percent(summary.aum.change_pct)}
                </div>
              ) : null}
            </div>
            <div>
              <div className="k">NET FLOWS</div>
              <div className={`v ${netFlows && netFlows.net_flows < 0 ? "dn" : ""}`}>
                {netFlows ? money(netFlows.net_flows) : "—"}
              </div>
              {netFlows ? (
                <div className="sub">
                  {money(netFlows.inflows)} in · {money(netFlows.outflows)} out
                </div>
              ) : null}
            </div>
            <div>
              <div className="k">OPEN EXCEPTIONS</div>
              <div className={`v ${exceptions && exceptions.open_count > 0 ? "dn" : ""}`}>
                {exceptions ? exceptions.open_count : "—"}
              </div>
              {exceptions && exceptions.open_count ? (
                <div className="sub">across {exceptions.advisor_count} advisors</div>
              ) : null}
            </div>
          </div>

          {/* 6.2b — narrative: one bolded sentence + bullets, book-level */}
          {complete ? (
            <>
              <NarrativeBlock run={complete} />
              <RecommendationsBlock run={complete} />
            </>
          ) : (
            <EmptyState
              title="No practice narrative for this transition yet"
              message="Regenerate All runs the Insights Miner for the aggregate book and every advisor, then writes the narrative you see here."
            />
          )}
        </div>
      </div>

      {/* -------- (c) Exceptions — the practice team's worklist -------- */}
      <div className="card">
        <div className="card-h">
          <div>
            <h2>Exceptions</h2>
            <p>Where the plan expects something the data does not show. Select a row to open that advisor.</p>
          </div>
          <span className={`chip ${exceptions?.open_count ? "neg" : "tag"}`}>
            {exceptions ? `${exceptions.open_count} Open` : "—"}
          </span>
        </div>
        <div className="card-b" style={{ padding: 0 }}>
          {exceptions && exceptions.exceptions.length ? (
            <>
              <div style={{ overflowX: "auto" }}>
                <table className="exc">
                  <thead>
                    <tr>
                      <th style={{ width: "16%" }}>Advisor</th>
                      <th>Issue</th>
                      <th className="num">Impact</th>
                      <th style={{ width: "18%" }}>Source</th>
                      <th style={{ width: "4%" }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {exceptions.exceptions.map((x, i) => {
                      const cite = x.citation?.citation;
                      return (
                        <tr key={`${x.advisor_sid}-${i}`} onClick={() => onOpenAdvisor(x.advisor_sid)} style={{ cursor: "pointer" }}>
                          <td>
                            <div style={{ fontWeight: 600 }}>{x.advisor_sid}</div>
                            {x.advisor_name ? (
                              <div style={{ color: "var(--slate)", fontSize: "12.5px" }}>{x.advisor_name}</div>
                            ) : null}
                          </td>
                          <td>
                            <div>{x.issue}</div>
                            <div style={{ color: "var(--slate)", fontSize: "12.5px", marginTop: 3 }}>{x.detail}</div>
                          </td>
                          <td className={`num ${x.impact_amt !== null && x.impact_amt < 0 ? "dn" : x.impact_amt !== null ? "up" : ""}`}>
                            {x.impact_amt === null ? "—" : money(x.impact_amt)}
                          </td>
                          <td>
                            {x.citation ? (
                              <SourceLink>
                                {x.citation.rule_name || x.citation.rule_code || x.rule_key}
                                {cite?.page_no != null ? ` · p.${cite.page_no}` : ""}
                              </SourceLink>
                            ) : (
                              <span style={{ color: "var(--slate)" }}>—</span>
                            )}
                          </td>
                          <td style={{ color: "var(--navy-hi)" }}>›</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="note">
                Impact figures are query results. An exception with no dollar impact is a position
                statement, not a revenue movement.
              </div>
            </>
          ) : (
            <div style={{ padding: 20 }}>
              <EmptyState
                title="No open exceptions"
                message={
                  exceptions
                    ? "No rule-cited findings on this transition — either the book is clean or the per-advisor runs have not been generated yet."
                    : "Exceptions come from each advisor's latest run on this transition."
                }
              />
            </div>
          )}
        </div>
      </div>

      {/* -------- What moved: book-level drivers, ranked by impact -------- */}
      {complete ? (
        <div className="card">
          <div className="card-h">
            <div>
              <h2>What Moved</h2>
              <p>Book-level drivers, ranked by impact. Account detail lives in the advisor view.</p>
            </div>
            <div className="pivot">
              <button aria-selected={pivot === "none"} onClick={() => setPivot("none")}>
                Ranked
              </button>
              <button aria-selected={pivot === "driver"} onClick={() => setPivot("driver")}>
                By Driver
              </button>
              <button aria-selected={pivot === "product"} onClick={() => setPivot("product")}>
                By Product
              </button>
            </div>
          </div>
          <div className="card-b" style={{ padding: 0 }}>
            {pivot !== "none"
              ? Array.from(groups.entries()).map(([label, fs]) => (
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
                    {fs.map((f, i) => (
                      <FindingRow key={f.finding_id ?? i} finding={f} />
                    ))}
                  </div>
                ))
              : findings.map((f, i) => (
                  <FindingRow key={f.finding_id ?? i} finding={f} defaultOpen={i === 0} />
                ))}
            {!findings.length ? (
              <div style={{ padding: "14px 15px", color: "var(--slate)", fontSize: "12.5px" }}>
                No findings for this transition.
              </div>
            ) : null}
            <div className="note">
              Findings are independent observations, not a decomposition — they are not expected to
              sum to the total change. Every figure shown is a stored query result.
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

// --------------------------------------------------------------------------
// Advisor view — one advisor + the page's selected transition (never fans out)
// --------------------------------------------------------------------------

function AdvisorView({
  sid,
  onSidChange,
  transition,
  monthLabel,
  traceSummary,
}: {
  sid: string;
  onSidChange: (sid: string) => void;
  transition: Transition | null;
  monthLabel: (id: string) => string;
  traceSummary: TraceSummary | null;
}) {
  const [advisors, setAdvisors] = useState<Advisor[]>([]);
  const [months, setMonths] = useState<MonthRow[]>([]);
  const [advisorTransitions, setAdvisorTransitions] = useState<Transition[]>([]);
  const [cohortRank, setCohortRank] = useState<string | null>(null);
  const [run, setRun] = useState<InsightRun | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAdvisors()
      .then((res) => {
        const cohort = res.advisors.filter((a) => a.in_cohort);
        setAdvisors(cohort);
        if (cohort.length && !sid) onSidChange(cohort[0].advisor_sid);
      })
      .catch((e) => setError(String(e?.message || e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadRun = useCallback((advisorSid: string, t: Transition | null) => {
    if (!t) return;
    getInsights(advisorSid, t.from_month_id, t.to_month_id)
      .then(setRun)
      .catch(() => setRun(null)); // no run yet — the empty state, never a spinner
  }, []);

  useEffect(() => {
    if (!sid) return;
    let cancelled = false;
    setError(null);
    setRun(null);
    Promise.all([getMonths(sid), getTransitions(sid)])
      .then(([m, t]) => {
        if (cancelled) return;
        setMonths(m.months);
        setAdvisorTransitions(t.transitions);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [sid]);

  useEffect(() => {
    if (sid && transition) {
      loadRun(sid, transition);
      getPeerRank(sid, transition.to_month_id)
        .then((r) => setCohortRank(r.rank ? `${r.rank} of ${r.cohort_size}` : null))
        .catch(() => setCohortRank(null));
    }
  }, [sid, transition, loadRun]);

  const projection = projectionLine(traceSummary, 1, "1 run");

  // 4.2 (kept): runs EXACTLY this advisor and the selected transition.
  const generate = async () => {
    if (!transition) return;
    setBusy("generating…");
    setError(null);
    try {
      const { job_id } = await generateInsights(sid, transition.from_month_id, transition.to_month_id);
      let status = await getInsightStatus(job_id);
      while (status.status === "running") {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        status = await getInsightStatus(job_id);
      }
      const failed = status.runs.find((r) => r.status === "failed");
      if (failed?.error) setError(failed.error);
      loadRun(sid, transition);
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy(null);
    }
  };

  const advisor = useMemo(() => advisors.find((a) => a.advisor_sid === sid), [advisors, sid]);
  // this advisor's own change on the page's selected transition
  const myTransition = useMemo(
    () =>
      transition
        ? advisorTransitions.find(
            (t) =>
              t.from_month_id === transition.from_month_id &&
              t.to_month_id === transition.to_month_id,
          ) ?? null
        : null,
    [advisorTransitions, transition],
  );
  const monthAmt = (id?: string) => months.find((m) => m.month_id === id)?.credited_amt;

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <h2>{advisor ? `${advisor.advisor_sid} · ${advisor.advisor_name || advisor.advisor_sid}` : "Advisor"}</h2>
          <p>
            Per-advisor credited revenue and generated insights
            {transition
              ? ` · ${monthLabel(transition.from_month_id)} → ${monthLabel(transition.to_month_id)}`
              : ""}
            .
          </p>
        </div>
        <div className="ctl">
          <select value={sid} onChange={(e) => onSidChange(e.target.value)}>
            {advisors.map((a) => (
              <option key={a.advisor_sid} value={a.advisor_sid}>
                {a.advisor_sid} · {a.advisor_name || a.advisor_sid}
              </option>
            ))}
          </select>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
            <button className="btn primary" onClick={generate} disabled={busy !== null || !transition}>
              {busy ? busy : "Generate Insights (this advisor only)"}
            </button>
            <span
              style={{
                fontSize: "11px",
                color: projection.hasHistory ? "var(--slate)" : "var(--rule)",
              }}
            >
              {projection.text}
            </span>
          </div>
        </div>
      </div>
      <div className="card-b">
        {error ? <EmptyState title="Problem" message={error} /> : null}
        <div className="kpi">
          {transition ? (
            <>
              <div>
                <div className="k">{monthLabel(transition.from_month_id).toUpperCase()}</div>
                <div className="v">{money(monthAmt(transition.from_month_id))}</div>
              </div>
              <div>
                <div className="k">{monthLabel(transition.to_month_id).toUpperCase()}</div>
                <div className="v">{money(monthAmt(transition.to_month_id))}</div>
              </div>
            </>
          ) : null}
          {myTransition ? (
            <div>
              <div className="k">CHANGE</div>
              <div className={`v ${myTransition.change_amt < 0 ? "dn" : "up"}`}>
                {arrow(myTransition.change_amt)} {money(myTransition.change_amt)}{" "}
                {percent(myTransition.change_pct)}
              </div>
            </div>
          ) : null}
          {cohortRank ? (
            <div>
              <div className="k">RANK IN COHORT</div>
              <div className="v">{cohortRank}</div>
            </div>
          ) : null}
          {run ? (
            <div>
              <div className="k">LAST GENERATED</div>
              <div className="v" style={{ fontSize: 15, fontWeight: 500 }}>
                {run.generated_at}
              </div>
            </div>
          ) : null}
        </div>

        {run && run.status === "COMPLETE" ? (
          <>
            <NarrativeBlock run={run} />
            <RecommendationsBlock run={run} />
            <div className="tcard" style={{ marginTop: 4 }}>
              {run.findings.map((f, i) => (
                <FindingRow key={f.finding_id ?? i} finding={f} defaultOpen={i === 0} />
              ))}
              {!run.findings.length ? (
                <div style={{ padding: "14px 15px", color: "var(--slate)", fontSize: "12.5px" }}>
                  No findings for this transition.
                </div>
              ) : null}
            </div>
          </>
        ) : run && run.status === "FAILED" ? (
          <EmptyState title="Last run failed" message={run.error ?? "See the server log."} />
        ) : !busy ? (
          <EmptyState
            title="No insights generated yet"
            message="Generate Insights runs the Miner for this advisor on the transition selected above — one run, this advisor only."
          />
        ) : (
          <EmptyState
            title="Generating…"
            message={`The Insights Miner is querying the graph for ${sid} (${transition?.from_month_id} → ${transition?.to_month_id}). This page updates when the run completes.`}
          />
        )}
      </div>
    </div>
  );
}
