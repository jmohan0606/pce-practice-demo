"use client";

import { useEffect, useMemo, useState } from "react";
import {
  type Advisor,
  type MonthRow,
  type Transition,
  getAdvisors,
  getMonths,
  getTransitions,
} from "@/lib/api";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import { arrow, money, percent } from "@/lib/format";

/** Advisor view — Round B renders the KPIs only; Round C fills the insights.
 * The only filter here is the single advisor selector. */
export default function AdvisorPage() {
  const [advisors, setAdvisors] = useState<Advisor[]>([]);
  const [sid, setSid] = useState<string>("");
  const [months, setMonths] = useState<MonthRow[]>([]);
  const [transitions, setTransitions] = useState<Transition[]>([]);
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

  useEffect(() => {
    if (!sid) return;
    let cancelled = false;
    setError(null);
    Promise.all([getMonths(sid), getTransitions(sid)])
      .then(([monthsRes, transRes]) => {
        if (cancelled) return;
        setMonths(monthsRes.months);
        setTransitions(transRes.transitions);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [sid]);

  const advisor = useMemo(() => advisors.find((a) => a.advisor_sid === sid), [advisors, sid]);
  // KPI change: the first transition between two FULL months, else the first transition
  const change = transitions.find((t) => {
    const to = months.find((m) => m.month_id === t.to_month_id);
    return to && !to.is_partial;
  }) ?? transitions[0];

  return (
    <section>
      <PageHeader title="Advisor View" meta="Insights generated and stored per advisor" />
      <div className="card">
        <div className="card-h">
          <div>
            <h2>{advisor ? `${advisor.advisor_sid} · ${advisor.advisor_name || advisor.advisor_sid}` : "Advisor"}</h2>
            <p>Credited revenue by month for this advisor.</p>
          </div>
          <div className="ctl">
            <select value={sid} onChange={(e) => setSid(e.target.value)}>
              {advisors.map((a) => (
                <option key={a.advisor_sid} value={a.advisor_sid}>
                  {a.advisor_sid} · {a.advisor_name || a.advisor_sid}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="card-b">
          {error ? (
            <EmptyState title="Data Unavailable" message={error} />
          ) : (
            <>
              <div className="kpi">
                {months.map((m) => (
                  <div key={m.month_id}>
                    <div className="k">
                      {m.month_name.toUpperCase()}
                      {m.is_partial ? " · PARTIAL" : ""}
                    </div>
                    <div className="v">{money(m.credited_amt)}</div>
                  </div>
                ))}
                {change ? (
                  <div>
                    <div className="k">CHANGE</div>
                    <div className={`v ${change.change_amt < 0 ? "dn" : "up"}`}>
                      {arrow(change.change_amt)} {money(change.change_amt)}{" "}
                      {percent(change.change_pct)}
                    </div>
                  </div>
                ) : null}
              </div>
              <EmptyState
                title="No Insights Generated Yet"
                message="Per-advisor insight generation arrives in Round C."
              />
            </>
          )}
        </div>
      </div>
    </section>
  );
}
