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
import { publishChatContext } from "@/lib/chatContext";
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
  type NnmCategory,
  type NnmResponse,
  type OpportunitiesResponse,
  type OpportunityDetailRow,
  generateCoaching,
  getAdvisorList,
  getAdvisorNnm,
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

  // Round E 6.2 — publish the selected advisor + transition to the chat panel
  // (a hint, never a filter). One call, in the existing selection-change path.
  useEffect(() => {
    const who = advisor?.advisor_name?.trim() ? `${advisor.advisor_name.trim()} (${sid})` : sid;
    publishChatContext({
      page: "advisor",
      advisor_sid: sid,
      advisor_name: advisor?.advisor_name || "",
      from_month: transition?.from_month_id,
      to_month: transition?.to_month_id,
      label: transition
        ? `${who} · ${monthName(transition.from_month_id)} → ${monthName(transition.to_month_id)}`
        : who,
    });
  }, [sid, advisor, transition, monthName]);

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
            <NnmStrip sid={sid} />
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

      {m.lifecycle.notes ? (
        <div className="note" style={{ marginTop: 4 }}>{m.lifecycle.notes}</div>
      ) : null}
    </>
  );
}

// ------------------------------------------------------- NNM strip (Round F2)
// The four real categories from the NNM files (Managed/Brokerage split
// REMOVED — it was an A2B placeholder). EC is prominent against the threshold
// the API resolves from the EXTRACTED plan rule; nothing is hardcoded here.

function categoryTooltip(c: NnmCategory): string {
  return c.confirmed
    ? `${c.label} — confirmed by the plan document (source file ${c.category_source}_*)`
    : `${c.label} — category inferred from the source filename ${c.category_source}_*`;
}

function NnmStrip({ sid }: { sid: string }) {
  const [nnm, setNnm] = useState<NnmResponse | null>(null);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  useEffect(() => {
    setNnm(null);
    setError(null);
    getAdvisorNnm(sid)
      .then(setNnm)
      .catch((e) => setError({ status: (e as { status?: number })?.status ?? 0, message: String((e as Error)?.message || e) }));
  }, [sid]);

  if (error) {
    // 409 = feature flag off — absent, like every other gated section
    if (error.status === 409) return null;
    return (
      <div className="note" style={{ marginTop: 10 }}>
        NNM unavailable: {error.message}
      </div>
    );
  }
  if (!nnm) {
    return <div style={{ color: "var(--slate)", fontSize: "12.5px", marginTop: 10 }}>Loading NNM…</div>;
  }

  const ec = nnm.categories.find((c) => c.category === "EC") ?? null;
  const rest = nnm.categories.filter((c) => c.category !== "EC");
  const t = nnm.threshold;

  if (!nnm.categories.length) {
    return (
      <div className="note" style={{ marginTop: 10 }}>
        {nnm.note || `No NNM rows in the feed for this advisor (as of ${nnm.as_of_label}).`}
      </div>
    );
  }

  return (
    <>
      <div className="mstrip" style={{ marginTop: 10 }}>
        {ec ? (
          <div title={categoryTooltip(ec)} style={{ borderLeft: "3px solid var(--navy)", paddingLeft: 9 }}>
            <div className="k">Existing Client (EC) NNM YTD — as of {nnm.as_of_label}</div>
            <div className="v">
              <Money value={ec.ytd_nnm} />
            </div>
            <div className="d mut">
              MTD <Money value={ec.mtd_nnm} />
            </div>
          </div>
        ) : null}
        {rest.map((c) => (
          <div key={c.category} title={categoryTooltip(c)}>
            <div className="k">
              {c.label} ({c.category}) YTD
            </div>
            <div className="v" style={{ fontSize: 15 }}>
              <Money value={c.ytd_nnm} />
            </div>
            <div className="d mut">
              MTD <Money value={c.mtd_nnm} />
            </div>
          </div>
        ))}
        <div>
          <div className="k">Total NNM (all four categories) YTD</div>
          <div className="v" style={{ fontSize: 15 }}>
            <Money value={nnm.total.ytd_nnm} />
          </div>
          <div className="d mut">
            MTD <Money value={nnm.total.mtd_nnm} />
          </div>
        </div>
      </div>
      <div className="note" style={{ marginTop: 8 }}>
        {t.available && t.threshold_amt !== null ? (
          <>
            EC YTD <Money value={t.ytd_nnm ?? 0} /> vs the <Money value={t.threshold_amt} /> threshold
            {" — "}
            {t.qualifies ? (
              <>at or above the threshold</>
            ) : (
              <>
                gap <Money value={t.gap ?? 0} /> below the threshold
              </>
            )}
            {t.as_of_month ? ` (as of ${nnm.as_of_label})` : ""}.{" "}
            <Chip variant="derived" title={t.assumed_note}>
              ASSUMED
            </Chip>{" "}
            The threshold figure comes from the extracted plan rule{t.rule_key ? ` (${t.rule_key})` : ""},
            measured on {t.measured_category} flows.
          </>
        ) : (
          <>{t.note || "No published plan rule states the NNM threshold yet — nothing is assumed in its place."}</>
        )}
      </div>
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

// ------------------------------------------------- opportunities (Round F2 CRM)

const STAGE_GROUP_ORDER = ["EARLY", "MID", "LATE", "CLOSING"];
const STAGE_GROUP_LABELS: Record<string, string> = {
  EARLY: "Early",
  MID: "Mid",
  LATE: "Late",
  CLOSING: "Closing",
};

/** The AI Read cell — the same purple ◆ AI treatment as every AI-generated
 * element. Descriptive only: this column never sorts, filters, or totals. */
function AiReadCell({ row }: { row: OpportunityDetailRow }) {
  if (!row.ai_read) {
    return <span className="mut" style={{ color: "var(--slate)", fontSize: 12 }}>No signal</span>;
  }
  const conf =
    row.ai_read_confidence != null ? `confidence ${Math.round(row.ai_read_confidence * 100)}%` : "confidence unknown";
  const evidence = row.ai_read_evidence ? ` — evidence: “${row.ai_read_evidence}”` : "";
  return (
    <Chip variant="aigen" title={`${conf}${evidence}`}>
      ◆ AI {row.ai_read}
    </Chip>
  );
}

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

  const groups = opps
    ? [...opps.by_stage_group].sort(
        (a, b) => STAGE_GROUP_ORDER.indexOf(a.stage_group) - STAGE_GROUP_ORDER.indexOf(b.stage_group),
      )
    : [];
  const stalledTotal = groups.reduce((n, g) => n + (g.stalled_count || 0), 0);
  const guidance = opps?.opportunities_guidance ?? opps?.guidance ?? null;

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <h2>Opportunities</h2>
          <p>CRM pipeline by stage group, joined through the household relationship.</p>
        </div>
      </div>
      <div className="card-b" style={{ padding: 0 }}>
        {error ? (
          <div style={{ padding: 16 }}>
            <EmptyState title="Opportunities unavailable" message={error} />
          </div>
        ) : opps && (groups.length || opps.opportunities.length) ? (
          <>
            <div style={{ overflowX: "auto" }}>
              <table className="exc">
                <thead>
                  <tr>
                    <th>Stage Group</th>
                    <th className="num">Opportunities</th>
                    <th className="num">Forecast Amount</th>
                    <th className="num">Actual Assets</th>
                    <th className="num">Stalled</th>
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => (
                    <tr key={g.stage_group}>
                      <td>{STAGE_GROUP_LABELS[g.stage_group] ?? g.stage_group}</td>
                      <td className="num">{g.opportunity_count}</td>
                      <td className="num">
                        <Money value={g.forecast_amount} />
                      </td>
                      <td className="num">
                        <Money value={g.actual_assets} />
                      </td>
                      <td className="num">
                        {g.stalled_count > 0 ? <b style={{ color: "var(--neg, #B3261E)" }}>{g.stalled_count}</b> : 0}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="note">{opps.won_lost_note}</div>
            <div className="note">{opps.assumption_note}</div>
            {opps.data_quality?.invalid_advisor_rows > 0 ? (
              <div className="note" style={{ color: "var(--sev-high-tx, #9A5B13)" }}>
                {opps.data_quality.note ||
                  `${opps.data_quality.invalid_advisor_rows} opportunity row(s) carry an invalid advisor reference in the source — shown, not hidden.`}
              </div>
            ) : null}
            {stalledTotal > 0 ? (
              <div className="note">
                <b>{stalledTotal} stalled opportunit{stalledTotal === 1 ? "y" : "ies"}</b> — the anticipated
                close date has passed (days to close is negative in the source).
              </div>
            ) : null}
            {opps.opportunities.length ? (
              <div style={{ overflowX: "auto" }}>
                <table className="exc">
                  <thead>
                    <tr>
                      <th>Household</th>
                      <th>Stage</th>
                      <th className="num">Days to Close</th>
                      <th className="num">Forecast</th>
                      <th className="num">Actual Assets</th>
                      <th>Notes</th>
                      {/* AI Read: descriptive only — deliberately not sortable or filterable */}
                      <th>AI Read</th>
                    </tr>
                  </thead>
                  <tbody>
                    {opps.opportunities.map((r) => (
                      <tr key={r.opportunity_id}>
                        <td>
                          <span style={{ fontFamily: "var(--mono, ui-monospace, monospace)", fontSize: 12 }} title={`Household ECI ${r.eci_id}`}>
                            {r.eci_id || "—"}
                          </span>
                          {!r.advisor_valid ? (
                            <>
                              {" "}
                              <Chip variant="neg" title="ownersid__c carried an invalid advisor reference in the source extract">
                                invalid advisor ref
                              </Chip>
                            </>
                          ) : null}
                        </td>
                        <td>{r.stage_name || "—"}</td>
                        <td className="num">
                          {r.days_to_close == null ? (
                            "—"
                          ) : r.is_stalled ? (
                            <Chip variant="neg" title="Anticipated close date passed — days_to_close is negative in the source">
                              Stalled · {-r.days_to_close}d past due
                            </Chip>
                          ) : (
                            r.days_to_close
                          )}
                        </td>
                        <td className="num">
                          <Money value={r.amount} />
                        </td>
                        <td className="num">
                          <Money value={r.actual_assets} />
                        </td>
                        <td style={{ maxWidth: 220 }}>
                          <span title={r.comments || undefined} style={{ fontSize: 12 }}>
                            {r.comments ? (r.comments.length > 60 ? `${r.comments.slice(0, 60)}…` : r.comments) : "—"}
                          </span>
                        </td>
                        <td>
                          <AiReadCell row={r} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {guidance?.document_name ? (
              <div className="note">
                Guidance: “{guidance.excerpt?.slice(0, 220)}…” — <CitationLine c={guidance} />
              </div>
            ) : null}
          </>
        ) : opps ? (
          <div style={{ padding: 16 }}>
            <EmptyState title="No opportunities in the CRM extract for this advisor" />
          </div>
        ) : (
          <div style={{ padding: 16, color: "var(--slate)", fontSize: "12.5px" }}>Loading…</div>
        )}
      </div>
    </div>
  );
}
