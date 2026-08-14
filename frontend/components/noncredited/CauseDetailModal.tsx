"use client";

/** Round A2B 4.3 — the per-cause 9X detail modal.
 *
 * One modal, four DELIBERATELY DIFFERENT table shapes (spec 4.3 — they are
 * not interchangeable), driven by a per-cause column spec over the real
 * `/api/noncredited/detail/{cause}` row fields:
 *
 *   household (9H)  — per-advisor; the column that matters is
 *                     `households_within_10k_of_threshold`, rendered as
 *                     "N within $10k" under "Closest to Threshold".
 *   inheritance (9G)— receiving advisor / from advisor (Departed chip when
 *                     `from_advisor_departed`) / `months_since_transfer`.
 *   discount (9D)   — the expected-vs-recorded gap: `grid_points_expected`
 *                     vs `grid_points_recorded`, recorded highlighted red
 *                     (`dn`) wherever recorded < expected.
 *   eligibility (9E)— grouped BY PRODUCT, no advisor column at all (a plan
 *                     definition, not advisor behaviour), with the server's
 *                     per-product `reason`.
 *
 * Props:
 *   - `detail: NoncreditedDetail` — the fetched per-cause payload
 *   - `summaryRow?: NoncreditedRow | null` — this cause's summary-table row,
 *     used for the sub-line (accounts · value not credited)
 *   - `monthLabel: string` — display name of the month shown
 *   - `onClose: () => void`
 *
 * Advisor cells are `<AdvisorLink>`; a totals row renders only when the
 * server provides one; the `.note` foot renders only from server note fields
 * (description / note) — nothing invented.
 */

import { type ReactNode, useEffect } from "react";
import type { NoncreditedDetail, NoncreditedRow } from "@/lib/api";
import AdvisorLink from "@/components/AdvisorLink";
import Chip from "@/components/Chip";
import { Money } from "@/components/Num";
import { useTerm } from "@/components/Term";

export interface CauseDetailModalProps {
  detail: NoncreditedDetail;
  summaryRow?: NoncreditedRow | null;
  monthLabel: string;
  onClose: () => void;
}

type Row = Record<string, unknown>;

interface Col {
  header: string;
  num?: boolean;
  render: (row: Row) => ReactNode;
}

const n = (v: unknown): number | null => (typeof v === "number" ? v : null);
const s = (v: unknown): string => (typeof v === "string" ? v : "");
const int = (v: unknown): string => (typeof v === "number" ? v.toLocaleString("en-US") : "—");

function advisorCell(row: Row, sidKey = "advisor_sid", nameKey = "advisor_name"): ReactNode {
  const sid = s(row[sidKey]);
  return sid ? <AdvisorLink sid={sid} name={s(row[nameKey]) || null} /> : "—";
}

/** The four shapes. Keys are the real API row fields (verified live). */
const CAUSE_COLUMNS: Record<string, Col[]> = {
  household: [
    { header: "Advisor", render: (r) => advisorCell(r) },
    { header: "Households", num: true, render: (r) => int(r["household_count"]) },
    { header: "Accounts", num: true, render: (r) => int(r["accounts"]) },
    { header: "Trades", num: true, render: (r) => int(r["trades"]) },
    { header: "Value", num: true, render: (r) => <Money value={n(r["value"])} /> },
    { header: "Avg Household Assets", num: true, render: (r) => <Money value={n(r["avg_household_assets"])} /> },
    {
      header: "Closest to Threshold",
      num: true,
      render: (r) => {
        const within = n(r["households_within_10k_of_threshold"]);
        return within === null ? "—" : `${within} within $10k`;
      },
    },
  ],
  inheritance: [
    { header: "Receiving Advisor", render: (r) => advisorCell(r) },
    {
      header: "From Advisor",
      render: (r) => (
        <>
          {advisorCell(r, "from_advisor_sid", "from_advisor_name")}{" "}
          {r["from_advisor_departed"] === true ? <Chip variant="tag">Departed</Chip> : null}
        </>
      ),
    },
    { header: "Accounts", num: true, render: (r) => int(r["accounts"]) },
    { header: "Transferred", render: (r) => s(r["transfer_date"]) || "—" },
    { header: "Months Since", num: true, render: (r) => int(r["months_since_transfer"]) },
    { header: "Trades", num: true, render: (r) => int(r["trades"]) },
    { header: "Value", num: true, render: (r) => <Money value={n(r["value"])} /> },
  ],
  discount: [
    { header: "Advisor", render: (r) => advisorCell(r) },
    { header: "Accounts", num: true, render: (r) => int(r["accounts"]) },
    { header: "Avg Standard", num: true, render: (r) => bps(r["avg_standard_bps"]) },
    { header: "Avg Actual", num: true, render: (r) => bps(r["avg_actual_bps"]) },
    {
      header: "Avg Reduction",
      num: true,
      render: (r) => {
        const pct = n(r["avg_reduction_pct"]);
        if (pct === null) return "—";
        // above the 10% grid-sharing threshold reads red, mockup-style
        return <span className={pct > 10 ? "dn" : undefined}>{pct.toFixed(1)}%</span>;
      },
    },
    { header: "Above 10%", num: true, render: (r) => int(r["accounts_above_10pct"]) },
    { header: "Grid Points Expected", num: true, render: (r) => int(r["grid_points_expected"]) },
    {
      header: "Recorded",
      num: true,
      render: (r) => {
        const expected = n(r["grid_points_expected"]);
        const recorded = n(r["grid_points_recorded"]);
        if (recorded === null) return "—";
        // THE column: red wherever recorded lags what the plan expects
        const short = expected !== null && recorded < expected;
        return <span className={short ? "dn" : undefined}>{recorded.toLocaleString("en-US")}</span>;
      },
    },
    { header: "Value", num: true, render: (r) => <Money value={n(r["value"])} /> },
  ],
  eligibility: [
    // grouped by product — deliberately NO advisor column
    { header: "Product", render: (r) => s(r["product"]) || s(r["product_id"]) || "—" },
    { header: "Reason", render: (r) => s(r["reason"]) || "—" },
    { header: "Accounts", num: true, render: (r) => int(r["accounts"]) },
    { header: "Advisors", num: true, render: (r) => int(r["advisors"]) },
    { header: "Trades", num: true, render: (r) => int(r["trades"]) },
    { header: "Value", num: true, render: (r) => <Money value={n(r["value"])} /> },
  ],
};

function bps(v: unknown): string {
  const value = n(v);
  return value === null ? "—" : `${Number.isInteger(value) ? value : value.toFixed(1)} bps`;
}

export default function CauseDetailModal({ detail, summaryRow, monthLabel, onClose }: CauseDetailModalProps) {
  const term = useTerm(`noncredited.${detail.reason_cd}`);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  const columns = CAUSE_COLUMNS[detail.cause];
  const sub = [
    monthLabel,
    summaryRow ? `${summaryRow.account_count.toLocaleString("en-US")} accounts` : `${detail.rows.length} rows`,
    summaryRow ? `$${Math.round(summaryRow.value).toLocaleString("en-US")} not credited` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <>
      <div className="scrim on" onClick={onClose} />
      <div className="modal on" role="dialog" aria-modal="true" aria-label={detail.cause_label}>
        <div className="m-head">
          <div>
            <h2>
              {detail.cause_label}{" "}
              <Chip variant="tag" title={term?.definition}>
                {detail.reason_cd}
              </Chip>
            </h2>
            <p style={{ margin: "4px 0 0", color: "var(--slate)", fontSize: "12.5px" }}>{sub}</p>
          </div>
          <button className="m-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="m-body">
          {/* the lead is the server's plain-English description — never invented */}
          <p style={{ margin: "0 0 14px", color: "var(--slate)", fontSize: 13 }}>{detail.description}</p>
          {columns ? (
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    {columns.map((c) => (
                      <th key={c.header} className={c.num ? "num" : undefined}>
                        {c.header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {detail.rows.map((row, i) => (
                    <tr key={i}>
                      {columns.map((c) => (
                        <td key={c.header} className={c.num ? "num" : undefined}>
                          {c.render(row)}
                        </td>
                      ))}
                    </tr>
                  ))}
                  {detail.total ? (
                    <tr className="tot">
                      {columns.map((c, i) =>
                        i === 0 ? (
                          <td key={c.header}>Total</td>
                        ) : (
                          <td key={c.header} className={c.num ? "num" : undefined}>
                            {c.render(detail.total as Row)}
                          </td>
                        ),
                      )}
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          ) : (
            <p style={{ color: "var(--slate)", fontSize: "12.5px" }}>
              Unknown cause &quot;{detail.cause}&quot; — no column spec for this shape.
            </p>
          )}
          {!detail.rows.length ? (
            <p style={{ color: "var(--slate)", fontSize: "12.5px" }}>No rows for {monthLabel}.</p>
          ) : null}
          {detail.note ? (
            <div className="note" style={{ border: "1px solid var(--rule)", borderRadius: 5, marginTop: 12 }}>
              {detail.note}
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}
