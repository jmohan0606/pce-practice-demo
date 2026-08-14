"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import TransitionChart from "@/components/chart/TransitionChart";
import Chip from "@/components/Chip";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import { FindingRow, LimitNotice } from "@/components/InsightPanel";
import { Delta, Money } from "@/components/Num";
import { Gated } from "@/lib/flags";
import { arrow, money, percent } from "@/lib/format";
import {
  type Finding,
  type InsightRun,
  type MonthRow,
  type Transition,
  getInsights,
  getMonths,
  getTransitions,
} from "@/lib/api";
import {
  type AdvisorListRow,
  type AdvisorPeerRanking,
  type AdvisorSummary,
  type CoachingResult,
  type OpportunitiesResponse,
  generateCoaching,
  getAdvisorList,
  getAdvisorPeerRanking,
  getAdvisorSummary,
  getCoaching,
  getOpportunities,
} from "@/lib/advisorApi";

/** Round A2B task 6 — iPerform Advisor AI Insights.
 * Advisor-scoped ONLY (the practice view lives on the dashboard). The chart's
 * arrow click drives every section below; there is NO transition dropdown. */
export default function AdvisorPage() {
  return (
    <Suspense fallback={null}>
      <AdvisorPageInner />
    </Suspense>
  );
}

function AdvisorPageInner() {
  const router = useRouter();
  const params = useSearchParams();
  const urlSid = params.get("sid") ?? "";

  const [advisors, setAdvisors] = useState<AdvisorListRow[]>([]);
  const [sid, setSid] = useState<string>(urlSid);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAdvisorList()
      .then((r) => {
        const cohort = r.advisors.filter((a) => a.in_cohort);
        setAdvisors(cohort);
        setSid((cur) => cur || urlSid || cohort[0]?.advisor_sid || "");
      })
      .catch((e) => setError(String(e?.message || e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ?sid= is the deep-link target — keep the URL in sync with the selection
  useEffect(() => {
    if (urlSid && urlSid !== sid) setSid(urlSid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlSid]);
  const selectSid = useCallback(
    (next: string) => {
      setSid(next);
      router.replace(`/advisor?sid=${encodeURIComponent(next)}`);
    },
    [router],
  );

  // 6.1 — search filters by name, SID, or rep code
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return advisors;
    return advisors.filter(
      (a) =>
        a.advisor_name.toLowerCase().includes(q) ||
        a.advisor_sid.toLowerCase().includes(q) ||
        a.rep_code.toLowerCase().includes(q),
    );
  }, [advisors, search]);

  const advisor = advisors.find((a) => a.advisor_sid === sid) ?? null;

  return (
    <section>
      <PageHeader
        title="iPerform Advisor AI Insights"
        meta="One advisor's transitions, drivers, peer position and coaching — every figure a stored query result"
      >
        <input
          className="filter"
          type="text"
          placeholder="Search name, SID or rep code…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search advisors"
          style={{ width: 210 }}
        />
        <select value={sid} onChange={(e) => selectSid(e.target.value)} aria-label="Advisor">
          {filtered.map((a) => (
            <option key={a.advisor_sid} value={a.advisor_sid}>
              {a.advisor_name || a.advisor_sid} ({a.advisor_sid}) · {a.rep_code}
            </option>
          ))}
          {!filtered.length ? <option value="">No advisors match</option> : null}
          {filtered.length && !filtered.some((a) => a.advisor_sid === sid) && advisor ? (
            <option value={sid}>
              {advisor.advisor_name || sid} ({sid}) · {advisor.rep_code}
            </option>
          ) : null}
        </select>
      </PageHeader>
      {error ? <EmptyState title="Page failed to load" message={error} /> : null}
      {sid ? <AdvisorBody key={sid} sid={sid} advisor={advisor} /> : null}
    </section>
  );
}

// ---------------------------------------------------------------------------

function AdvisorBody({ sid, advisor }: { sid: string; advisor: AdvisorListRow | null }) {
  const [months, setMonths] = useState<MonthRow[]>([]);
  const [transitions, setTransitions] = useState<Transition[]>([]);
  const [selected, setSelected] = useState(0);
  const [summary, setSummary] = useState<AdvisorSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getMonths(sid), getTransitions(sid)])
      .then(([m, t]) => {
        setMonths(m.months);
        setTransitions(t.transitions);
        setSelected(0);
      })
      .catch((e) => setError(String(e?.message || e)));
  }, [sid]);

  const transition = transitions[selected] ?? null;

  useEffect(() => {
    if (!transition) return;
    setSummary(null);
    getAdvisorSummary(sid, transition.from_month_id, transition.to_month_id)
      .then(setSummary)
      .catch(() => setSummary(null));
  }, [sid, transition]);

  const monthName = useCallback(
    (id: string) => months.find((m) => m.month_id === id)?.month_name ?? id,
    [months],
  );

  // chart props per the shared TransitionChart contract — advisor-scoped
  // months/transitions; AUM from the advisor summary, null when absent
  const chartMonths = useMemo(
    () =>
      months.map((m) => ({
        month_id: m.month_id,
        credited_amt: m.credited_amt,
        recurring_amt: m.recurring_amt,
        non_recurring_amt: m.non_recurring_amt,
        aum: summary?.aum_by_month?.[m.month_id] ?? null,
      })),
    [months, summary],
  );
  const chartTransitions = useMemo(
    () =>
      transitions.map((t) => ({
        from: t.from_month_id,
        to: t.to_month_id,
        change_amt: t.change_amt,
        change_pct: t.change_pct,
        direction: t.direction,
      })),
    [transitions],
  );

  return (
    <>
      {error ? <EmptyState title="Failed to load advisor data" message={error} /> : null}

      <Gated flag="advisor.chart_metrics">
        <div className="card">
          <div className="card-h">
            <div>
              <h2>
                {advisor ? `${advisor.advisor_name || sid} (${sid})` : sid}{" "}
                {summary ? (
                  <Chip
                    variant="tag"
                    title={
                      summary.team.is_team
                        ? `ACTIVE team agreement — team rep ${summary.team.team_rep_cd ?? "unknown"}`
                        : "No ACTIVE team agreement"
                    }
                  >
                    {summary.team.is_team
                      ? `Team${summary.team.team_rep_cd ? ` · ${summary.team.team_rep_cd}` : ""}`
                      : "Individual"}
                  </Chip>
                ) : null}{" "}
                {advisor?.rep_code ? (
                  <span style={{ fontSize: 12, color: "var(--slate)", fontWeight: 400 }}>
                    rep {advisor.rep_code}
                  </span>
                ) : null}
              </h2>
              <p>Select a transition arrow — it drives every section below.</p>
            </div>
          </div>
          <div className="card-b">
            {months.length ? (
              <TransitionChart
                months={chartMonths}
                transitions={chartTransitions}
                view="all"
                selected={selected}
                onSelect={setSelected}
                monthName={monthName}
              />
            ) : (
              <EmptyState title="No months loaded for this advisor" />
            )}
            <MetricsStrip summary={summary} transition={transition} monthName={monthName} />
          </div>
        </div>
      </Gated>

      <Gated flag="advisor.drivers">
        <DriversSection sid={sid} transitions={transitions} selected={selected} monthName={monthName} />
      </Gated>

      <Gated flag="advisor.peer_ranking">
        <PeerRankingSection sid={sid} transition={transition} monthName={monthName} />
      </Gated>

      <Gated flag="advisor.coaching">
        <CoachingSection sid={sid} transition={transition} monthName={monthName} />
      </Gated>

      <Gated flag="advisor.crm_opportunities">
        <OpportunitiesSection sid={sid} transition={transition} />
      </Gated>
      {/* 6.6 — deliberately NO exceptions count on this page */}
    </>
  );
}

// ------------------------------------------------------------------ metrics

function MetricsStrip({
  summary,
  transition,
  monthName,
}: {
  summary: AdvisorSummary | null;
  transition: Transition | null;
  monthName: (id: string) => string;
}) {
  if (!summary || !transition) {
    return <div style={{ color: "var(--slate)", fontSize: "12.5px" }}>Loading metrics…</div>;
  }
  const m = summary.metrics;
  return (
    <>
      <div className="mstrip" style={{ marginTop: 14 }}>
        <div>
          <div className="k">New Accounts</div>
          <div className="v">{m.lifecycle.new_count}</div>
        </div>
        <div>
          <div className="k">Lost Accounts</div>
          <div className="v">{m.lifecycle.lost_count}</div>
        </div>
        <div>
          <div className="k">Retained Accounts</div>
          <div className="v">{m.lifecycle.retained_count}</div>
        </div>
        <div>
          <div className="k">AUM</div>
          <div className="v">{m.aum ? money(m.aum.total_balance) : "—"}</div>
          <div className="d">
            {m.aum && m.aum.change_amt !== null ? (
              <>
                <Delta value={m.aum.change_amt} /> vs prior month
              </>
            ) : (
              <span className="mut">no prior month</span>
            )}
          </div>
        </div>
        <div>
          <div className="k">NCF (net credited flows)</div>
          <div className="v">{m.ncf ? money(m.ncf.net_flows) : "—"}</div>
          {m.ncf ? (
            <div className="d mut">
              {money(m.ncf.inflows)} in · {money(m.ncf.outflows)} out
            </div>
          ) : null}
        </div>
        <div>
          <div className="k">Total Trades ({monthName(transition.to_month_id)})</div>
          <div className="v">{m.trades.to_count.toLocaleString("en-US")}</div>
          <div className="d">
            <Delta value={m.trades.delta} kind="count" /> vs {monthName(transition.from_month_id)}
          </div>
        </div>
      </div>

      {/* NNM — BOTH figures, clearly labelled (6.3) */}
      <div className="mstrip" style={{ marginTop: 10 }}>
        <div>
          <div className="k">NNM YTD (from {monthName(m.nnm.ytd.first_month ?? "")} — first loaded month)</div>
          <div className="v">
            <Money value={m.nnm.ytd.amount} />
          </div>
        </div>
        <div>
          <div className="k">
            NNM in scope ({monthName(transition.from_month_id)}→{monthName(transition.to_month_id)})
          </div>
          <div className="v">
            <Money value={m.nnm.in_scope.amount} />
          </div>
        </div>
        {m.nnm.by_product.map((p) => (
          <div key={p.flow_product_cd}>
            <div className="k">
              {p.flow_product_cd === "MGDF" ? "Managed" : p.flow_product_cd === "BRKF" ? "Brokerage" : p.flow_product_cd}{" "}
              net flows
            </div>
            <div className="v" style={{ fontSize: 15 }}>
              <Money value={p.net_flows} />
            </div>
          </div>
        ))}
      </div>
      <div className="note" style={{ marginTop: 8 }}>
        {m.nnm.categories_note}.{" "}
        <Chip variant="derived" title={m.nnm.qualification_note}>
          ASSUMED
        </Chip>{" "}
        Any $4MM qualification statement rests on an unconfirmed assumption.
      </div>
      {m.lifecycle.notes ? (
        <div className="note" style={{ marginTop: 4 }}>{m.lifecycle.notes}</div>
      ) : null}
    </>
  );
}

// ------------------------------------------------------------------ drivers

type Pivot = "driver" | "product";

function groupFindings(findings: Finding[], pivot: Pivot): Map<string, Finding[]> {
  const map = new Map<string, Finding[]>();
  for (const f of findings) {
    const key = pivot === "product" ? f.group_id || "No product" : f.driver_tag || "Other";
    map.set(key, [...(map.get(key) ?? []), f]);
  }
  return map;
}

function DriverList({ run, pivot }: { run: InsightRun | null; pivot: Pivot }) {
  if (!run || run.status !== "COMPLETE") {
    return (
      <div style={{ padding: "14px 15px" }}>
        <EmptyState
          title="No stored run for this transition"
          message="Generate this advisor's insights from the dashboard's AI Insights section first — this page renders the stored findings."
        />
      </div>
    );
  }
  const groups = groupFindings(run.findings, pivot);
  return (
    <>
      <LimitNotice limits={run.limits_hit} />
      {Array.from(groups.entries()).map(([label, fs]) => (
        <div key={label}>
          <div
            style={{
              padding: "8px 15px",
              background: "var(--panel)",
              fontWeight: 600,
              fontSize: 12,
              color: "var(--slate)",
              borderBottom: "1px solid var(--rule-2)",
            }}
          >
            {label}
          </div>
          {fs.map((f, i) => (
            <FindingRow key={f.finding_id ?? i} finding={f} />
          ))}
        </div>
      ))}
      {!run.findings.length ? (
        <div style={{ padding: "14px 15px", color: "var(--slate)", fontSize: "12.5px" }}>
          Run stored, no findings for this transition.
        </div>
      ) : null}
    </>
  );
}

function useStoredRun(sid: string, transition: Transition | null): InsightRun | null {
  const [run, setRun] = useState<InsightRun | null>(null);
  useEffect(() => {
    setRun(null);
    if (!transition) return;
    getInsights(sid, transition.from_month_id, transition.to_month_id)
      .then(setRun)
      .catch(() => setRun(null)); // no run yet / flag off — honest empty state
  }, [sid, transition]);
  return run;
}

function DriversSection({
  sid,
  transitions,
  selected,
  monthName,
}: {
  sid: string;
  transitions: Transition[];
  selected: number;
  monthName: (id: string) => string;
}) {
  const [mode, setMode] = useState<"single" | "compare">("single");
  const [pivot, setPivot] = useState<Pivot>("driver");
  const transition = transitions[selected] ?? null;
  const otherOptions = transitions.filter((_t, i) => i !== selected);
  const [otherKey, setOtherKey] = useState<string>("");
  const other =
    otherOptions.find((t) => `${t.from_month_id}|${t.to_month_id}` === otherKey) ??
    otherOptions[0] ??
    null;

  const run = useStoredRun(sid, transition);
  const otherRun = useStoredRun(sid, mode === "compare" ? other : null);

  const label = (t: Transition | null) =>
    t ? `${monthName(t.from_month_id)} → ${monthName(t.to_month_id)}` : "—";

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <h2>Drivers</h2>
          <p>
            The advisor&apos;s stored findings — {label(transition)}. Every finding keeps its rule and
            document citation.
          </p>
        </div>
        <div className="ctl">
          <div className="pivot">
            <button aria-selected={mode === "single"} onClick={() => setMode("single")}>
              Single Transition
            </button>
            <Gated flag="advisor.compare">
              <button aria-selected={mode === "compare"} onClick={() => setMode("compare")}>
                Compare Two Transitions
              </button>
            </Gated>
          </div>
          <div className="pivot">
            <button aria-selected={pivot === "driver"} onClick={() => setPivot("driver")}>
              By Driver
            </button>
            <button aria-selected={pivot === "product"} onClick={() => setPivot("product")}>
              By Product
            </button>
          </div>
          {mode === "compare" ? (
            <select
              value={other ? `${other.from_month_id}|${other.to_month_id}` : ""}
              onChange={(e) => setOtherKey(e.target.value)}
              aria-label="Second transition"
            >
              {otherOptions.map((t) => (
                <option key={`${t.from_month_id}|${t.to_month_id}`} value={`${t.from_month_id}|${t.to_month_id}`}>
                  {label(t)} {arrow(t.change_amt)} {money(t.change_amt)}
                </option>
              ))}
            </select>
          ) : null}
        </div>
      </div>
      <div className="card-b" style={{ padding: mode === "compare" ? 16 : 0 }}>
        {mode === "single" ? (
          <DriverList run={run} pivot={pivot} />
        ) : (
          <Gated flag="advisor.compare">
            <div className="two">
              {[
                { t: transition, r: run },
                { t: other, r: otherRun },
              ].map(({ t, r }, i) => (
                <div key={i} className="tcard" style={{ overflow: "hidden" }}>
                  <h3 style={{ padding: "10px 15px 0" }}>
                    {label(t)} {t ? <Delta value={t.change_amt} /> : null}{" "}
                    {t ? <span style={{ color: "var(--slate)", fontWeight: 400 }}>{percent(t.change_pct)}</span> : null}
                  </h3>
                  <DriverList run={r} pivot={pivot} />
                </div>
              ))}
            </div>
          </Gated>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------- peer ranking

function RankCard({
  title,
  block,
  prominent,
  valueKind,
}: {
  title: string;
  block: { rank: number | null; cohort_size: number; value: number | null; cohort_median: number | null; note?: string };
  prominent?: boolean;
  valueKind: "money" | "pct";
}) {
  const fmt = (v: number | null) => (v === null ? "—" : valueKind === "money" ? money(v) : percent(v));
  return (
    <div
      style={{
        border: prominent ? "2px solid var(--navy)" : "1px solid var(--rule)",
        borderRadius: 6,
        padding: "12px 14px",
        background: prominent ? "var(--panel)" : "#fff",
      }}
    >
      <div className="k" style={{ fontSize: 11, letterSpacing: ".03em", color: "var(--slate)", textTransform: "uppercase" }}>
        {title}
      </div>
      <div style={{ fontSize: prominent ? 24 : 20, fontWeight: 600, marginTop: 4 }}>
        {block.rank !== null ? `#${block.rank}` : "—"}
        <span style={{ fontSize: 13, fontWeight: 400, color: "var(--slate)" }}> of {block.cohort_size}</span>
      </div>
      <div style={{ fontSize: "12.5px", marginTop: 4 }}>
        {block.rank !== null || block.value !== null ? (
          <>
            This advisor: <b>{fmt(block.value)}</b> · cohort median {fmt(block.cohort_median)}
          </>
        ) : (
          <span style={{ color: "var(--slate)" }}>Not ranked — no qualifying data this month.</span>
        )}
      </div>
      {block.note ? <div style={{ fontSize: 11.5, color: "var(--slate)", marginTop: 5 }}>{block.note}</div> : null}
    </div>
  );
}

function PeerRankingSection({
  sid,
  transition,
  monthName,
}: {
  sid: string;
  transition: Transition | null;
  monthName: (id: string) => string;
}) {
  const [ranking, setRanking] = useState<AdvisorPeerRanking | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setRanking(null);
    setError(null);
    if (!transition) return;
    getAdvisorPeerRanking(sid, transition.from_month_id, transition.to_month_id)
      .then(setRanking)
      .catch((e) => setError(String(e?.message || e)));
  }, [sid, transition]);

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <h2>Peer Ranking</h2>
          <p>
            Where this advisor sits in the cohort
            {transition ? ` — ${monthName(transition.to_month_id)}` : ""}. Discount rate is the metric
            nobody volunteers about themselves.
          </p>
        </div>
      </div>
      <div className="card-b">
        {error ? <EmptyState title="Peer ranking unavailable" message={error} /> : null}
        {ranking ? (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1.3fr", gap: 14 }}>
            <RankCard title="By Revenue" block={ranking.revenue} valueKind="money" />
            <RankCard title="By Growth" block={ranking.growth} valueKind="money" />
            <RankCard title="By Discount Rate" block={ranking.discount_rate} valueKind="pct" prominent />
          </div>
        ) : !error ? (
          <div style={{ color: "var(--slate)", fontSize: "12.5px" }}>Loading ranking…</div>
        ) : null}
      </div>
    </div>
  );
}

// ----------------------------------------------------------------- coaching

function CitationLine({ c }: { c: { document_name: string | null; page_no: number | null; section_path: string | null } }) {
  if (!c.document_name) return null;
  return (
    <a className="src" href={`/documents?doc=${encodeURIComponent(c.document_name)}`}>
      {c.document_name}
      {c.page_no != null ? ` · p.${c.page_no}` : ""}
      {c.section_path ? ` · ${c.section_path}` : ""}
    </a>
  );
}

function CoachingSection({
  sid,
  transition,
  monthName,
}: {
  sid: string;
  transition: Transition | null;
  monthName: (id: string) => string;
}) {
  const [result, setResult] = useState<CoachingResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!transition) return;
    getCoaching(sid, transition.from_month_id, transition.to_month_id)
      .then(setResult)
      .catch((e) => {
        setResult(null);
        setError(String(e?.message || e));
      });
  }, [sid, transition]);
  useEffect(() => {
    setResult(null);
    setError(null);
    load();
  }, [load]);

  const generate = async () => {
    if (!transition) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await generateCoaching(sid, transition.from_month_id, transition.to_month_id));
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const generated = result?.generated !== false && (result?.points?.length || result?.generated_at);

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <h2>
            Coaching <Chip variant="aigen">◆ AI Generated</Chip>
          </h2>
          <p>
            Retrieved guidance-document facts and their implications — Level 2 only, nothing invented. A
            point with no document citation is dropped server-side.
          </p>
        </div>
        <div className="ctl">
          {result?.generated_at ? (
            <span style={{ fontSize: 12, color: "var(--slate)" }}>generated {result.generated_at}</span>
          ) : null}
          <button className="btn primary" onClick={generate} disabled={busy || !transition}>
            {busy ? "generating…" : generated ? "↻ Re-Generate Coaching" : "Generate Coaching"}
          </button>
        </div>
      </div>
      <div className="card-b">
        {error ? <EmptyState title="Coaching unavailable" message={error} /> : null}
        {result && result.points.length ? (
          result.points.map((p, i) => (
            <div key={i} style={{ borderBottom: "1px solid var(--rule-2)", padding: "10px 2px" }}>
              <blockquote
                style={{
                  margin: 0,
                  padding: "8px 12px",
                  borderLeft: "3px solid var(--ai, #4C4EA3)",
                  background: "var(--panel)",
                  fontSize: "12.5px",
                  color: "var(--slate)",
                }}
              >
                “{p.citation.excerpt}”
                <div style={{ marginTop: 5 }}>
                  <CitationLine c={p.citation} />
                </div>
              </blockquote>
              <div style={{ marginTop: 7, fontSize: "13px" }}>{p.fact}</div>
              <div style={{ marginTop: 4, fontSize: "12.5px", color: "var(--slate)" }}>
                <b style={{ color: "var(--ink)" }}>Implication:</b> {p.implication}
              </div>
            </div>
          ))
        ) : result ? (
          <EmptyState
            title={result.generated === false ? "No coaching generated yet" : "No coaching points"}
            message={
              result.note ??
              (result.generated === false
                ? `Generate Coaching runs the Coach agent for ${sid} on ${
                    transition ? `${monthName(transition.from_month_id)} → ${monthName(transition.to_month_id)}` : "this transition"
                  } — retrieval from GUIDANCE documents plus one Haiku call.`
                : "Every candidate point was dropped by the citation gate — nothing citation-less is shown.")
            }
          />
        ) : !error ? (
          <div style={{ color: "var(--slate)", fontSize: "12.5px" }}>Loading…</div>
        ) : null}
        {result?.dropped?.length ? (
          <div className="note" style={{ marginTop: 8 }}>
            {result.dropped.length} candidate point{result.dropped.length > 1 ? "s" : ""} dropped by the
            citation gate (no resolvable citation or unverifiable figures).
          </div>
        ) : null}
        {result?.limits?.length
          ? result.limits.map((l, i) => (
              <div key={i} className="note" style={{ marginTop: 4 }}>
                {l.limit_name}: {l.limit_effect}
              </div>
            ))
          : null}
      </div>
    </div>
  );
}

// ------------------------------------------------------------ opportunities

const STATUS_ORDER = ["Won", "Lost", "Pending"];

function OpportunitiesSection({ sid, transition }: { sid: string; transition: Transition | null }) {
  const [opps, setOpps] = useState<OpportunitiesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setOpps(null);
    setError(null);
    getOpportunities(sid, transition?.from_month_id, transition?.to_month_id)
      .then(setOpps)
      .catch((e) => setError(String(e?.message || e)));
  }, [sid, transition]);

  const rows = opps
    ? STATUS_ORDER.flatMap((s) => opps.by_status[s] ?? []).concat(opps.other)
    : [];

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <h2>
            Opportunities <Chip variant="dummy" title="Placeholder feed — every row is synthetic until the real CRM feed arrives">Dummy Data</Chip>
          </h2>
          <p>CRM pipeline by status, joined through the household relationship.</p>
        </div>
      </div>
      <div className="card-b" style={{ padding: 0 }}>
        {error ? (
          <div style={{ padding: 16 }}>
            <EmptyState title="Opportunities unavailable" message={error} />
          </div>
        ) : rows.length ? (
          <>
            <div style={{ overflowX: "auto" }}>
              <table className="exc">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Stage</th>
                    <th className="num">Opportunities</th>
                    <th className="num">Amount</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i}>
                      <td>
                        <Chip variant={r.status.toLowerCase() === "won" ? "pos" : r.status.toLowerCase() === "lost" ? "neg" : "tag"}>
                          {r.status || "—"}
                        </Chip>
                      </td>
                      <td>{r.stage || "—"}</td>
                      <td className="num">{r.opportunity_count}</td>
                      <td className="num">
                        <Money value={r.total_amount} />
                      </td>
                      <td>
                        <Chip variant="dummy" title="data_source = DUMMY">Dummy Data</Chip>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {opps?.guidance?.document_name ? (
              <div className="note">
                Guidance: “{opps.guidance.excerpt?.slice(0, 220)}…” — <CitationLine c={opps.guidance} />
              </div>
            ) : (
              <div className="note">No document-derived guidance attached for this pipeline.</div>
            )}
          </>
        ) : opps ? (
          <div style={{ padding: 16 }}>
            <EmptyState title="No opportunities in the feed for this advisor" />
          </div>
        ) : (
          <div style={{ padding: 16, color: "var(--slate)", fontSize: "12.5px" }}>Loading…</div>
        )}
      </div>
    </div>
  );
}
