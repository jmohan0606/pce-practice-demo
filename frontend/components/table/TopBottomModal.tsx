"use client";

import { useEffect, useState } from "react";
import {
  type DashboardTableRow,
  type ProductRanking,
  type RankingAdvisor,
  getProductRanking,
} from "@/lib/api";
import AdvisorLink from "@/components/AdvisorLink";
import DriverChip from "@/components/DriverChip";
import EmptyState from "@/components/EmptyState";
import { Delta, Money, Pct } from "@/components/Num";
import { useGlossary } from "@/components/Term";

/** Round A2B 3.5 — Top / Bottom contributors modal, per product row.
 *
 * Two tables side by side ranked by change amount, up to 10 each with an
 * honest "Showing N of 10" when fewer. dominant_driver_code is null for many
 * advisors — the cell reads "AI Insights not generated yet", never blank,
 * never guessed. Non-null codes resolve label + tooltip from the glossary
 * key `driver.<code>`; a missing key falls back to the code itself.
 */
export default function TopBottomModal({
  row,
  from,
  to,
  fromLabel,
  toLabel,
  onClose,
}: {
  row: DashboardTableRow;
  from: string;
  to: string;
  fromLabel: string;
  toLabel: string;
  onClose: () => void;
}) {
  const [data, setData] = useState<ProductRanking | null>(null);
  const [error, setError] = useState<string | null>(null);
  const glossary = useGlossary();

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    getProductRanking(row.group_id, from, to)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [row.group_id, from, to]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const driverCell = (code: string | null) => {
    if (!code)
      return (
        <span style={{ color: "var(--slate)", fontSize: 12 }}>
          AI Insights not generated yet
        </span>
      );
    const term = glossary?.terms?.[`driver.${code}`];
    return (
      <DriverChip code={code} label={term?.term ?? null} definition={term?.definition ?? null} />
    );
  };

  const side = (list: RankingAdvisor[], up: boolean, limit: number) => (
    <div>
      <h3 className={up ? "up" : "dn"}>
        {up ? "▲" : "▼"} {up ? "Top" : "Bottom"} {limit} Contributors
      </h3>
      <table>
        <thead>
          <tr>
            <th>Advisor</th>
            <th className="num">{fromLabel}</th>
            <th className="num">{toLabel}</th>
            <th className="num">Change</th>
            <th className="num">% of Change</th>
            <th className="num">Accts</th>
            <th>Dominant Driver</th>
          </tr>
        </thead>
        <tbody>
          {list.map((a) => (
            <tr key={a.advisor_sid}>
              <td>
                <AdvisorLink sid={a.advisor_sid} name={a.advisor_name} />
              </td>
              <td className="num">
                <Money value={a.from_amt} />
              </td>
              <td className="num">
                <Money value={a.to_amt} />
              </td>
              <td className="num">
                <Delta value={a.change_amt} />
              </td>
              <td className="num">
                <Pct value={a.pct_of_total_change} />
              </td>
              <td className="num">
                {a.account_count.toLocaleString("en-US")}{" "}
                <Delta kind="count" value={a.account_delta} />
              </td>
              <td>{driverCell(a.dominant_driver_code)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {list.length < limit ? (
        <div style={{ fontSize: 12, color: "var(--slate)", padding: "8px 2px" }}>
          Showing {list.length} of {limit}
        </div>
      ) : null}
    </div>
  );

  const productName = `${row.display_prefix || ""}${row.group_name}`;
  const rankedBy = data?.ranked_by === "change_amt" ? "change amount" : data?.ranked_by;

  return (
    <>
      <div className="scrim on" onClick={onClose} />
      <div className="modal on" role="dialog" aria-modal="true" aria-label={productName}>
        <div className="m-head">
          <div>
            <h2>{productName}</h2>
            <p style={{ margin: "4px 0 0", color: "var(--slate)", fontSize: 12.5 }}>
              {fromLabel} → {toLabel}
              {data ? ` · ranked by ${rankedBy} · ${data.advisor_count} advisors in this product` : ""}
            </p>
          </div>
          <button type="button" className="m-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="m-body">
          {error ? (
            <EmptyState title="Data Unavailable" message={error} />
          ) : data ? (
            <div className="two">
              {side(data.top, true, data.limit)}
              {side(data.bottom, false, data.limit)}
            </div>
          ) : (
            <EmptyState title="Loading" message="Fetching advisor ranking…" />
          )}
        </div>
      </div>
    </>
  );
}
