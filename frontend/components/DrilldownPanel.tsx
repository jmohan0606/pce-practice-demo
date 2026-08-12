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
import Chip from "@/components/Chip";
import { Bold, FindingRow, LimitNotice } from "@/components/InsightPanel";
import { arrow, money, moneyAxis, percent } from "@/lib/format";

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
  aum: "AUM",
  advisor_count: "Advisors",
  account_count: "Accounts",
  txn_count: "Txns",
  from_txn_count: "__FROM__ Txns",
  to_txn_count: "__TO__ Txns",
  end_balance: "Balance",
  client_rate_bps: "Rate",
};

function metricLabel(key: string, labels: { from: string; to: string }): string {
  const mapped = METRIC_LABELS[key];
  const raw = mapped ?? key.replace(/_/g, " ");
  return raw.replace("__FROM__", labels.from).replace("__TO__", labels.to);
}

function metricValue(key: string, v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (/bps/.test(key)) return `${Number.isInteger(v) ? v : v.toFixed(1)} bps`;
  if (/aum|balance/.test(key)) return moneyAxis(v);
  if (/_amt$|^amt|revenue/.test(key)) return money(v);
  if (/pct/.test(key)) return percent(v);
  if (/count|txn/.test(key)) return v.toLocaleString("en-US");
  return v.toLocaleString("en-US");
}

// ---------------------------------------------------------------- metric strip

/** Deterministic metric strip. Keys prefixed `prior_` render as the muted
 * "N in <from month>" sub-line of their base metric. `drills` makes a count
 * a drill button opening the next level. */
function MetricStrip({
  metrics,
  labels,
  drills,
}: {
  metrics: Record<string, number | null>;
  labels: { from: string; to: string };
  drills?: Record<string, (() => void) | undefined>;
}) {
  const keys = Object.keys(metrics).filter((k) => !k.startsWith("prior_"));
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
        return (
          <div key={key}>
            <div className="k">{metricLabel(key, labels)}</div>
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
            ) : prior !== null && prior !== undefined ? (
              <div className="d mut">
                {metricValue(key, prior)} in {labels.from}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
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

function AdvisorRows({
  rows,
  labels,
  onOpen,
}: {
  rows: DrilldownAdvisorRow[];
  labels: { from: string; to: string };
  onOpen: (advisor: string) => void;
}) {
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
              <th className="num">Accounts</th>
              <th aria-label="Open" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.advisor_sid}>
                <td>
                  {r.advisor_sid}
                  {r.advisor_name ? ` · ${r.advisor_name}` : ""}{" "}
                  {r.is_new_to_product ? (
                    <Chip
                      variant="tag"
                      title="This advisor recorded no revenue for this product in the prior month."
                    >
                      New
                    </Chip>
                  ) : null}
                </td>
                <td className="num">{money(r.from_amt)}</td>
                <td className="num">{money(r.to_amt)}</td>
                <ChangeCell change={r.change_amt} />
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
              <th className="num">Txns</th>
              <th aria-label="Open" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
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
      </div>
    </>
  );
}

/** Fallback for a contribution shape this component does not recognise —
 * render the payload's own columns rather than dropping data. */
function GenericRows({ rows }: { rows: Record<string, unknown>[] }) {
  const columns = Object.keys(rows[0] ?? {});
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
                  {c.replace(/_/g, " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c} className={typeof row[c] === "number" ? "num" : undefined}>
                    {row[c] === null || row[c] === undefined || row[c] === ""
                      ? "—"
                      : String(row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
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
          ) : txns ? (
            <TxnView txns={txns} labels={labels} />
          ) : ins ? (
            <InsightView
              ins={ins}
              level={level}
              labels={labels}
              goTo={goTo}
              generate={generate}
              generating={generating}
            />
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
  goTo,
  generate,
  generating,
}: {
  ins: DrilldownLevel;
  level: Level;
  labels: DrilldownTarget["labels"];
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
      <MetricStrip metrics={ins.metrics ?? {}} labels={monthLabels} drills={drills} />

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
  const total = rows.reduce((sum, t) => sum + (t.credited_amt || 0), 0);
  const fromCount = txns.metrics?.["from_txn_count"];
  return (
    <>
      <MetricStrip metrics={txns.metrics ?? {}} labels={monthLabels} />
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
            {rows.map((t, i) => (
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
