"use client";

import { useEffect, useState } from "react";
import { getHealth } from "@/lib/api/client";
import type { HealthStatus } from "@/lib/types/api";
import { cn } from "@/lib/utils";

const NAV_TABS = ["Dashboard", "AI Insights", "Advisor", "Documents & Rules", "Rule Versions"] as const;

function StatusPill({ health, error }: { health: HealthStatus | null; error: boolean }) {
  const ok = health?.healthy === true;
  const label = error
    ? "TigerGraph: Unreachable"
    : health === null
      ? "TigerGraph: Checking…"
      : ok
        ? `TigerGraph: Connected${health.mode ? ` (${health.mode})` : ""}`
        : "TigerGraph: Unavailable";
  return (
    <span
      className={cn(
        "rounded-xl border px-2.5 py-[3px] text-[11.5px]",
        ok
          ? "border-pm-pos-br bg-pm-pos-bg text-pm-pos"
          : health === null && !error
            ? "border-pm-rule bg-pm-panel text-pm-slate"
            : "border-pm-neg-br bg-pm-neg-bg text-pm-neg"
      )}
    >
      {label}
    </span>
  );
}

export default function Home() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [activeTab, setActiveTab] = useState<(typeof NAV_TABS)[number]>("Dashboard");

  useEffect(() => {
    getHealth()
      .then((h) => setHealth(h))
      .catch(() => setHealthError(true));
  }, []);

  return (
    <div className="min-h-screen">
      <header className="flex h-[50px] items-center justify-between bg-pm-navy px-6 text-white">
        <span className="text-[16px] font-semibold">Practice Management</span>
        <StatusPill health={health} error={healthError} />
      </header>

      <nav className="sticky top-0 z-20 flex gap-1 overflow-x-auto border-b border-pm-rule bg-white px-6" aria-label="Primary">
        {NAV_TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            aria-selected={activeTab === tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              "whitespace-nowrap border-b-2 border-transparent px-4 py-[13px] text-[14px] font-medium text-pm-slate hover:text-pm-ink focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-pm-navy",
              activeTab === tab && "border-pm-navy font-semibold text-pm-navy"
            )}
          >
            {tab}
          </button>
        ))}
      </nav>

      <main className="mx-auto max-w-[1240px] px-6 pb-16 pt-5">
        <div className="rounded-md border border-pm-rule bg-white p-8 text-center">
          <h1 className="text-[18px]">{activeTab}</h1>
          <p className="mt-2 text-[12.5px] text-pm-slate">This screen is under construction.</p>
        </div>
      </main>
    </div>
  );
}
