"use client";

/** Round A2B 4.3 — the dashboard's Non-Credited (9X) card.
 *
 * Self-contained: fetches `/api/noncredited/summary` for the TO-month of the
 * selected transition on mount / prop change and renders its own empty state.
 *
 * Props (the common section contract — the main thread composes this into
 * `app/page.tsx`):
 *   - `fromMonth: string`  — from-month id (unused by the query; part of the
 *                            shared contract so all sections compose alike)
 *   - `toMonth: string`    — the month analysed, e.g. "202605"
 *   - `monthName: (id: string) => string` — month id -> display name
 *
 * Behaviour:
 *   - Summary table by cause: bold label + 9X code chip (tooltip from the
 *     glossary `noncredited.<code>`), accounts / trades / value / advisors,
 *     the server's `description` as the plain-English "What it means" column
 *     (never invented), and a View button per cause.
 *   - View fetches `/api/noncredited/detail/{cause}` and opens
 *     `CauseDetailModal` — each cause has its OWN table shape.
 *   - `tr.tot` total row from the server total; `.note` foot from the server
 *     note; card sub-line built with `<Money>`.
 *   - Export select posts `POST /api/export` with
 *     `{section:"noncredited", format, params:{month}}` (params confirmed in
 *     app/export/providers.py — requires `month`, or `to`).
 */

import { useCallback, useEffect, useState } from "react";
import {
  type NoncreditedDetail,
  type NoncreditedRow,
  type NoncreditedSummary,
  exportSection,
  getNoncreditedDetail,
  getNoncreditedSummary,
} from "@/lib/api";
import Chip from "@/components/Chip";
import { CompareValue } from "@/components/CompareValue";
import EmptyState from "@/components/EmptyState";
import { Money } from "@/components/Num";
import { useTerm } from "@/components/Term";
import CauseDetailModal from "@/components/noncredited/CauseDetailModal";

export interface NoncreditedSectionProps {
  fromMonth: string;
  toMonth: string;
  monthName: (id: string) => string;
}

const EXPORT_FORMATS = [
  ["pdf", "PDF"],
  ["pptx", "PowerPoint"],
  ["xlsx", "Excel"],
  ["csv", "CSV"],
] as const;

/** 9X code chip whose tooltip resolves from the glossary. */
function CodeChip({ code }: { code: string }) {
  const term = useTerm(`noncredited.${code}`);
  return (
    <Chip variant="tag" title={term?.definition}>
      {code}
    </Chip>
  );
}

export default function NoncreditedSection({ fromMonth, toMonth, monthName }: NoncreditedSectionProps) {
  const [summary, setSummary] = useState<NoncreditedSummary | null>(null);
  // Review G3 — the from-month summary feeds the month-over-month deltas
  const [priorSummary, setPriorSummary] = useState<NoncreditedSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<NoncreditedDetail | null>(null);
  const [priorDetail, setPriorDetail] = useState<NoncreditedDetail | null>(null);
  const [detailRow, setDetailRow] = useState<NoncreditedRow | null>(null);
  const [busyCause, setBusyCause] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setDetail(null);
    setPriorDetail(null);
    getNoncreditedSummary(toMonth)
      .then((s) => {
        setSummary(s);
        setLoading(false);
      })
      .catch((e) => {
        setSummary(null);
        setError(String((e as Error)?.message || e));
        setLoading(false);
      });
    // the prior month's figures power the comparisons; a miss means the
    // comparison line is simply absent — never an error
    getNoncreditedSummary(fromMonth)
      .then(setPriorSummary)
      .catch(() => setPriorSummary(null));
  }, [fromMonth, toMonth]);

  const openCause = useCallback(
    (row: NoncreditedRow) => {
      setBusyCause(row.cause);
      Promise.all([
        getNoncreditedDetail(row.cause, toMonth),
        // Review G3 — the per-cause detail carries the same comparison
        getNoncreditedDetail(row.cause, fromMonth).catch(() => null),
      ])
        .then(([d, prior]) => {
          setDetail(d);
          setPriorDetail(prior);
          setDetailRow(row);
        })
        .catch((e) => setError(String((e as Error)?.message || e)))
        .finally(() => setBusyCause(null));
    },
    [fromMonth, toMonth],
  );

  const priorByReason = new Map((priorSummary?.rows ?? []).map((r) => [r.reason_cd, r]));
  const fromLabel = monthName(fromMonth);

  const doExport = async (format: (typeof EXPORT_FORMATS)[number][0]) => {
    setExportBusy(true);
    try {
      await exportSection("noncredited", format, { month: toMonth });
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setExportBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <h2>Non-Credited Revenue — Why It Did Not Count</h2>
          <p>
            {summary ? (
              <>
                <Money value={summary.total.value} /> of {monthName(toMonth)} transaction value did
                not reach credited revenue. Grouped by cause.
              </>
            ) : (
              <>Transactions carrying a reason code, grouped by cause · {monthName(toMonth)}</>
            )}
          </p>
        </div>
        <div className="ctl">
          <select
            className="btn"
            value=""
            disabled={exportBusy || !summary}
            onChange={(e) => {
              const fmt = e.target.value as (typeof EXPORT_FORMATS)[number][0] | "";
              if (fmt) void doExport(fmt);
              e.target.value = "";
            }}
            aria-label="Export"
          >
            <option value="">{exportBusy ? "Exporting…" : "Export…"}</option>
            {EXPORT_FORMATS.map(([fmt, label]) => (
              <option key={fmt} value={fmt}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="card-b flush" style={{ padding: 0 }}>
        {error ? (
          <div style={{ padding: 18 }}>
            <EmptyState title="Non-credited analysis failed to load" message={error} />
          </div>
        ) : null}
        {loading ? (
          <p style={{ color: "var(--slate)", fontSize: "12.5px", margin: 0, padding: "14px 18px" }}>
            Loading…
          </p>
        ) : null}
        {summary ? (
          <>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th style={{ width: "22%" }}>Cause</th>
                    <th className="num">Accounts</th>
                    <th className="num">Trades</th>
                    <th className="num">Value</th>
                    <th className="num">Advisors</th>
                    {/* Review G1 — naming convention on the label */}
                    <th style={{ width: "34%" }}>What It Means</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {summary.rows.map((row) => {
                    const prior = priorByReason.get(row.reason_cd);
                    return (
                    <tr key={row.reason_cd}>
                      <td>
                        {/* Review F7-style row header */}
                        <span className="rowhead">{row.cause_label}</span>{" "}
                        <CodeChip code={row.reason_cd} />
                      </td>
                      {/* Review G3 — month-over-month deltas on every figure */}
                      <td className="num">
                        <CompareValue
                          current={row.account_count}
                          prior={prior?.account_count}
                          kind="count"
                          priorLabel={fromLabel}
                        />
                      </td>
                      <td className="num">
                        <CompareValue
                          current={row.trade_count}
                          prior={prior?.trade_count}
                          kind="count"
                          priorLabel={fromLabel}
                        />
                      </td>
                      <td className="num">
                        <CompareValue
                          current={row.value}
                          prior={prior?.value}
                          kind="money"
                          priorLabel={fromLabel}
                        />
                      </td>
                      <td className="num">
                        <CompareValue
                          current={row.advisor_count}
                          prior={prior?.advisor_count}
                          kind="count"
                          priorLabel={fromLabel}
                        />
                      </td>
                      {/* the server's description IS the plain-English column */}
                      <td style={{ color: "var(--slate)" }}>{row.description}</td>
                      <td>
                        <button
                          className="btn sm"
                          onClick={() => openCause(row)}
                          disabled={busyCause !== null}
                        >
                          {busyCause === row.cause ? "…" : "View"}
                        </button>
                      </td>
                    </tr>
                    );
                  })}
                  <tr className="tot">
                    {/* Review G1 — naming convention on the label */}
                    <td>Total Non-Credited</td>
                    <td className="num">
                      <CompareValue
                        current={summary.total.account_count}
                        prior={priorSummary?.total.account_count}
                        kind="count"
                        priorLabel={fromLabel}
                      />
                    </td>
                    <td className="num">
                      <CompareValue
                        current={summary.total.trade_count}
                        prior={priorSummary?.total.trade_count}
                        kind="count"
                        priorLabel={fromLabel}
                      />
                    </td>
                    <td className="num">
                      <CompareValue
                        current={summary.total.value}
                        prior={priorSummary?.total.value}
                        kind="money"
                        priorLabel={fromLabel}
                      />
                    </td>
                    <td className="num">—</td>
                    <td>—</td>
                    <td>—</td>
                  </tr>
                </tbody>
              </table>
            </div>
            {summary.note ? <div className="note">{summary.note}</div> : null}
          </>
        ) : null}
      </div>
      {detail ? (
        <CauseDetailModal
          detail={detail}
          priorDetail={priorDetail}
          summaryRow={detailRow}
          monthLabel={monthName(toMonth)}
          priorMonthLabel={fromLabel}
          onClose={() => {
            setDetail(null);
            setPriorDetail(null);
            setDetailRow(null);
          }}
        />
      ) : null}
    </div>
  );
}
