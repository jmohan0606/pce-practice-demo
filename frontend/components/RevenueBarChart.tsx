"use client";

import { useId } from "react";
import type { MonthRow, Transition } from "@/lib/api";
import { arrow, money, moneyAxis, niceCeil, percent } from "@/lib/format";

/** Stacked month bars (Recurring bottom, Non-Recurring top), y-axis with
 * gridlines, SVG change arrows, and selectable arrow pills between bar tops.
 * The selected pill fills navy and drives the product table below. */
export default function RevenueBarChart({
  months,
  transitions,
  selected,
  onSelect,
}: {
  months: MonthRow[];
  transitions: Transition[];
  selected: number;
  onSelect: (index: number) => void;
}) {
  const markerId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const yMax = niceCeil(Math.max(1, ...months.map((m) => m.credited_amt)));
  const ticks = [1, 0.75, 0.5, 0.25, 0].map((f) => f * yMax);
  const n = Math.max(months.length, 1);
  const colWidth = 100 / n;

  /** Top of a month's bar as % from the top of the plot area. */
  const topPct = (m: MonthRow) => 100 - (m.credited_amt / yMax) * 100;

  return (
    <>
      <div className="legend">
        <span>
          <i style={{ background: "var(--rec)" }} />
          Recurring
        </span>
        <span>
          <i style={{ background: "var(--nrec)" }} />
          Non-Recurring
        </span>
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
              const heightPct = (m.credited_amt / yMax) * 100;
              const recShare = m.credited_amt > 0 ? (m.recurring_amt / m.credited_amt) * 100 : 0;
              return (
                <div className="mcol" key={m.month_id}>
                  <div className="bval">{money(m.credited_amt)}</div>
                  <div className="bar" style={{ height: `${heightPct}%` }}>
                    <div className="sr" style={{ height: `${recShare}%` }} />
                    <div className="sn" style={{ height: `${100 - recShare}%` }} />
                  </div>
                  <div className="mlab">
                    {m.month_name}
                    {m.is_partial ? (
                      <span style={{ color: "var(--slate-2)" }}>
                        {" "}
                        · {m.trading_days} Trading Days
                      </span>
                    ) : null}
                  </div>
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
              {transitions.map((t, i) => {
                const fromMonth = months.find((m) => m.month_id === t.from_month_id);
                const toMonth = months.find((m) => m.month_id === t.to_month_id);
                if (!fromMonth || !toMonth) return null;
                const up = t.change_amt >= 0;
                const x1 = (i + 0.5) * colWidth + 0.2 * colWidth;
                const x2 = (i + 1.5) * colWidth - 0.2 * colWidth;
                const y1 = Math.max(topPct(fromMonth) - 3, 0);
                const y2 = Math.max(topPct(toMonth) - 3, 0);
                const cy = Math.max(Math.min(y1, y2) - 10, 0);
                return (
                  <path
                    key={t.from_month_id}
                    d={`M${x1},${y1} Q${(x1 + x2) / 2},${cy} ${x2},${y2}`}
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
              const fromMonth = months.find((m) => m.month_id === t.from_month_id);
              const toMonth = months.find((m) => m.month_id === t.to_month_id);
              if (!fromMonth || !toMonth) return null;
              const up = t.change_amt >= 0;
              const pillTop = Math.max(Math.min(topPct(fromMonth), topPct(toMonth)) - 6, 0);
              return (
                <button
                  key={`pill-${t.from_month_id}`}
                  type="button"
                  className={`apill ${up ? "up" : "dn"}`}
                  aria-pressed={selected === i}
                  style={{ left: `${(i + 1) * colWidth}%`, top: `${pillTop}%` }}
                  onClick={() => onSelect(i)}
                >
                  {arrow(t.change_amt)} {money(t.change_amt)} {" "}
                  {percent(t.change_pct)}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </>
  );
}
