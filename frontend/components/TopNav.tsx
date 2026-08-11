"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getHealth } from "@/lib/api";

const TABS = [
  { href: "/", label: "Dashboard" },
  { href: "/insights", label: "AI Insights" },
  { href: "/advisor", label: "Advisor" },
  { href: "/documents", label: "Documents & Rules" },
  { href: "/rules", label: "Rule Versions" },
];

/** Top bar (brand + TigerGraph pill) and the five-tab navigation. */
export default function TopNav() {
  const pathname = usePathname();
  const [pill, setPill] = useState<{ text: string; on: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((health) => {
        if (cancelled) return;
        const tier = health.graph?.tier;
        setPill({
          text: `● TigerGraph${tier ? ` · Tier ${tier}` : ""}`,
          on: Boolean(health.healthy),
        });
      })
      .catch(() => {
        if (!cancelled) setPill({ text: "● Graph Offline", on: false });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <div className="topbar">
        <div className="brand">Practice Management</div>
        <div className="right">
          {pill ? <span className={`pill-tg${pill.on ? "" : " off"}`}>{pill.text}</span> : null}
        </div>
      </div>
      <nav className="nav">
        {TABS.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={pathname === tab.href ? "page" : undefined}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
    </>
  );
}
