"use client";

import { useEffect, useState } from "react";
import { type RuleVersion, getRuleVersions } from "@/lib/api";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";

/** AI Insights — Round C fills this page; Round B renders the empty state.
 * The only filter that acts here is the rule-set version. */
export default function InsightsPage() {
  const [versions, setVersions] = useState<RuleVersion[]>([]);
  const [version, setVersion] = useState("latest");

  useEffect(() => {
    getRuleVersions()
      .then((res) => setVersions(res.versions ?? []))
      .catch(() => setVersions([])); // B3 lands in parallel — 404 is a valid state
  }, []);

  return (
    <section>
      <PageHeader title="AI Insights" meta="Scope follows the Dashboard selection" />
      <div className="card">
        <div className="card-h">
          <div>
            <h2>What Is Driving the Changes in Month-over-Month Credited Revenue?</h2>
            <p>
              One card per month-over-month move · findings ranked by impact · every figure computed
              from graph data
            </p>
          </div>
          <div className="ctl">
            <span style={{ fontSize: "12.5px", color: "var(--slate)" }}>Rule Set</span>
            <select value={version} onChange={(e) => setVersion(e.target.value)}>
              <option value="latest">Latest</option>
              {versions.map((v) => (
                <option key={v.version_id ?? v.version_no} value={v.version_id ?? String(v.version_no)}>
                  v{v.version_no}
                  {v.published_at ? ` · ${v.published_at}` : ""}
                </option>
              ))}
            </select>
          </div>
        </div>
        <EmptyState
          title="No Insights Yet"
          message="Insight generation arrives in Round C. Generated findings will appear here, one card per month-over-month move."
        />
      </div>
    </section>
  );
}
