"use client";

/** Round G Task 4 — the drill-down side panel (docs/ui/MOCKUP_DRILLDOWN.html).
 *
 * One general component keyed by a scope descriptor (scope, scope_key, labels),
 * NOT product-specific: any table (product contribution today; exceptions or
 * advisor totals later) opens it via `useDrilldownPanel()` + a DrilldownTarget.
 * Levels REPLACE within the panel — they never stack. Everything rendered comes
 * from the API payload: no hardcoded narrative, no fabricated figures. An
 * ungenerated level shows only the deterministic parts plus the Generate
 * estimate; AI content appears only when the payload carries it.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  type DrilldownLevel,
  type DrilldownTxnLevel,
  type DrilldownAdvisorRow,
  type DrilldownAccountRow,
  type DrilldownContributionRow,
  generateDrilldown,
  getDrilldownAccounts,
  getDrilldownAdvisors,
  getDrilldownProduct,
  getDrilldownTxns,
} from "@/lib/api";
import AdvisorLink from "@/components/AdvisorLink";
import Chip from "@/components/Chip";
import { CompareValue } from "@/components/CompareValue";
import { Bold, FindingRow, LimitNotice } from "@/components/InsightPanel";
import { Delta } from "@/components/Num";
import { Pager, usePager } from "@/components/Pager";
import Term from "@/components/Term";
import { arrow, money, moneyAxis, percent } from "@/lib/format";
import { isBooleanish, labelize, yesNo } from "@/lib/labels";

// ---------------------------------------------------------------- target/hook

/** What was clicked: the root scope of the drill chain plus display labels.
 * Reusable — another table opens the same panel with its own descriptor. */
export interface DrilldownTarget {
  scope: "product";
  /** group_id for product scope; parts of deeper keys are appended with ~ server-side */
  scope_key: string;
  from: string; // month_id, e.g. "202604"
  to: string;
  labels: {
    title: string; // e.g. "Managed Accounts"
    from: string; // e.g. "Apr 2026"
    to: string; // e.g. "May 2026"
    sub?: string; // e.g. "Recurring"
  };
}

/** State holder any page can use to drive the panel. */
export function useDrilldownPanel() {
  const [target, setTarget] = useState<DrilldownTarget | null>(null);
  const openPanel = useCallback((t: DrilldownTarget) => setTarget(t), []);
  const closePanel = useCallback(() => setTarget(null), []);
  return { target, openPanel, closePanel };
}

// ---------------------------------------------------------------- level model

type Level =
  | { kind: "product" }
  | { kind: "advisors" }
  | { kind: "accounts"; advisor: string }
  | { kind: "txns"; advisor: string; acct: string };

interface LevelData {
  loading: boolean;
  error: string | null;
  insight: DrilldownLevel | null;
  txns: DrilldownTxnLevel | null;
}

const EMPTY: LevelData = { loading: true, error: null, insight: null, txns: null };

// ---------------------------------------------------------------- formatting

const METRIC_LABELS: Record<string, string> = {
  from_amt: "__FROM__",
  to_amt: "__TO__",
  change_amt: "Change",
  // Review D2 — AUM applies to Managed Accounts only, and says so
  aum: "AUM (Managed Accounts only)",
  advisor_count: "Advisors",
  account_count: "Accounts",
  txn_count: "Transactions",
  from_txn_count: "__FROM__ Transactions",
  to_txn_count: "__TO__ Transactions",
  end_balance: "Balance",
  client_rate_bps: "Rate",
};

function metricLabel(key: string, labels: { from: string; to: string }): string {
  const mapped = METRIC_LABELS[key];
  const raw = mapped ?? labelize(key);
  return raw.replace("__FROM__", labels.from).replace("__TO__", labels.to);
}

function metricValue(key: string, v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  // Round 4 task 3 — the operator's "false" on screen was THIS tile, not the
  // table cell: the advisor-accounts level's metric strip carries
  // is_new_to_product and the formatter let the boolean fall through raw.
  if (isBooleanish(v)) return yesNo(v);
  if (/bps/.test(key)) return `${Number.isInteger(v) ? v : v.toFixed(1)} bps`;
  if (/aum|balance/.test(key)) return moneyAxis(v);
  if (/_amt$|^amt|revenue/.test(key)) return money(v);
  if (/pct/.test(key)) return percent(v);
  if (/count|txn/.test(key)) return v.toLocaleString("en-US");
  return v.toLocaleString("en-US");
}

// ---------------------------------------------------------------- metric strip

/** Deterministic metric strip. Keys prefixed `prior_` feed the prior-month
 * comparison line beneath their base metric (review D3 — coloured + arrowed,
 * counts too). `drills` makes a count a drill button opening the next level.
 * Review D2 — the AUM tile renders ONLY for the managed platform group
 * (`showAum`); for any other product it is simply absent. */
function MetricStrip({
  metrics,
  labels,
  drills,
  showAum = false,
  firmBasis = false,
}: {
  metrics: Record<string, number | null>;
  labels: { from: string; to: string };
  drills?: Record<string, (() => void) | undefined>;
  showAum?: boolean;
  /** Round 5 task 14 — true only at the level-1 (product) strip, whose amount
   * totals are firm-basis while the advisor rows beneath are advisor-basis:
   * the amount tiles get the glossary firm-vs-advisor tooltip. */
  firmBasis?: boolean;
}) {
  const keys = Object.keys(metrics).filter(
    (k) => !k.startsWith("prior_") && (showAum || !/(^|_)aum$/.test(k)),
  );
  if (!keys.length) return null;
  const fromAmt = metrics["from_amt"];
  return (
    <div className="mstrip">
      {keys.map((key) => {
        const v = metrics[key];
        const prior = metrics[`prior_${key}`];
        const drill = drills?.[key];
        const isChange = key === "change_amt";
        const dir = isChange && v ? (v > 0 ? "up" : "dn") : "";
        const changePct =
          isChange && v != null && fromAmt ? (v / Math.abs(fromAmt)) * 100 : null;
        const deltaKind = /_amt$|^amt|aum|balance|revenue/.test(key) ? "money" : "count";
        return (
          <div key={key}>
            <div className="k">
              {firmBasis && /_amt$/.test(key) ? (
                <Term code="metric.firm_vs_advisor">{metricLabel(key, labels)}</Term>
              ) : (
                metricLabel(key, labels)
              )}
            </div>
            {drill && v !== null && v !== undefined ? (
              <button className="count-drill" onClick={drill}>
                {metricValue(key, v)}
              </button>
            ) : (
              <div className={`v ${dir}`.trim()}>
                {isChange && v ? `${arrow(v)} ${money(v)}` : metricValue(key, v)}
              </div>
            )}
            {isChange && changePct !== null ? (
              <div className={`d ${dir}`.trim()}>{percent(changePct)}</div>
            ) : prior !== null && prior !== undefined && v !== null && v !== undefined ? (
              // Review D3 — the secondary line is the prior-month comparison,
              // colour-coded with an up/down arrow, never a muted restatement
              <div className="d">
                <Delta kind={deltaKind} value={v - prior} /> vs {labels.from}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- lifecycle strip (review D8)

const DRILLDOWN_API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8002";

interface LifecycleCounts {
  new_count: number;
  lost_count: number;
  retained_count: number;
  transferred_in_count: number;
  transferred_out_count: number;
  notes: string;
  scope_kind: string;
}

/** GET /api/dashboard/lifecycle — a typed local client (lib/api.ts is not
 * owned by this subagent; gap noted in the report). */
async function fetchLifecycle(
  from: string,
  to: string,
  scope: string,
): Promise<LifecycleCounts> {
  const params = new URLSearchParams({ from, to, scope });
  const response = await fetch(
    `${DRILLDOWN_API_BASE}/api/dashboard/lifecycle?${params.toString()}`,
    { cache: "no-store" },
  );
  if (!response.ok) throw new ApiError(response.status, `${response.status} for /api/dashboard/lifecycle`);
  return (await response.json()) as LifecycleCounts;
}

/** Review D8 — New / Lost / Retained counts at the TOP of every drill-down
 * level, scoped to that level (the product's counts at product/advisors
 * level, the advisor's at account/txn level). A failed fetch renders nothing
 * — the counts are simply absent, never an apology. */
function LifecycleStrip({ from, to, scope }: { from: string; to: string; scope: string }) {
  const [counts, setCounts] = useState<LifecycleCounts | null>(null);
  useEffect(() => {
    let cancelled = false;
    setCounts(null);
    fetchLifecycle(from, to, scope)
      .then((c) => {
        if (!cancelled) setCounts(c);
      })
      .catch(() => {
        /* absent, not apologised for */
      });
    return () => {
      cancelled = true;
    };
  }, [from, to, scope]);
  if (!counts) return null;
  const tiles: [string, number][] = [
    ["New", counts.new_count],
    ["Lost", counts.lost_count],
    ["Retained", counts.retained_count],
    ["Transferred In", counts.transferred_in_count],
    ["Transferred Out", counts.transferred_out_count],
  ];
  return (
    <>
      <div className="mstrip" style={{ marginBottom: 6 }}>
        {tiles.map(([label, value]) => (
          <div key={label}>
            <div className="k">{label}</div>
            <div className="v">{value.toLocaleString("en-US")}</div>
          </div>
        ))}
      </div>
      {counts.notes ? (
        <p className="why-note" style={{ marginTop: 0 }}>
          {counts.notes}
        </p>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------- AI narrative

/** Rendered ONLY when the payload is generated and carries narrative text. */
function AiNarrative({ narrative, bullets }: { narrative: string; bullets: string[] }) {
  return (
    <div className="narr">
      <Chip variant="aigen">◆ AI Generated</Chip>
      {narrative.split(/\n\n+/).map((p, i) => (
        <p key={i} style={i === 0 ? { marginTop: 10 } : undefined}>
          <Bold text={p} />
        </p>
      ))}
      {bullets.length ? (
        <ul>
          {bullets.map((b, i) => (
            <li key={i}>
              <Bold text={b} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- why table

function WhyTable({
  causes,
  labels,
}: {
  causes: NonNullable<DrilldownLevel["movement_causes"]>;
  labels: { from: string; to: string };
}) {
  const rows: { cause: string; from: string; to: string; effect: number }[] = [
    {
      cause: "Advisors selling this product",
      from: String(causes.advisor_count_from),
      to: String(causes.advisor_count_to),
      effect: causes.advisor_effect_amt,
    },
    {
      cause: "Accounts holding this product",
      from: String(causes.account_count_from),
      to: String(causes.account_count_to),
      effect: causes.account_effect_amt,
    },
    {
      cause: "Revenue per existing account",
      from: money(causes.rev_per_existing_from),
      to: money(causes.rev_per_existing_to),
      effect: causes.rev_per_existing_effect_amt,
    },
  ];
  return (
    <>
      <div className="sec-h">Why the number moved</div>
      <div className="why">
        <table>
          <thead>
            <tr>
              <th>Cause</th>
              <th className="num">{labels.from}</th>
              <th className="num">{labels.to}</th>
              <th className="num">Effect</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.cause}>
                <td>{r.cause}</td>
                <td className="num">{r.from}</td>
                <td className="num">{r.to}</td>
                <td className={`num ${r.effect < 0 ? "dn" : r.effect > 0 ? "up" : ""}`.trim()}>
                  {r.effect === 0 ? "—" : `${arrow(r.effect)} ${money(r.effect)}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="why-note">
        {causes.note ||
          "Counts are query results. The effect column is descriptive, not a decomposition — the parts are not expected to sum exactly to the change."}
      </p>
    </>
  );
}

// ---------------------------------------------------------------- contribution tables

function isAdvisorRow(r: DrilldownContributionRow): r is DrilldownAdvisorRow {
  return typeof r === "object" && r !== null && "advisor_sid" in r;
}
function isAccountRow(r: DrilldownContributionRow): r is DrilldownAccountRow {
  return typeof r === "object" && r !== null && "acct_key" in r;
}

function ChangeCell({ change }: { change: number }) {
  return (
    <td className={`num ${change < 0 ? "dn" : change > 0 ? "up" : ""}`.trim()}>
      {change === 0 ? "—" : `${arrow(change)} ${money(change)}`}
    </td>
  );
}

// A3/D5 — advisor identity is Name (SID) even when the contribution payload
// carries only the SID: one cached advisor-list fetch resolves names.
let _advisorNames: Record<string, string> | null = null;
function useAdvisorNames(): Record<string, string> {
  const [names, setNames] = useState<Record<string, string>>(_advisorNames ?? {});
  useEffect(() => {
    if (_advisorNames) return;
    import("@/lib/api").then(({ getAdvisors }) =>
      getAdvisors()
        .then((r) => {
          _advisorNames = Object.fromEntries(
            (r.advisors ?? []).map((a) => [a.advisor_sid, a.advisor_name]),
          );
          setNames(_advisorNames);
        })
        .catch(() => {}),
    );
  }, []);
  return names;
}

function AdvisorRows({
  rows,
  labels,
  onOpen,
}: {
  rows: DrilldownAdvisorRow[];
  labels: { from: string; to: string };
  onOpen: (advisor: string) => void;
}) {
  const pager = usePager(rows);
  const names = useAdvisorNames();
  return (
    <>
      <div className="sec-h">Contribution by advisor</div>
      <div className="why">
        <table>
          <thead>
            <tr>
              <th>Advisor</th>
              <th className="num">{labels.from}</th>
              <th className="num">{labels.to}</th>
              <th className="num">Change</th>
              <th className="num">New To Product</th>
              <th className="num">Accounts</th>
              <th aria-label="Open" />
            </tr>
          </thead>
          <tbody>
            {pager.rows.map((r) => (
              <tr key={r.advisor_sid}>
                <td>
                  {/* Review D5 — advisors here are ALWAYS Name (SID), linked */}
                  <AdvisorLink sid={r.advisor_sid} name={r.advisor_name ?? names[r.advisor_sid] ?? null} />{" "}
                  {r.is_new_to_product ? (
                    // Review D6 — the New tag renders bold / highlighted
                    <span
                      className="chip newtag"
                      title="This advisor recorded no revenue for this product in the prior month."
                    >
                      New
                    </span>
                  ) : null}
                </td>
                <td className="num">{money(r.from_amt)}</td>
                <td className="num">{money(r.to_amt)}</td>
                <ChangeCell change={r.change_amt} />
                {/* Review D7 — booleans render Yes / No, never true / false */}
                <td className="num">{yesNo(r.is_new_to_product)}</td>
                <td className="num">
                  <button
                    className="count-drill sm"
                    onClick={() => onOpen(r.advisor_sid)}
                    aria-label={`Open accounts for ${r.advisor_sid}`}
                  >
                    {r.account_count}
                  </button>
                </td>
                <td>
                  <button
                    className="btn row-open"
                    onClick={() => onOpen(r.advisor_sid)}
                    aria-label={`Open accounts for ${r.advisor_sid}`}
                  >
                    ›
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pager {...pager} noun="advisors" />
      </div>
    </>
  );
}

function AccountRows({
  rows,
  labels,
  onOpen,
}: {
  rows: DrilldownAccountRow[];
  labels: { from: string; to: string };
  onOpen: (acct: string) => void;
}) {
  const pager = usePager(rows);
  return (
    <>
      <div className="sec-h">Contribution by account</div>
      <div className="why">
        <table>
          <thead>
            <tr>
              <th>Account</th>
              <th className="num">{labels.from}</th>
              <th className="num">{labels.to}</th>
              <th className="num">Change</th>
              <th className="num">Balance</th>
              <th className="num">Transactions</th>
              <th aria-label="Open" />
            </tr>
          </thead>
          <tbody>
            {pager.rows.map((r) => (
              <tr key={r.acct_key}>
                <td>{r.acct_key}</td>
                <td className="num">{money(r.from_amt)}</td>
                <td className="num">{money(r.to_amt)}</td>
                <ChangeCell change={r.change_amt} />
                <td className="num">{moneyAxis(r.end_balance)}</td>
                <td className="num">
                  <button
                    className="count-drill sm"
                    onClick={() => onOpen(r.acct_key)}
                    aria-label={`Open transactions for account ${r.acct_key}`}
                  >
                    {r.txn_count}
                  </button>
                </td>
                <td>
                  <button
                    className="btn row-open"
                    onClick={() => onOpen(r.acct_key)}
                    aria-label={`Open transactions for account ${r.acct_key}`}
                  >
                    ›
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pager {...pager} noun="accounts" />
      </div>
    </>
  );
}

/** Fallback for a contribution shape this component does not recognise —
 * render the payload's own columns rather than dropping data. Headers go
 * through labelize (6.5) and booleans through yesNo (D7). */
function GenericRows({ rows }: { rows: Record<string, unknown>[] }) {
  const columns = Object.keys(rows[0] ?? {});
  const pager = usePager(rows);
  if (!columns.length) return null;
  return (
    <>
      <div className="sec-h">Contribution</div>
      <div className="why">
        <table>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c} className={typeof rows[0][c] === "number" ? "num" : undefined}>
                  {labelize(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pager.rows.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c} className={typeof row[c] === "number" ? "num" : undefined}>
                    {row[c] === null || row[c] === undefined || row[c] === ""
                      ? "—"
                      : isBooleanish(row[c])
                        ? yesNo(row[c])
                        : String(row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <Pager {...pager} noun="rows" />
      </div>
    </>
  );
}

// ---------------------------------------------------------------- panel

export default function DrilldownPanel({
  target,
  onClose,
}: {
  target: DrilldownTarget | null;
  onClose: () => void;
}) {
  const open = target !== null;
  const [level, setLevel] = useState<Level>({ kind: "product" });
  const [data, setData] = useState<LevelData>(EMPTY);
  const [generating, setGenerating] = useState(false);
  const [advisorCount, setAdvisorCount] = useState<number | null>(null);

  const closeRef = useRef<HTMLButtonElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  // reset to the root level whenever a new target opens
  useEffect(() => {
    setLevel({ kind: "product" });
    setAdvisorCount(null);
  }, [target]);

  // focus into the panel on open; return to the invoking element on close
  useEffect(() => {
    if (open) {
      restoreRef.current = (document.activeElement as HTMLElement) ?? null;
      closeRef.current?.focus();
    } else if (restoreRef.current) {
      restoreRef.current.focus();
      restoreRef.current = null;
    }
  }, [open]);

  // Escape closes
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // fetch the current level
  useEffect(() => {
    if (!target) return;
    let cancelled = false;
    setData(EMPTY);
    setGenerating(false);
    const { scope_key: groupId, from, to } = target;
    const load = async (): Promise<Partial<LevelData>> => {
      if (level.kind === "product") {
        return { insight: await getDrilldownProduct(groupId, from, to) };
      }
      if (level.kind === "advisors") {
        return { insight: await getDrilldownAdvisors(groupId, from, to) };
      }
      if (level.kind === "accounts") {
        return { insight: await getDrilldownAccounts(groupId, level.advisor, from, to) };
      }
      return { txns: await getDrilldownTxns(groupId, level.advisor, level.acct, from, to) };
    };
    load()
      .then((partial) => {
        if (cancelled) return;
        setData({ ...EMPTY, loading: false, ...partial });
        const ins = partial.insight;
        if (ins) {
          const count =
            level.kind === "advisors"
              ? ins.contributions?.length ?? ins.metrics?.["advisor_count"] ?? null
              : ins.metrics?.["advisor_count"] ?? null;
          if (typeof count === "number") setAdvisorCount(count);
        }
      })
      .catch((e) => {
        if (cancelled) return;
        const message =
          e instanceof ApiError && e.status === 0
            ? e.message
            : String((e as Error)?.message || e);
        setData({ loading: false, error: message, insight: null, txns: null });
      });
    return () => {
      cancelled = true;
    };
  }, [target, level]);

  const goTo = useCallback((next: Level) => {
    setLevel(next);
    bodyRef.current?.scrollTo({ top: 0 });
  }, []);

  const generate = useCallback(() => {
    if (!target || !data.insight || generating) return;
    const { scope, scope_key } = data.insight;
    setGenerating(true);
    generateDrilldown(scope, scope_key, target.from, target.to)
      .then((ins) => {
        setData({ loading: false, error: null, insight: ins, txns: null });
        setGenerating(false);
      })
      .catch((e) => {
        setData((d) => ({ ...d, error: String((e as Error)?.message || e) }));
        setGenerating(false);
      });
  }, [target, data.insight, generating]);

  if (!target) {
    // keep the aside mounted so the slide-out transition plays
    return (
      <>
        <div className="scrim" aria-hidden="true" />
        <aside className="panel" role="dialog" aria-label="Drill-down" aria-hidden="true" />
      </>
    );
  }

  const { labels } = target;
  const advisorsCrumb = advisorCount !== null ? `${advisorCount} Advisors` : "Advisors";

  // breadcrumb: [label, level-to-navigate | null(current)]
  const crumb: [string, Level | null][] =
    level.kind === "product"
      ? [[labels.title, null]]
      : level.kind === "advisors"
        ? [
            [labels.title, { kind: "product" }],
            [advisorsCrumb, null],
          ]
        : level.kind === "accounts"
          ? [
              [labels.title, { kind: "product" }],
              [advisorsCrumb, { kind: "advisors" }],
              [level.advisor, null],
            ]
          : [
              [labels.title, { kind: "product" }],
              [advisorsCrumb, { kind: "advisors" }],
              [level.advisor, { kind: "accounts", advisor: level.advisor }],
              [`Account ${level.acct}`, null],
            ];

  const title =
    level.kind === "product"
      ? labels.title
      : level.kind === "advisors"
        ? "Advisors"
        : level.kind === "accounts"
          ? level.advisor
          : `Account ${level.acct}`;
  const sub =
    level.kind === "product"
      ? `${labels.from} → ${labels.to}${labels.sub ? ` · ${labels.sub}` : ""}`
      : level.kind === "advisors"
        ? `Advisors selling ${labels.title} · ${labels.from} → ${labels.to}`
        : level.kind === "accounts"
          ? `Accounts in ${labels.title} · ${labels.from} → ${labels.to}`
          : `${labels.title} · ${level.advisor} · ${labels.to}`;

  const ins = data.insight;
  const txns = data.txns;
  const stored = ins?.generated ? ins.stored : null;

  return (
    <>
      <div className="scrim on" onClick={onClose} aria-hidden="true" />
      <aside className="panel on" role="dialog" aria-label={`Drill-down: ${title}`}>
        <div className="p-head">
          <div style={{ minWidth: 0 }}>
            <div className="crumb">
              {crumb.map(([label, dest], i) => (
                <span key={i} style={{ display: "contents" }}>
                  {i > 0 ? <span className="sep">›</span> : null}
                  {dest ? (
                    <button onClick={() => goTo(dest)}>{label}</button>
                  ) : (
                    <span className="cur">{label}</span>
                  )}
                </span>
              ))}
            </div>
            <div className="p-title">{title}</div>
            <div className="p-sub">{sub}</div>
          </div>
          <button className="p-close" ref={closeRef} onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="p-body" ref={bodyRef}>
          {data.loading ? (
            <div className="empty">
              <b>Loading</b>
              <p>Fetching drill-down…</p>
            </div>
          ) : data.error ? (
            <div className="empty">
              <b>Data Unavailable</b>
              <p>{data.error}</p>
            </div>
          ) : txns || ins ? (
            <>
              {/* Review D8 — New / Lost / Retained at the top of EVERY level,
                  scoped to it: the product's counts at product/advisor-list
                  level, the advisor's own at account/transaction level. */}
              <LifecycleStrip
                from={target.from}
                to={target.to}
                scope={
                  level.kind === "product" || level.kind === "advisors"
                    ? target.scope_key
                    : level.advisor
                }
              />
              {txns ? (
                <TxnView txns={txns} labels={labels} />
              ) : ins ? (
                <InsightView
                  ins={ins}
                  level={level}
                  labels={labels}
                  managed={target.scope_key === "managed_accounts"}
                  goTo={goTo}
                  generate={generate}
                  generating={generating}
                />
              ) : null}
            </>
          ) : null}
        </div>

        <div className="p-foot">
          <span>
            {stored ? (
              <>
                <span className="stored">✓ Stored</span> generated {stored.generated_at} · rule
                set v{stored.version_no} · shared by everyone
              </>
            ) : null}
          </span>
          <span>
            {ins?.generated ? (
              <button className="btn row-open" onClick={generate} disabled={generating}>
                {generating ? "Regenerating…" : "↻ Regenerate"}
              </button>
            ) : null}
          </span>
        </div>
      </aside>
    </>
  );
}

// ---------------------------------------------------------------- level views

function InsightView({
  ins,
  level,
  labels,
  managed,
  goTo,
  generate,
  generating,
}: {
  ins: DrilldownLevel;
  level: Level;
  labels: DrilldownTarget["labels"];
  /** Review D2 — true only for the managed platform group; gates the AUM tile. */
  managed: boolean;
  goTo: (next: Level) => void;
  generate: () => void;
  generating: boolean;
}) {
  const monthLabels = { from: labels.from, to: labels.to };
  const contributions = ins.contributions ?? [];
  const advisorRows = contributions.filter(isAdvisorRow);
  const accountRows = contributions.filter(isAccountRow);

  // drillable counts in the metric strip — only where a real endpoint exists
  const drills: Record<string, (() => void) | undefined> =
    level.kind === "product" ? { advisor_count: () => goTo({ kind: "advisors" }) } : {};

  return (
    <>
      <MetricStrip
        metrics={ins.metrics ?? {}}
        labels={monthLabels}
        drills={drills}
        showAum={managed}
        firmBasis={level.kind === "product"}
      />

      {/* Round H 4.1: a scoped run that hit a limit says so in a sentence —
          rendered whenever the payload carries limits_hit */}
      {ins.generated ? <LimitNotice limits={ins.limits_hit} /> : null}

      {ins.generated && ins.narrative ? (
        <AiNarrative narrative={ins.narrative} bullets={ins.bullets ?? []} />
      ) : !ins.generated ? (
        <div className="gen">
          <div className="t">No insight generated for this view yet</div>
          <div className="m">
            Generated once, then stored permanently against the current rule set. Everyone who
            opens this view sees the same insight and the same figures — it is not regenerated per
            person. A new rule version produces a new insight; nothing is overwritten.
          </div>
          <button className="btn primary" onClick={generate} disabled={generating}>
            {generating
              ? "Generating…"
              : `Generate${
                  ins.estimate
                    ? ` — approx $${ins.estimate.cost_usd.toFixed(2)}, ~${ins.estimate.seconds}s`
                    : ""
                }`}
          </button>
        </div>
      ) : null}

      {ins.movement_causes ? <WhyTable causes={ins.movement_causes} labels={monthLabels} /> : null}

      {advisorRows.length ? (
        <AdvisorRows
          rows={advisorRows}
          labels={monthLabels}
          onOpen={(advisor) => goTo({ kind: "accounts", advisor })}
        />
      ) : accountRows.length && level.kind === "accounts" ? (
        <AccountRows
          rows={accountRows}
          labels={monthLabels}
          onOpen={(acct) => goTo({ kind: "txns", advisor: level.advisor, acct })}
        />
      ) : contributions.length ? (
        <GenericRows rows={contributions as Record<string, unknown>[]} />
      ) : null}

      {ins.generated && ins.findings?.length ? (
        <>
          <div className="sec-h">Findings</div>
          {ins.findings.map((f, i) => (
            <FindingRow key={f.finding_id ?? i} finding={f} defaultOpen={i === 0} />
          ))}
        </>
      ) : null}
    </>
  );
}

/** Transaction level: deterministic only — llm:false means no AI block at all.
 * The explanatory caption is plain text derived from the payload, never styled
 * as AI content. */
function TxnView({
  txns,
  labels,
}: {
  txns: DrilldownTxnLevel;
  labels: DrilldownTarget["labels"];
}) {
  const monthLabels = { from: labels.from, to: labels.to };
  const rows = txns.transactions ?? [];
  const txnPager = usePager(rows);
  const total = rows.reduce((sum, t) => sum + (t.credited_amt || 0), 0);
  const fromCount = txns.metrics?.["from_txn_count"];
  const toCount = txns.metrics?.["to_txn_count"];
  const volumePct =
    fromCount != null && toCount != null && fromCount !== 0
      ? ((toCount - fromCount) / Math.abs(fromCount)) * 100
      : null;
  return (
    <>
      <MetricStrip metrics={txns.metrics ?? {}} labels={monthLabels} />
      {/* Review D9 — transaction volume: count, difference and percentage,
          current vs prior month, coloured + arrowed */}
      {toCount != null ? (
        <div className="mstrip" style={{ marginTop: 6 }}>
          <div>
            <div className="k">Transaction Volume — {labels.to}</div>
            <div className="v">
              <CompareValue
                current={toCount}
                prior={fromCount}
                kind="count"
                priorLabel={labels.from}
              />
            </div>
            {volumePct !== null ? (
              <div className="d">
                <Delta kind="pct" value={volumePct} /> vs {labels.from}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
      <div className="sec-h">Transactions — {labels.to}</div>
      <div className="why">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Description</th>
              <th>Product</th>
              <th className="num">Rate</th>
              <th className="num">Credited</th>
            </tr>
          </thead>
          <tbody>
            {txnPager.rows.map((t, i) => (
              <tr key={i}>
                <td>{t.trade_dt}</td>
                <td>{t.trade_description}</td>
                <td>{t.product_id}</td>
                <td className="num">
                  {t.client_rate_bps === null || t.client_rate_bps === undefined
                    ? "—"
                    : `${
                        Number.isInteger(t.client_rate_bps)
                          ? t.client_rate_bps
                          : t.client_rate_bps.toFixed(1)
                      } bps`}
                </td>
                <td className={`num ${t.credited_amt < 0 ? "dn" : t.credited_amt > 0 ? "up" : ""}`.trim()}>
                  {money(t.credited_amt)}
                </td>
              </tr>
            ))}
            {rows.length ? (
              <tr className="tot">
                <td colSpan={4}>
                  Total — {rows.length} transaction{rows.length === 1 ? "" : "s"}
                </td>
                <td className={`num ${total < 0 ? "dn" : total > 0 ? "up" : ""}`.trim()}>
                  {money(total)}
                </td>
              </tr>
            ) : (
              <tr>
                <td colSpan={5} style={{ color: "var(--slate)" }}>
                  No credited transactions in {labels.to} for this account.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <Pager {...txnPager} noun="transactions" />
      </div>
      <p className="why-note">
        {fromCount === 0
          ? `${labels.from} had no credited transactions for this account. `
          : ""}
        Reason-coded rows are excluded from credited totals but remain queryable.
      </p>
    </>
  );
}
