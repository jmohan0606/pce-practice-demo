"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import TransitionChart from "@/components/chart/TransitionChart";
import Chip from "@/components/Chip";
import ColHead from "@/components/advisor/ColHead";
import SeverityChip from "@/components/advisor/SeverityChip";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import { FindingRow, LimitNotice } from "@/components/InsightPanel";
import { CompareValue } from "@/components/CompareValue";
import { Delta, Money } from "@/components/Num";
import { Pager, usePager } from "@/components/Pager";
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
  // Round 7 task 10 — the cascading filter (client req of 17 Aug):
  // Job Code / Display Name → Work State → Work City → Advisor.
  // "" = all; "__BLANK__" selects advisors whose value is blank (a blank stays
  // blank — never invented, and never a reason to hide an advisor).
  const [jobFilter, setJobFilter] = useState("");
  const [stateFilter, setStateFilter] = useState("");
  const [cityFilter, setCityFilter] = useState("");
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

  const matchesLevel = (value: string | undefined, filter: string) =>
    !filter || (filter === "__BLANK__" ? !(value || "") : (value || "") === filter);

  // Each cascade level's options derive from the advisors the EARLIER levels
  // leave — each level narrows the next. A blank value gets an explicit
  // "(blank)" option so those advisors stay reachable, never hidden.
  const jobOptions = useMemo(() => {
    const byCode = new Map<string, string>();
    for (const a of advisors) byCode.set(a.job_code || "", a.job_display_name || "");
    return [...byCode.entries()].sort((x, y) => (x[1] || x[0]).localeCompare(y[1] || y[0]));
  }, [advisors]);
  const afterJob = useMemo(
    () => advisors.filter((a) => matchesLevel(a.job_code, jobFilter)),
    [advisors, jobFilter],
  );
  const stateOptions = useMemo(
    () => [...new Set(afterJob.map((a) => a.work_state || ""))].sort(),
    [afterJob],
  );
  const afterState = useMemo(
    () => afterJob.filter((a) => matchesLevel(a.work_state, stateFilter)),
    [afterJob, stateFilter],
  );
  const cityOptions = useMemo(
    () => [...new Set(afterState.map((a) => a.work_city || ""))].sort(),
    [afterState],
  );
  const afterCity = useMemo(
    () => afterState.filter((a) => matchesLevel(a.work_city, cityFilter)),
    [afterState, cityFilter],
  );

  // 6.1 — search filters by name, SID, or rep code (on top of the cascade)
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return afterCity;
    return afterCity.filter(
      (a) =>
        a.advisor_name.toLowerCase().includes(q) ||
        a.advisor_sid.toLowerCase().includes(q) ||
        a.rep_code.toLowerCase().includes(q),
    );
  }, [afterCity, search]);

  const advisor = advisors.find((a) => a.advisor_sid === sid) ?? null;

  return (
    <section>
      <PageHeader
        title="iPerform Advisor AI Insights"
        meta="One advisor's transitions, drivers, peer position and coaching — every figure a stored query result"
      >
        {/* Round 7 task 10 — Job Code / Display Name → Work State → Work City →
            Advisor. Each level narrows the next; changing a level resets the
            levels below it. Display names come from the client's mapping
            (job_display_name); an unmapped code shows as the raw code. */}
        <select
          value={jobFilter}
          onChange={(e) => {
            setJobFilter(e.target.value);
            setStateFilter("");
            setCityFilter("");
          }}
          aria-label="Job code / display name"
        >
          <option value="">All job codes</option>
          {jobOptions.map(([code, name]) => (
            <option key={code || "__BLANK__"} value={code || "__BLANK__"}>
              {code === ""
                ? "(blank job code)"
                : name && name !== code
                  ? `${name} (${code})`
                  : code}
            </option>
          ))}
        </select>
        <select
          value={stateFilter}
          onChange={(e) => {
            setStateFilter(e.target.value);
            setCityFilter("");
          }}
          aria-label="Work state"
        >
          <option value="">All states</option>
          {stateOptions.map((s) => (
            <option key={s || "__BLANK__"} value={s || "__BLANK__"}>
              {s === "" ? "(blank state)" : s}
            </option>
          ))}
        </select>
        <select
          value={cityFilter}
          onChange={(e) => setCityFilter(e.target.value)}
          aria-label="Work city"
        >
          <option value="">All cities</option>
          {cityOptions.map((c) => (
            <option key={c || "__BLANK__"} value={c || "__BLANK__"}>
              {c === "" ? "(blank city)" : c}
            </option>
          ))}
        </select>
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
  const [priorSummary, setPriorSummary] = useState<AdvisorSummary | null>(null);
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
  // The transition ending where the selected one begins — the prior period
  // every count on the metrics strip compares against (review A2).
  const priorTransition = useMemo(
    () =>
      transition
        ? (transitions.find((t) => t.to_month_id === transition.from_month_id) ?? null)
        : null,
    [transitions, transition],
  );

  useEffect(() => {
    if (!transition) return;
    setSummary(null);
    getAdvisorSummary(sid, transition.from_month_id, transition.to_month_id)
      .then(setSummary)
      .catch(() => setSummary(null));
  }, [sid, transition]);

  useEffect(() => {
    setPriorSummary(null);
    if (!priorTransition) return;
    getAdvisorSummary(sid, priorTransition.from_month_id, priorTransition.to_month_id)
      .then(setPriorSummary)
      .catch(() => setPriorSummary(null));
  }, [sid, priorTransition]);

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
  // months/transitions. Review B1: AUM is REMOVED from the bar chart — the
  // aum prop is null for every month and the shared component's per-month
  // AUM label is hidden by the scoped style below (the chart component is
  // shared and not owned by this page).
  const chartMonths = useMemo(
    () =>
      months.map((m) => ({
        month_id: m.month_id,
        credited_amt: m.credited_amt,
        recurring_amt: m.recurring_amt,
        non_recurring_amt: m.non_recurring_amt,
        aum: null,
      })),
    [months],
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
            {/* B1 — no per-month AUM series/labels on the advisor bar chart */}
            <style>{`.advchart .baum{display:none}`}</style>
            {months.length ? (
              <div className="advchart">
                <TransitionChart
                  months={chartMonths}
                  transitions={chartTransitions}
                  view="all"
                  selected={selected}
                  onSelect={setSelected}
                  monthName={monthName}
                />
              </div>
            ) : (
              <EmptyState title="No months loaded for this advisor" />
            )}
            <MetricsStrip
              summary={summary}
              priorSummary={priorSummary}
              transition={transition}
              priorTransition={priorTransition}
              monthName={monthName}
            />
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
  priorSummary,
  transition,
  priorTransition,
  monthName,
}: {
  summary: AdvisorSummary | null;
  priorSummary: AdvisorSummary | null;
  transition: Transition | null;
  priorTransition: Transition | null;
  monthName: (id: string) => string;
}) {
  if (!summary || !transition) {
    return <div style={{ color: "var(--slate)", fontSize: "12.5px" }}>Loading metrics…</div>;
  }
  const m = summary.metrics;
  const p = priorSummary?.metrics ?? null;
  // Prior-period label for the lifecycle counts: the prior transition's
  // to-month (each count is measured at its transition's to-month).
  const priorLabel = priorTransition ? monthName(priorTransition.to_month_id) : undefined;
  const managed = m.aum_managed ?? null;
  return (
    <>
      <div className="mstrip" style={{ marginTop: 14 }}>
        <div>
          <div className="k">New Accounts</div>
          <div className="v">
            <CompareValue
              current={m.lifecycle.new_count}
              prior={p?.lifecycle.new_count ?? null}
              kind="count"
              priorLabel={priorLabel}
            />
          </div>
        </div>
        <div>
          <div className="k">Lost Accounts</div>
          <div className="v">
            <CompareValue
              current={m.lifecycle.lost_count}
              prior={p?.lifecycle.lost_count ?? null}
              kind="count"
              priorLabel={priorLabel}
            />
          </div>
        </div>
        <div>
          <div className="k">Retained Accounts</div>
          <div className="v">
            <CompareValue
              current={m.lifecycle.retained_count}
              prior={p?.lifecycle.retained_count ?? null}
              kind="count"
              priorLabel={priorLabel}
            />
          </div>
        </div>
        {/* Review B1/D2 — AUM is Managed Accounts only, labelled as such.
            When the advisor has no managed account rows the tile is absent. */}
        {managed ? (
          <div>
            <div className="k">AUM (Managed Accounts only)</div>
            <div className="v">
              <CompareValue
                current={managed.total_balance}
                prior={managed.prior_balance}
                kind="money"
                priorLabel={monthName(transition.from_month_id)}
              />
            </div>
          </div>
        ) : null}
        <div>
          <div className="k">
            <ColHead
              code="metric.ncf"
              label="NCF (Net Cash Flows)"
              fallback="Net Cash Flows — inflows minus outflows from the advisor flows table (the source's total net financial flows, real cash movement, not credited revenue)."
            />
          </div>
          <div className="v">
            <CompareValue
              current={m.ncf?.net_flows ?? null}
              prior={p?.ncf?.net_flows ?? null}
              kind="money"
              priorLabel={priorLabel}
            />
          </div>
          {m.ncf ? (
            <div className="d mut">
              {money(m.ncf.inflows)} in · {money(m.ncf.outflows)} out
            </div>
          ) : null}
        </div>
        <div>
          <div className="k">Total Trades ({monthName(transition.to_month_id)})</div>
          <div className="v">
            <CompareValue
              current={m.trades.to_count}
              prior={m.trades.from_count}
              kind="count"
              priorLabel={monthName(transition.from_month_id)}
            />
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
// Review D5 — the section carries a clear title and a subtitle naming what it
// shows. Review A2/A4 — no ASSUMED tag, no category-availability commentary:
// categories present in the feed render; absent ones are simply not there.

function NnmStrip({ sid }: { sid: string }) {
  const [nnm, setNnm] = useState<NnmResponse | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setNnm(null);
    setFailed(false);
    getAdvisorNnm(sid)
      .then(setNnm)
      .catch(() => setFailed(true)); // flag off or unavailable — section absent
  }, [sid]);

  if (failed) return null;
  if (!nnm) {
    return <div style={{ color: "var(--slate)", fontSize: "12.5px", marginTop: 10 }}>Loading NNM…</div>;
  }
  // No NNM rows for this advisor — the section is simply not there (A4).
  if (!nnm.categories.length) return null;

  const ec = nnm.categories.find((c) => c.category === "EC") ?? null;
  const rest = nnm.categories.filter((c) => c.category !== "EC");
  const t = nnm.threshold;

  return (
    <>
      <div style={{ marginTop: 16 }}>
        <div className="sec-h">Net New Money (NNM)</div>
        <div style={{ fontSize: "12.5px", color: "var(--slate)", marginTop: 2 }}>
          Year-to-date by category, as of {nnm.as_of_label}
        </div>
      </div>
      <div className="mstrip" style={{ marginTop: 8 }}>
        {ec ? (
          <div style={{ borderLeft: "3px solid var(--navy)", paddingLeft: 9 }}>
            <div className="k">Existing Client (EC) NNM YTD</div>
            <div className="v">
              <Money value={ec.ytd_nnm} />
            </div>
            <div className="d mut">
              MTD <Money value={ec.mtd_nnm} />
            </div>
          </div>
        ) : null}
        {rest.map((c) => (
          <div key={c.category}>
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
          <div className="k">Total NNM YTD</div>
          <div className="v" style={{ fontSize: 15 }}>
            <Money value={nnm.total.ytd_nnm} />
          </div>
          <div className="d mut">
            MTD <Money value={nnm.total.mtd_nnm} />
          </div>
        </div>
      </div>
      {/* The threshold line stays (without the ASSUMED tag and its wording);
          with no threshold available, nothing renders in its place. */}
      {t.available && t.threshold_amt !== null ? (
        <div className="note" style={{ marginTop: 8 }}>
          EC YTD <Money value={t.ytd_nnm ?? 0} /> vs the <Money value={t.threshold_amt} /> threshold
          {" — "}
          {t.qualifies ? (
            <>at or above the threshold</>
          ) : (
            <>
              gap <Money value={t.gap ?? 0} /> below the threshold
            </>
          )}
          {t.as_of_month ? ` (as of ${nnm.as_of_label})` : ""}. The threshold figure comes from the
          extracted plan rule{t.rule_key ? ` (${t.rule_key})` : ""}, measured on {t.measured_category}{" "}
          flows.
        </div>
      ) : null}
    </>
  );
}

// ------------------------------------------------------------------ drivers

type Pivot = "driver" | "product";
type FindingWithGroup = Finding & { group_name?: string | null };

/** Review B4 (batch 1 F2) — By Product groups by the finding's group_id and
 * labels with group_name from the API; unattributed findings sit under
 * "No product attribution", never a raw id. */
function groupFindings(
  findings: Finding[],
  pivot: Pivot,
): { label: string; findings: Finding[] }[] {
  const map = new Map<string, { label: string; findings: Finding[] }>();
  for (const f of findings) {
    const fg = f as FindingWithGroup;
    const key = pivot === "product" ? fg.group_id || "__none__" : f.driver_tag || "Other";
    const label =
      pivot === "product"
        ? fg.group_id
          ? fg.group_name || fg.group_id
          : "No product attribution"
        : f.driver_tag || "Other";
    const entry = map.get(key) ?? { label, findings: [] };
    entry.findings.push(f);
    map.set(key, entry);
  }
  return Array.from(map.values());
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
      {groups.map(({ label, findings }) => (
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
          {findings.map((f, i) => (
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
          <h2>Revenue Drivers</h2>
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

/** Review B6 — highlighting reflects the VALUE, one consistent rule for ALL
 * ranking entries: the advisor's rank splits the ranked cohort into thirds.
 * Favourable third = green, middle = amber, unfavourable = red. Orientation
 * per metric: for revenue and growth a HIGH rank (nearer #1) is favourable;
 * for discount rate a LOW rank is favourable (rank #1 = highest mean fee
 * reduction). Unranked entries stay neutral. */
const TIER_RULE =
  "Highlight rule: the advisor's rank splits the ranked cohort into thirds — " +
  "green = favourable third, amber = middle third, red = unfavourable third. " +
  "For revenue and growth, higher is better; for discount rate, lower is better. " +
  "Unranked entries are not highlighted.";

type Tier = "green" | "amber" | "red" | null;

function rankTier(rank: number | null, size: number, higherIsBetter: boolean): Tier {
  if (rank === null || size <= 0) return null;
  const third = size / 3;
  const fromBest = higherIsBetter ? rank : size - rank + 1;
  if (fromBest <= Math.ceil(third)) return "green";
  if (fromBest <= Math.ceil(2 * third)) return "amber";
  return "red";
}

const TIER_STYLE: Record<Exclude<Tier, null>, { border: string; bg: string }> = {
  // no shared tokens exist for tiered rank cards — inline colours, noted
  green: { border: "#157F4C", bg: "#EAF4EE" },
  amber: { border: "#9A5B13", bg: "#FAF3E7" },
  red: { border: "#B3261E", bg: "#FBEDEB" },
};

function RankCard({
  title,
  block,
  valueKind,
  higherIsBetter,
}: {
  title: string;
  block: { rank: number | null; cohort_size: number; value: number | null; cohort_median: number | null; note?: string };
  valueKind: "money" | "pct";
  higherIsBetter: boolean;
}) {
  const fmt = (v: number | null) => (v === null ? "—" : valueKind === "money" ? money(v) : percent(v));
  const tier = rankTier(block.rank, block.cohort_size, higherIsBetter);
  const style = tier ? TIER_STYLE[tier] : null;
  return (
    <div
      title={TIER_RULE}
      style={{
        border: style ? `2px solid ${style.border}` : "1px solid var(--rule)",
        borderRadius: 6,
        padding: "12px 14px",
        background: style ? style.bg : "#fff",
      }}
    >
      <div className="k" style={{ fontSize: 11, letterSpacing: ".03em", color: "var(--slate)", textTransform: "uppercase" }}>
        {title}
      </div>
      <div style={{ fontSize: 20, fontWeight: 600, marginTop: 4, color: style?.border }}>
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
            {transition ? ` — ${monthName(transition.to_month_id)}` : ""}. Green / amber / red shows
            which third of the cohort the advisor sits in for each metric.
          </p>
        </div>
      </div>
      <div className="card-b">
        {error ? <EmptyState title="Peer ranking unavailable" message={error} /> : null}
        {ranking ? (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1.3fr", gap: 14 }}>
            <RankCard title="By Revenue" block={ranking.revenue} valueKind="money" higherIsBetter />
            <RankCard title="By Growth" block={ranking.growth} valueKind="money" higherIsBetter />
            <RankCard
              title="By Discount Rate"
              block={ranking.discount_rate}
              valueKind="pct"
              higherIsBetter={false}
            />
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

  // Review B7 — points arrive sorted Critical → Info; the order is KEPT.
  const pointsPager = usePager(result?.points ?? []);

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
          <>
            {pointsPager.rows.map((p, i) => (
              <div key={i} style={{ borderBottom: "1px solid var(--rule-2)", padding: "10px 2px" }}>
                {/* B7 order: 1) Coaching first, 2) Implication, 3) passage collapsed */}
                <div style={{ fontSize: "13px" }}>
                  <SeverityChip severity={p.severity} basis={p.severity_basis} />{" "}
                  <b>Coaching:</b> {p.text}
                </div>
                {p.fact ? (
                  <div style={{ marginTop: 4, fontSize: "12.5px", color: "var(--slate)" }}>{p.fact}</div>
                ) : null}
                <div style={{ marginTop: 4, fontSize: "12.5px", color: "var(--slate)" }}>
                  <b style={{ color: "var(--ink)" }}>Implication:</b> {p.implication}
                </div>
                <details className="tech" style={{ marginTop: 6 }}>
                  <summary>Supporting document passage (opens on click)</summary>
                  <blockquote
                    style={{
                      margin: "6px 0 0",
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
                </details>
              </div>
            ))}
            <Pager {...pointsPager} noun="coaching points" />
          </>
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

  const groups = useMemo(
    () =>
      opps
        ? [...opps.by_stage_group].sort(
            (a, b) => STAGE_GROUP_ORDER.indexOf(a.stage_group) - STAGE_GROUP_ORDER.indexOf(b.stage_group),
          )
        : [],
    [opps],
  );
  const groupPager = usePager(groups);
  const rowPager = usePager(opps?.opportunities ?? []);
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
                    {/* B8 — Stalled column REMOVED (days-to-close colour-coding
                        carries the meaning); Forecast Amount renamed Amount;
                        every header carries a glossary info tooltip */}
                    <th>
                      <ColHead
                        code="crm.stage_group"
                        label="Stage Group"
                        fallback="CRM pipeline stage grouped as Early / Mid / Late / Closing."
                      />
                    </th>
                    <th className="num">
                      <ColHead
                        code="crm.opportunity_count"
                        label="Opportunities"
                        fallback="Count of open CRM opportunities in the stage group."
                      />
                    </th>
                    <th className="num">
                      <ColHead
                        code="crm.amount"
                        label="Amount"
                        fallback="The CRM opportunity amount — the forecast pipeline value."
                      />
                    </th>
                    <th className="num">
                      <ColHead
                        code="crm.actual_assets"
                        label="Actual Assets"
                        fallback="Assets that actually landed for the opportunity — never summed with Amount."
                      />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {groupPager.rows.map((g) => (
                    <tr key={g.stage_group}>
                      <td>{STAGE_GROUP_LABELS[g.stage_group] ?? g.stage_group}</td>
                      <td className="num">{g.opportunity_count}</td>
                      <td className="num">
                        <Money value={g.forecast_amount} />
                      </td>
                      <td className="num">
                        <Money value={g.actual_assets} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager {...groupPager} noun="stage groups" />
            {opps.data_quality?.invalid_advisor_rows > 0 ? (
              <div className="note" style={{ color: "var(--sev-high-tx, #9A5B13)" }}>
                {`${opps.data_quality.invalid_advisor_rows} opportunity row(s) carry an invalid advisor reference in the source — shown, not hidden.`}
              </div>
            ) : null}
            {opps.opportunities.length ? (
              <>
                <div style={{ overflowX: "auto" }}>
                  <table className="exc">
                    <thead>
                      <tr>
                        <th>
                          <ColHead
                            code="crm.household"
                            label="Household"
                            fallback="The household (ECI) the opportunity belongs to — the join between CRM and the book."
                          />
                        </th>
                        <th>
                          <ColHead
                            code="crm.stage"
                            label="Stage"
                            fallback="The opportunity's CRM stage name, verbatim from the source."
                          />
                        </th>
                        <th className="num">
                          <ColHead
                            code="crm.days_to_close"
                            label="Days to Close"
                            fallback="Days until the anticipated close date. A red negative value means the anticipated close date has already passed."
                          />
                        </th>
                        <th className="num">
                          <ColHead
                            code="crm.amount"
                            label="Amount"
                            fallback="The CRM opportunity amount — the forecast pipeline value."
                          />
                        </th>
                        <th className="num">
                          <ColHead
                            code="crm.actual_assets"
                            label="Actual Assets"
                            fallback="Assets that actually landed for the opportunity — never summed with Amount."
                          />
                        </th>
                        <th>
                          <ColHead
                            code="crm.notes"
                            label="Notes"
                            fallback="The CRM comment on the opportunity, verbatim from the source."
                          />
                        </th>
                        {/* AI Read: descriptive only — deliberately not sortable or filterable */}
                        <th>
                          <ColHead
                            code="crm.ai_read"
                            label="AI Read"
                            fallback="An AI reading of the CRM comment — descriptive only; it never drives a figure, sort, or filter."
                          />
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {rowPager.rows.map((r) => (
                        <tr key={r.opportunity_id}>
                          <td>
                            <span style={{ fontFamily: "var(--mono, ui-monospace, monospace)", fontSize: 12 }} title={`Household ECI ${r.eci_id}`}>
                              {r.eci_id || "—"}
                            </span>
                            {!r.advisor_valid ? (
                              <>
                                {" "}
                                <Chip variant="neg" title="The source extract carries an invalid advisor reference for this row">
                                  invalid advisor ref
                                </Chip>
                              </>
                            ) : null}
                          </td>
                          <td>{r.stage_name || "—"}</td>
                          <td className="num">
                            {r.days_to_close == null ? (
                              "—"
                            ) : r.days_to_close < 0 ? (
                              // B8 — negative days-to-close is colour-coded red:
                              // the anticipated close date has passed
                              <b
                                style={{ color: "var(--neg, #B3261E)" }}
                                title={`Anticipated close date passed ${-r.days_to_close} day(s) ago`}
                              >
                                {r.days_to_close}
                              </b>
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
                <Pager {...rowPager} noun="opportunities" />
              </>
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
