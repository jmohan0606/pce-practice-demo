"use client";

import { Pager, usePager } from "@/components/Pager";
import { isBooleanish, labelize, yesNo } from "@/lib/labels";

/** Round 3 — the ONE evidence-table surface (review F3–F7 + task 2).
 *
 * - collapsed by default behind an expand control with a note (F3)
 * - proper column labels, never raw field names (F4)
 * - paginated 5/10/20 (F5) — evidence now carries EVERY row (task 2)
 * - shrinks to its content instead of stretching (F6 — .ev table CSS)
 * - booleans render Yes / No (6.6)
 * - a footer total row reconciles to the finding's headline figure (task 2)
 */

function cell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (isBooleanish(value)) return yesNo(value);
  if (typeof value === "number")
    return Number.isInteger(value)
      ? value.toLocaleString("en-US")
      : value.toLocaleString("en-US", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        });
  return String(value);
}

export function EvidenceTable({
  rows,
  columns,
  totals,
  total,
  startOpen = false,
  noun = "evidence rows",
}: {
  rows: Record<string, unknown>[];
  columns?: string[];
  /** per-column sums from the server (evidence_totals) — the footer that
   * reconciles to the headline figure */
  totals?: Record<string, number>;
  /** the true producing count (evidence_total) */
  total?: number;
  startOpen?: boolean;
  noun?: string;
}) {
  const cols =
    columns && columns.length ? columns : Object.keys(rows[0] ?? {});
  const pager = usePager(rows);
  const totalCount = total ?? rows.length;
  if (!rows.length) return null;
  const totalCols = totals
    ? cols.filter((c) => typeof totals[c] === "number" && totals[c] !== 0)
    : [];
  return (
    <details className="tech ev" open={startOpen || undefined}>
      <summary>
        View evidence — {totalCount.toLocaleString("en-US")} {noun} (opens on
        click)
      </summary>
      <div style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c} className={typeof rows[0]?.[c] === "number" ? "num" : undefined}>
                  {labelize(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pager.rows.map((row, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c} className={typeof row[c] === "number" ? "num" : undefined}>
                    {cell(row[c])}
                  </td>
                ))}
              </tr>
            ))}
            {totalCols.length ? (
              <tr className="tot">
                {cols.map((c, i) => (
                  <td key={c} className={totalCols.includes(c) ? "num" : undefined}>
                    {totalCols.includes(c)
                      ? cell(totals?.[c])
                      : i === 0
                        ? `Total (${totalCount.toLocaleString("en-US")})`
                        : ""}
                  </td>
                ))}
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <Pager {...pager} noun={noun} />
    </details>
  );
}
