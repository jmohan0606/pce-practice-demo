"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type ChartView,
  type DashboardChart,
  type DashboardTable,
  type DashboardTableRow,
  type MonthRow,
  getDashboardChart,
  getDashboardTable,
  getMonths,
} from "@/lib/api";
import DrilldownPanel, { useDrilldownPanel } from "@/components/DrilldownPanel";
import { Gated, useFlag } from "@/lib/flags";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import { Delta } from "@/components/Num";
import TransitionChart from "@/components/chart/TransitionChart";
import ProductChangeTable, {
  CLASS_LABELS,
  groupingOptionsForView,
} from "@/components/table/ProductChangeTable";
import ExportMenu from "@/components/table/ExportMenu";
import TopBottomModal from "@/components/table/TopBottomModal";
import InsightsSection from "@/components/insights/InsightsSection";
import DriversSection from "@/components/insights/DriversSection";
import NoncreditedSection from "@/components/noncredited/NoncreditedSection";
import ExceptionsSection from "@/components/exceptions/ExceptionsSection";

/** Round A2B — Practice Management Dashboard (Subagent A owns this file).
 *
 * Firm-level only: no advisor dropdown anywhere on this page (2.1). One
 * selected transition drives every section below the chart; the chart itself
 * refetches only when the view changes (2.5).
 */

const VIEW_OPTIONS: { value: ChartView; label: string }[] = [
  { value: "all", label: "All Products — Default" },
  { value: "split", label: "All Products — Recurring / Non-Recurring" },
  { value: "rec", label: "Recurring Only" },
  { value: "nrec", label: "Non-Recurring Only" },
];

/** The export provider's view names differ from the UI's (providers.py):
 * rec → recurring, nrec → non_recurring. */
const EXPORT_VIEW: Record<ChartView, string> = {
  all: "all",
  split: "split",
  rec: "recurring",
  nrec: "non_recurring",
};

export default function DashboardPage() {
  const [view, setView] = useState<ChartView>("all");
  const [chart, setChart] = useState<DashboardChart | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);
  const [selected, setSelected] = useState(0); // index into chart.transitions
  const [months, setMonths] = useState<MonthRow[]>([]);
  const [table, setTable] = useState<DashboardTable | null>(null);
  const [tableError, setTableError] = useState<string | null>(null);
  const [grouping, setGrouping] = useState<string>(groupingOptionsForView("all")[0]);
  const [tbRow, setTbRow] = useState<DashboardTableRow | null>(null);
  // Round G 4.2 — drill-down side panel (general component; keyed by scope)
  const { target: drillTarget, openPanel, closePanel } = useDrilldownPanel();
  // Round A2B task 7 — flag-gated affordances (OFF = the fetch/query never runs)
  const chartOn = useFlag("dashboard.chart");
  const drilldownOn = useFlag("global.drilldown");
  const topBottomOn = useFlag("dashboard.table.top_bottom");

  // month_name lookup (one fetch)
  useEffect(() => {
    getMonths()
      .then((r) => setMonths(r.months))
      .catch(() => setMonths([]));
  }, []);

  // 2.5 — the chart fetches only when the view changes; selecting a
  // transition never refetches it.
  useEffect(() => {
    if (chartOn === false) return; // flag off: the query does not run
    let cancelled = false;
    setChartError(null);
    getDashboardChart(view)
      .then((d) => {
        if (cancelled) return;
        setChart(d);
        setSelected((s) => (s < d.transitions.length ? s : 0));
      })
      .catch((e) => {
        if (!cancelled) setChartError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [view, chartOn]);

  // 3.2 — the grouping option set changes with the chart view.
  useEffect(() => {
    setGrouping(groupingOptionsForView(view)[0]);
  }, [view]);

  const activeTransition = chart?.transitions[selected] ?? null;

  // The table fetches on (view, selected transition) change.
  useEffect(() => {
    if (!activeTransition) {
      setTable(null);
      return;
    }
    let cancelled = false;
    setTableError(null);
    getDashboardTable(activeTransition.from, activeTransition.to, view)
      .then((d) => {
        if (!cancelled) setTable(d);
      })
      .catch((e) => {
        if (!cancelled) setTableError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [activeTransition, view]);

  const monthName = useCallback(
    (id: string) => months.find((m) => m.month_id === id)?.month_name || id,
    [months],
  );

  const rangeLabel = useMemo(() => {
    if (!months.length) return "";
    const first = months[0].month_name.split(" ")[0];
    return `${first}–${months[months.length - 1].month_name}`;
  }, [months]);

  const meta = [
    "Firm-level credited revenue",
    table ? `${table.total.advisor_count} advisors` : null,
    rangeLabel || null,
  ]
    .filter(Boolean)
    .join(" · ");

  const openDrill = useCallback(
    (row: DashboardTableRow) => {
      if (!activeTransition) return;
      openPanel({
        scope: "product",
        scope_key: row.group_id,
        from: activeTransition.from,
        to: activeTransition.to,
        labels: {
          title: `${row.display_prefix || ""}${row.group_name}`,
          from: monthName(activeTransition.from),
          to: monthName(activeTransition.to),
          sub: CLASS_LABELS[row.class_id],
        },
      });
    },
    [activeTransition, monthName, openPanel],
  );

  return (
    <section>
      <PageHeader title="Practice Management Dashboard" meta={meta} />

      <Gated flag="dashboard.chart">
      <div className="card">
        <div className="card-h">
          <div>
            <h2>Credited Revenue — Month over Month</h2>
            <p>
              Select an arrow to focus that transition. Every view below updates. Negative values
              are shown in parentheses.
            </p>
          </div>
          <div className="ctl">
            <select
              className="sel-strong"
              value={view}
              onChange={(e) => setView(e.target.value as ChartView)}
              aria-label="Product view"
            >
              {VIEW_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        {chartError ? (
          <EmptyState title="Data Unavailable" message={chartError} />
        ) : chart ? (
          <TransitionChart
            months={chart.months}
            transitions={chart.transitions}
            view={view}
            selected={selected}
            onSelect={setSelected}
            monthName={monthName}
          />
        ) : (
          <EmptyState title="Loading" message="Fetching monthly revenue…" />
        )}
      </div>
      </Gated>

      <Gated flag="dashboard.table">
      <div className="card">
        <div className="card-h">
          <div>
            <h2>
              What Is Driving the Change
              {activeTransition
                ? ` — ${monthName(activeTransition.from)} → ${monthName(activeTransition.to)}`
                : ""}
            </h2>
            <p>
              {activeTransition ? (
                <>
                  Product-type contributions to the change of{" "}
                  <Delta value={activeTransition.change_amt} />{" "}
                  <Delta kind="pct" value={activeTransition.change_pct} />
                  {table ? <> across {table.total.advisor_count} advisors</> : null}.
                </>
              ) : (
                "Select a transition above."
              )}
            </p>
          </div>
          <div className="ctl">
            <select
              value={grouping}
              onChange={(e) => setGrouping(e.target.value)}
              aria-label="Table grouping"
            >
              {groupingOptionsForView(view).map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
            {activeTransition ? (
              <ExportMenu
                section="dashboard_table"
                params={{
                  from: activeTransition.from,
                  to: activeTransition.to,
                  view: EXPORT_VIEW[view],
                }}
              />
            ) : null}
          </div>
        </div>
        <div className="card-b flush" style={{ overflowX: "auto" }}>
          {table && activeTransition ? (
            <ProductChangeTable
              data={table}
              grouping={grouping}
              fromLabel={monthName(activeTransition.from)}
              toLabel={monthName(activeTransition.to)}
              onDrill={drilldownOn !== false ? openDrill : undefined}
              onTopBottom={topBottomOn !== false ? setTbRow : undefined}
            />
          ) : (
            <EmptyState
              title={tableError ? "Data Unavailable" : "Loading"}
              message={tableError ?? "Fetching product contributions…"}
            />
          )}
        </div>
      </div>
      </Gated>

      {/* Round A2B Task 5 — one selected transition drives all of it; each
          section fetches independently so a slow insight fetch never blocks
          the table (composed by the main thread). */}
      {activeTransition ? (
        <>
          <Gated flag="dashboard.insights">
            <InsightsSection
              fromMonth={activeTransition.from}
              toMonth={activeTransition.to}
              monthName={monthName}
            />
          </Gated>
          <Gated flag="dashboard.drivers">
            <DriversSection
              fromMonth={activeTransition.from}
              toMonth={activeTransition.to}
              monthName={monthName}
            />
          </Gated>
          <Gated flag="dashboard.noncredited">
            <NoncreditedSection
              fromMonth={activeTransition.from}
              toMonth={activeTransition.to}
              monthName={monthName}
            />
          </Gated>
          <Gated flag="dashboard.exceptions">
            <ExceptionsSection
              fromMonth={activeTransition.from}
              toMonth={activeTransition.to}
              monthName={monthName}
            />
          </Gated>
        </>
      ) : null}

      {tbRow && activeTransition ? (
        <TopBottomModal
          row={tbRow}
          from={activeTransition.from}
          to={activeTransition.to}
          fromLabel={monthName(activeTransition.from)}
          toLabel={monthName(activeTransition.to)}
          onClose={() => setTbRow(null)}
        />
      ) : null}

      <DrilldownPanel target={drillTarget} onClose={closePanel} />
    </section>
  );
}
