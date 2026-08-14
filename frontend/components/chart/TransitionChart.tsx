"use client";

import { useId } from "react";
import { useTerm } from "@/components/Term";
import { arrow, money, moneyAxis, niceCeil, percent } from "@/lib/format";

/** Round A2B Task 2 — the transition bar chart.
 *
 * SHARED prop contract with the advisor page (Subagent C reuses this
 * component scoped to one advisor) — do not change the interface without
 * coordinating both pages.
 *
 * Per-view bar colours each with their own legend (mockup VIEWS object):
 * all → single --all bar; split → stacked recurring (bottom) / non-recurring
 * (top); rec → recurring only; nrec → non-recurring only. Bar heights scale
 * to the max PLOTTED value in the current view, and the value label above
 * each bar is the view's plotted amount, not always the grand total.
 * The view dropdown lives OUTSIDE this component (the card header).
 */
export interface TransitionChartProps {
  months: {
    month_id: string;
    credited_amt: number;
    recurring_amt: number;
    non_recurring_amt: number;
    aum: number | null;
  }[];
  transitions: {
    from: string;
    to: string;
    change_amt: number;
    change_pct: number | null;
    direction: "up" | "down";
  }[];
  view: "all" | "split" | "rec" | "nrec";
  selected: number; // index into transitions
  onSelect: (index: number) => void;
  monthName: (monthId: string) => string; // "202604" -> "Apr 2026"
}

type ChartMonth = TransitionChartProps["months"][number];

interface ViewConfig {
  /** [css colour, label] pairs — the legend INSIDE the component. */
  legend: [string, string][];
  /** Bottom-up stack segments for one month's bar. */
  segments: (m: ChartMonth) => { cls: string; amt: number }[];
}

const VIEW_CONFIG: Record<TransitionChartProps["view"], ViewConfig> = {
  all: {
    legend: [["var(--all)", "All Products"]],
    segments: (m) => [{ cls: "sa", amt: m.credited_amt }],
  },
  split: {
    legend: [
      ["var(--rec)", "Recurring"],
      ["var(--nrec)", "Non-Recurring"],
    ],
    // column-reverse container: first child renders at the bottom (recurring)
    segments: (m) => [
      { cls: "sr", amt: m.recurring_amt },
      { cls: "sn", amt: m.non_recurring_amt },
    ],
  },
  rec: {
    legend: [["var(--rec)", "Recurring"]],
    segments: (m) => [{ cls: "sr", amt: m.recurring_amt }],
  },
  nrec: {
    legend: [["var(--nrec)", "Non-Recurring"]],
    segments: (m) => [{ cls: "sn", amt: m.non_recurring_amt }],
  },
};

export default function TransitionChart({
  months,
  transitions,
  view,
  selected,
  onSelect,
  monthName,
}: TransitionChartProps) {
  const markerId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const aumTerm = useTerm("metric.aum");
  const config = VIEW_CONFIG[view];

  /** The view's plotted amount for a month — the bar height AND its label. */
  const plotted = (m: ChartMonth) =>
    config.segments(m).reduce((sum, s) => sum + s.amt, 0);

  const yMax = niceCeil(Math.max(1, ...months.map(plotted)));
  const ticks = [1, 0.75, 0.5, 0.25, 0].map((f) => f * yMax);
  const n = Math.max(months.length, 1);
  const colWidth = 100 / n;
  const monthIndex = new Map(months.map((m, i) => [m.month_id, i]));

  /** Top of a month's bar as % from the top of the plot area. */
  const topPct = (m: ChartMonth) => 100 - (plotted(m) / yMax) * 100;

  return (
    <>
      <div className="legend">
        {config.legend.map(([colour, label]) => (
          <span key={label}>
            <i style={{ background: colour }} />
            {label}
          </span>
        ))}
      </div>
      <div className="chartwrap">
        <div className="yax">
          {ticks.map((t) => (
            <span key={t}>{moneyAxis(t)}</span>
          ))}
        </div>
        <div className="plot">
          <div className="grid">
            <div />
            <div />
            <div />
            <div />
            <div />
          </div>
          <div className="bars">
            {months.map((m) => {
              const total = plotted(m);
              const heightPct = (total / yMax) * 100;
              return (
                <div className="mcol" key={m.month_id}>
                  <div className="bval">{money(total)}</div>
                  <div className="baum" title={aumTerm?.definition}>
                    AUM {m.aum === null ? "—" : moneyAxis(m.aum)}
                  </div>
                  <div className="bar" style={{ height: `${heightPct}%` }}>
                    {config.segments(m).map((s) => (
                      <div
                        key={s.cls}
                        className={s.cls}
                        style={{ height: `${total > 0 ? (s.amt / total) * 100 : 0}%` }}
                      />
                    ))}
                  </div>
                  <div className="mlab">{monthName(m.month_id)}</div>
                </div>
              );
            })}
          </div>
          <div className="arrows">
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <defs>
                <marker
                  id={`${markerId}-g`}
                  markerWidth="9"
                  markerHeight="9"
                  refX="7"
                  refY="4.5"
                  orient="auto"
                >
                  <path d="M0,0 L9,4.5 L0,9 z" fill="#157F4C" />
                </marker>
                <marker
                  id={`${markerId}-r`}
                  markerWidth="9"
                  markerHeight="9"
                  refX="7"
                  refY="4.5"
                  orient="auto"
                >
                  <path d="M0,0 L9,4.5 L0,9 z" fill="#B3261E" />
                </marker>
              </defs>
              {transitions.map((t) => {
                const fromIdx = monthIndex.get(t.from);
                const toIdx = monthIndex.get(t.to);
                if (fromIdx === undefined || toIdx === undefined) return null;
                const up = t.change_amt >= 0;
                const x1 = (fromIdx + 0.5) * colWidth + 0.2 * colWidth;
                const x2 = (toIdx + 0.5) * colWidth - 0.2 * colWidth;
                const y1 = Math.max(topPct(months[fromIdx]) - 3, 0);
                const y2 = Math.max(topPct(months[toIdx]) - 3, 0);
                return (
                  <path
                    key={`${t.from}-${t.to}`}
                    d={`M${x1},${y1} L${x2},${y2}`}
                    stroke={up ? "#157F4C" : "#B3261E"}
                    strokeWidth="2.5"
                    fill="none"
                    vectorEffect="non-scaling-stroke"
                    markerEnd={`url(#${markerId}-${up ? "g" : "r"})`}
                  />
                );
              })}
            </svg>
            {transitions.map((t, i) => {
              const fromIdx = monthIndex.get(t.from);
              const toIdx = monthIndex.get(t.to);
              if (fromIdx === undefined || toIdx === undefined) return null;
              const up = t.change_amt >= 0;
              const pillTop = Math.max(
                Math.min(topPct(months[fromIdx]), topPct(months[toIdx])) - 6,
                0,
              );
              return (
                <button
                  key={`pill-${t.from}-${t.to}`}
                  type="button"
                  className={`apill ${up ? "up" : "dn"}`}
                  aria-pressed={selected === i}
                  title={`${monthName(t.from)} to ${monthName(t.to)}`}
                  style={{ left: `${((fromIdx + toIdx) / 2 + 0.5) * colWidth}%`, top: `${pillTop}%` }}
                  onClick={() => onSelect(i)}
                >
                  {arrow(t.change_amt)} {money(t.change_amt)} {percent(t.change_pct)}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </>
  );
}
