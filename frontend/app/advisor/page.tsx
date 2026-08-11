"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type Advisor,
  type InsightRun,
  type MonthRow,
  type Transition,
  generateInsights,
  getAdvisors,
  getInsightStatus,
  getInsights,
  getMonths,
  getPeerRank,
  getTransitions,
} from "@/lib/api";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import { NarrativeBlock, TransitionCard } from "@/components/InsightPanel";
import { arrow, money, percent } from "@/lib/format";

/** C5 — Advisor view: KPI row + per-advisor generated insights. */
export default function AdvisorPage() {
  const [advisors, setAdvisors] = useState<Advisor[]>([]);
  const [sid, setSid] = useState<string>("");
  const [months, setMonths] = useState<MonthRow[]>([]);
  const [transitions, setTransitions] = useState<Transition[]>([]);
  const [cohortRank, setCohortRank] = useState<string | null>(null);
  const [run, setRun] = useState<InsightRun | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAdvisors()
      .then((res) => {
        const cohort = res.advisors.filter((a) => a.in_cohort);
        setAdvisors(cohort);
        if (cohort.length) setSid((current) => current || cohort[0].advisor_sid);
      })
      .catch((e) => setError(String(e?.message || e)));
  }, []);

  // KPI transition: the first between two FULL months, else the first
  const kpiTransition = useMemo(() => {
    return (
      transitions.find((t) => {
        const to = months.find((m) => m.month_id === t.to_month_id);
        return to && !to.is_partial;
      }) ?? transitions[0] ?? null
    );
  }, [transitions, months]);

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
        setTransitions(t.transitions);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [sid]);

  useEffect(() => {
    if (sid && kpiTransition) loadRun(sid, kpiTransition);
    if (sid && kpiTransition) {
      getPeerRank(sid, kpiTransition.to_month_id)
        .then((r) => setCohortRank(r.rank ? `${r.rank} of ${r.cohort_size}` : null))
        .catch(() => setCohortRank(null));
    }
  }, [sid, kpiTransition, loadRun]);

  const generate = async () => {
    if (!kpiTransition) return;
    setBusy("generating…");
    setError(null);
    try {
      const { job_id } = await generateInsights(sid, kpiTransition.from_month_id, kpiTransition.to_month_id);
      let status = await getInsightStatus(job_id);
      while (status.status === "running") {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        status = await getInsightStatus(job_id);
      }
      const failed = status.runs.find((r) => r.status === "failed");
      if (failed?.error) setError(failed.error);
      loadRun(sid, kpiTransition);
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy(null);
    }
  };

  const advisor = useMemo(() => advisors.find((a) => a.advisor_sid === sid), [advisors, sid]);
  const monthLabel = useCallback(
    (id: string) => months.find((m) => m.month_id === id)?.month_name ?? id,
    [months],
  );
  const fullMonths = months.filter((m) => !m.is_partial);

  return (
    <section>
      <PageHeader title="Advisor View" meta="Insights generated and stored per advisor" />
      <div className="card">
        <div className="card-h">
          <div>
            <h2>{advisor ? `${advisor.advisor_sid} · ${advisor.advisor_name || advisor.advisor_sid}` : "Advisor"}</h2>
            <p>Per-advisor credited revenue and generated insights.</p>
          </div>
          <div className="ctl">
            <select value={sid} onChange={(e) => setSid(e.target.value)}>
              {advisors.map((a) => (
                <option key={a.advisor_sid} value={a.advisor_sid}>
                  {a.advisor_sid} · {a.advisor_name || a.advisor_sid}
                </option>
              ))}
            </select>
            <button className="btn primary" onClick={generate} disabled={busy !== null || !kpiTransition}>
              {busy ? busy : "Generate Insights"}
            </button>
          </div>
        </div>
        <div className="card-b">
          {error ? <EmptyState title="Problem" message={error} /> : null}
          <div className="kpi">
            {fullMonths.map((m) => (
              <div key={m.month_id}>
                <div className="k">{m.month_name.toUpperCase()}</div>
                <div className="v">{money(m.credited_amt)}</div>
              </div>
            ))}
            {kpiTransition ? (
              <div>
                <div className="k">CHANGE</div>
                <div className={`v ${kpiTransition.change_amt < 0 ? "dn" : "up"}`}>
                  {arrow(kpiTransition.change_amt)} {money(kpiTransition.change_amt)}{" "}
                  {percent(kpiTransition.change_pct)}
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
              <TransitionCard run={run} transition={kpiTransition} monthLabel={monthLabel} />
            </>
          ) : run && run.status === "FAILED" ? (
            <EmptyState title="Last run failed" message={run.error ?? "See the server log."} />
          ) : !busy ? (
            <EmptyState
              title="No insights generated yet"
              message="Generate Insights runs the Miner for this advisor's latest full-month transition."
            />
          ) : (
            <EmptyState
              title="Generating…"
              message={`The Insights Miner is querying the graph for ${sid} (${kpiTransition?.from_month_id} → ${kpiTransition?.to_month_id}). This page updates when the run completes.`}
            />
          )}
        </div>
      </div>
    </section>
  );
}
