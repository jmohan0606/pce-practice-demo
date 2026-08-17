"use client";

import type { ChartView, DashboardTable, DashboardTableRow } from "@/lib/api";
import Term from "@/components/Term";
import { Delta, Money, Pct } from "@/components/Num";
import { arrow, money } from "@/lib/format";

/** Round A2B Task 3 — the expanded product table.
 *
 * Data is GET /api/dashboard/table: flat rows + a "__TOTAL__" totals row
 * (distinct-account totals) + column definitions from the glossary. No
 * "Other" roll-up — every server row renders, including Unmapped Products.
 * The Δ Revenue cell is a real button opening the Round G drill-down panel.
 */

/** 3.2 — the grouping dropdown's option set follows the chart view. */
export function groupingOptionsForView(view: ChartView): string[] {
  switch (view) {
    case "all":
      return ["No grouping"];
    case "split":
      return ["Group by Revenue Class", "No grouping"];
    case "rec":
      return ["Recurring products only"];
    default:
      return ["Non-Recurring products only"];
  }
}

export const CLASS_LABELS: Record<string, string> = {
  RECURRING: "Recurring",
  NON_RECURRING: "Non-Recurring",
};

function ProductRow({
  row,
  onDrill,
  onTopBottom,
}: {
  row: DashboardTableRow;
  /** Absent when the drill-down feature flag is off — renders plain text. */
  onDrill?: (row: DashboardTableRow) => void;
  /** Absent when the top/bottom sub-feature flag is off — button hidden. */
  onTopBottom?: (row: DashboardTableRow) => void;
}) {
  return (
    <tr>
      <td>
        {/* Review C2/C4 — bold product name, prefix joined with an en dash
            ("TWHS – Structured Products", never "TWHSStructured Products") */}
        {row.display_prefix ? <span className="pfx">{row.display_prefix} – </span> : null}
        <span className="rowhead">{row.group_name}</span>
      </td>
      <td className="num grpline">{row.from_account_count.toLocaleString("en-US")}</td>
      <td className="num">{row.from_trade_count.toLocaleString("en-US")}</td>
      <td className="num">
        <Money value={row.from_amt} />
      </td>
      <td className="num grpline">{row.to_account_count.toLocaleString("en-US")}</td>
      <td className="num">{row.to_trade_count.toLocaleString("en-US")}</td>
      <td className="num">
        <Money value={row.to_amt} />
      </td>
      <td className="num grpline">
        <Delta kind="count" value={row.account_delta} />
      </td>
      <td className="num">
        <Delta kind="count" value={row.trade_delta} />
      </td>
      <td className="num">
        {onDrill ? (
          <button
            type="button"
            className={`drill ${row.direction === "down" ? "dn" : "up"}`}
            onClick={() => onDrill(row)}
          >
            {arrow(row.change_amt)} {money(row.change_amt)}
          </button>
        ) : (
          <Delta value={row.change_amt} />
        )}
      </td>
      <td className="num share">
        <Pct value={row.share_pct} />
      </td>
      <td>
        {onTopBottom ? (
          <button type="button" className="btn sm" onClick={() => onTopBottom(row)}>
            ▲▼ Top / Bottom
          </button>
        ) : (
          "—"
        )}
      </td>
    </tr>
  );
}

export default function ProductChangeTable({
  data,
  grouping,
  fromLabel,
  toLabel,
  onDrill,
  onTopBottom,
}: {
  data: DashboardTable;
  /** The selected option from groupingOptionsForView(view). */
  grouping: string;
  fromLabel: string;
  toLabel: string;
  onDrill?: (row: DashboardTableRow) => void;
  onTopBottom?: (row: DashboardTableRow) => void;
}) {
  const total = data.total;

  // "Group by Revenue Class" (split view only): tr.sect class-header rows,
  // preserving server row order within each class. Anything else is flat.
  const byClass = grouping === "Group by Revenue Class";
  const classIds = byClass
    ? Array.from(new Set(data.rows.map((r) => r.class_id)))
    : [];

  const bodyRows = (rows: DashboardTableRow[]) =>
    rows.map((row) => (
      <ProductRow key={row.group_id} row={row} onDrill={onDrill} onTopBottom={onTopBottom} />
    ));

  return (
    <>
      <table>
        <thead>
          {/* Review C1 — every header renders in the SAME font/size: the
              rowSpan'd headers carry the same .colhead class (12px) the
              sub-row headers already had. C3 — Accts renamed Accounts. */}
          <tr>
            <th rowSpan={2} className="colhead" style={{ width: "19%" }}>
              Product Type
            </th>
            <th className="grp colhead" colSpan={3}>
              {fromLabel}
            </th>
            <th className="grp colhead" colSpan={3}>
              {toLabel}
            </th>
            <th className="grp colhead" colSpan={3}>
              Difference
            </th>
            <th rowSpan={2} className="num colhead">
              <Term code="metric.share">% Share</Term>
            </th>
            <th rowSpan={2} className="colhead" style={{ width: "9%" }}>
              Advisors
            </th>
          </tr>
          <tr>
            <th className="num grpline colhead">
              <Term code="metric.accounts">Accounts</Term>
            </th>
            <th className="num colhead">
              <Term code="metric.trades">Trades</Term>
            </th>
            <th className="num colhead">
              <Term code="metric.revenue">Revenue</Term>
            </th>
            <th className="num grpline colhead">
              <Term code="metric.accounts">Accounts</Term>
            </th>
            <th className="num colhead">
              <Term code="metric.trades">Trades</Term>
            </th>
            <th className="num colhead">
              <Term code="metric.revenue">Revenue</Term>
            </th>
            <th className="num grpline colhead">Δ Accounts</th>
            <th className="num colhead">Δ Trades</th>
            <th className="num colhead">Δ Revenue</th>
          </tr>
        </thead>
        <tbody>
          {byClass
            ? classIds.map((classId) => (
                <FragmentRows
                  key={classId}
                  label={CLASS_LABELS[classId] ?? classId}
                  rows={bodyRows(data.rows.filter((r) => r.class_id === classId))}
                />
              ))
            : bodyRows(data.rows)}
          <tr className="tot">
            <td>Total (all product types)</td>
            <td className="num grpline">{total.from_account_count.toLocaleString("en-US")}</td>
            <td className="num">{total.from_trade_count.toLocaleString("en-US")}</td>
            <td className="num">
              <Money value={total.from_amt} />
            </td>
            <td className="num grpline">{total.to_account_count.toLocaleString("en-US")}</td>
            <td className="num">{total.to_trade_count.toLocaleString("en-US")}</td>
            <td className="num">
              <Money value={total.to_amt} />
            </td>
            <td className="num grpline">
              <Delta kind="count" value={total.account_delta} />
            </td>
            <td className="num">
              <Delta kind="count" value={total.trade_delta} />
            </td>
            <td className="num">
              <Delta value={total.change_amt} />
            </td>
            <td className="num">
              <Pct value={total.share_pct} />
            </td>
            <td>—</td>
          </tr>
        </tbody>
      </table>
      <div className="note">
        {/* Column definitions from the glossary via the API payload — one
            source, never hardcoded. The share definition carries the
            sums-to-100-within-the-view note. */}
        {["accounts", "trades", "revenue", "share"]
          .map((key) => data.definitions[key])
          .filter(Boolean)
          .join(" ")}
      </div>
    </>
  );
}

/** A class-header section row plus its product rows (split view grouping). */
function FragmentRows({ label, rows }: { label: string; rows: React.ReactNode }) {
  return (
    <>
      <tr className="sect">
        <td colSpan={12}>{label}</td>
      </tr>
      {rows}
    </>
  );
}
