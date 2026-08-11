"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type AdvisorsResponse,
  type ClassFilter,
  type MonthRow,
  type ProductContribution,
  type Transition,
  getAdvisors,
  getMonths,
  getProductContribution,
  getTransitions,
} from "@/lib/api";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import ProductTable from "@/components/ProductTable";
import RevenueBarChart from "@/components/RevenueBarChart";

const CLASS_OPTIONS: { value: ClassFilter; label: string }[] = [
  { value: "all", label: "All Products" },
  { value: "RECURRING", label: "Recurring Only" },
  { value: "NON_RECURRING", label: "Non-Recurring Only" },
];

export default function DashboardPage() {
  const [advisors, setAdvisors] = useState<AdvisorsResponse | null>(null);
  // pending filter selections vs the applied ones (Apply commits them)
  const [advisorSel, setAdvisorSel] = useState("all");
  const [classSel, setClassSel] = useState<ClassFilter>("all");
  const [applied, setApplied] = useState<{ advisor: string; cls: ClassFilter }>({
    advisor: "all",
    cls: "all",
  });

  const [months, setMonths] = useState<MonthRow[]>([]);
  const [transitions, setTransitions] = useState<Transition[]>([]);
  const [selected, setSelected] = useState(0); // default: the FIRST transition
  const [contribution, setContribution] = useState<ProductContribution | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAdvisors().then(setAdvisors).catch(() => setAdvisors(null));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all([getMonths(applied.advisor), getTransitions(applied.advisor)])
      .then(([monthsRes, transRes]) => {
        if (cancelled) return;
        setMonths(monthsRes.months);
        setTransitions(transRes.transitions);
        setSelected(0);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [applied]);

  const activeTransition = transitions[selected];

  useEffect(() => {
    if (!activeTransition) {
      setContribution(null);
      return;
    }
    let cancelled = false;
    getProductContribution(
      activeTransition.from_month_id,
      activeTransition.to_month_id,
      applied.advisor,
      applied.cls,
    )
      .then((data) => {
        if (!cancelled) setContribution(data);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [activeTransition, applied]);

  const monthName = useCallback(
    (id: string) => months.find((m) => m.month_id === id)?.month_name || id,
    [months],
  );

  const advisorLabel = useMemo(() => {
    if (applied.advisor === "all")
      return `All Advisors${advisors ? ` (${advisors.cohort_count})` : ""}`;
    const advisor = advisors?.advisors.find((a) => a.advisor_sid === applied.advisor);
    return advisor ? `${advisor.advisor_sid} · ${advisor.advisor_name || advisor.advisor_sid}` : applied.advisor;
  }, [applied.advisor, advisors]);

  const rangeLabel = useMemo(() => {
    if (!months.length) return "";
    const first = months[0].month_name.split(" ")[0];
    return `${first}–${months[months.length - 1].month_name}`;
  }, [months]);

  return (
    <section>
      <PageHeader title="Practice Management Dashboard" meta={`${advisorLabel}${rangeLabel ? ` · ${rangeLabel}` : ""}`}>
        <select value={advisorSel} onChange={(e) => setAdvisorSel(e.target.value)}>
          <option value="all">All Advisors{advisors ? ` (${advisors.cohort_count})` : ""}</option>
          {(advisors?.advisors ?? [])
            .filter((a) => a.in_cohort)
            .map((a) => (
              <option key={a.advisor_sid} value={a.advisor_sid}>
                {a.advisor_sid} · {a.advisor_name || a.advisor_sid}
              </option>
            ))}
        </select>
        <select value={classSel} onChange={(e) => setClassSel(e.target.value as ClassFilter)}>
          {CLASS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <button className="btn primary" onClick={() => setApplied({ advisor: advisorSel, cls: classSel })}>
          Apply
        </button>
      </PageHeader>

      <div className="card">
        <div className="card-h">
          <div>
            <h2>Credited Revenue — Month over Month</h2>
            <p>
              Arrows show the change between consecutive months. Select an arrow to load the views
              below. Negative values are shown in parentheses.
            </p>
          </div>
        </div>
        {error ? (
          <EmptyState title="Data Unavailable" message={error} />
        ) : months.length ? (
          <RevenueBarChart
            months={months}
            transitions={transitions}
            selected={selected}
            onSelect={setSelected}
          />
        ) : (
          <EmptyState title="Loading" message="Fetching monthly revenue…" />
        )}
      </div>

      <div className="card">
        <div className="card-h">
          <div>
            <h2>
              Product Contribution
              {activeTransition
                ? ` — ${monthName(activeTransition.from_month_id)} → ${monthName(activeTransition.to_month_id)}`
                : ""}
            </h2>
            <p>
              {activeTransition
                ? `Share is of the ${monthName(activeTransition.to_month_id)} total. Every figure is a query result.`
                : "Select a transition above."}
            </p>
          </div>
        </div>
        <div className="card-b flush">
          {contribution && activeTransition ? (
            <>
              <ProductTable
                data={contribution}
                fromLabel={monthName(contribution.from_month_id)}
                toLabel={monthName(contribution.to_month_id)}
              />
              <div className="note">
                Credited revenue is the sum of post-split credited amount where the reason code is
                empty. Non-credited rows are held in the graph and available to the agent, but are
                not included here.
              </div>
            </>
          ) : (
            <EmptyState
              title={error ? "Data Unavailable" : "Loading"}
              message={error ?? "Fetching product contribution…"}
            />
          )}
        </div>
      </div>
    </section>
  );
}
