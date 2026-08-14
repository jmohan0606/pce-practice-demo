"use client";

/** Round A2B Task 4 — shared plumbing for the dashboard's AI Insights and
 * Drivers sections. Both sections fetch the SAME stored run independently
 * (self-contained, no shared loading gate) via `useInsightRun`; `Prose`
 * renders reporter text (**bold** markdown-lite) with every movable figure
 * pushed through `<NarrativeText>` so nothing renders unstyled.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, type Finding, type InsightRun, getInsights } from "@/lib/api";
import { NarrativeText } from "@/components/Num";

export interface InsightRunState {
  /** The stored COMPLETE run, or null. */
  run: InsightRun | null;
  /** True once the fetch settled with a 404 — honest "not generated yet". */
  notGenerated: boolean;
  /** Non-404 failure message, or null. */
  error: string | null;
  /** True until the first fetch settles. */
  loading: boolean;
  refetch: () => void;
}

/** Fetch the stored practice-level run for a transition. 404 is a designed
 * state (nothing generated yet), never an error. */
export function useInsightRun(fromMonth: string, toMonth: string): InsightRunState {
  const [run, setRun] = useState<InsightRun | null>(null);
  const [notGenerated, setNotGenerated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refetch = useCallback(() => {
    setLoading(true);
    setError(null);
    setNotGenerated(false);
    getInsights("all", fromMonth, toMonth)
      .then((r) => {
        setRun(r);
        setLoading(false);
      })
      .catch((e) => {
        setRun(null);
        if (e instanceof ApiError && e.status === 404) setNotGenerated(true);
        else setError(String((e as Error)?.message || e));
        setLoading(false);
      });
  }, [fromMonth, toMonth]);

  useEffect(refetch, [refetch]);
  return { run, notGenerated, error, loading, refetch };
}

/** The API serializes `driver_code` (stable identity, Round A1 task 1) on
 * every finding, but lib/api.ts's `Finding` type predates it — typed here as
 * a local extension rather than editing api.ts (gap reported). */
export type FindingWithDriver = Finding & { driver_code?: string | null };

/** The stored driver_code, falling back to the served label (never invented). */
export function driverCode(f: Finding): string {
  return (f as FindingWithDriver).driver_code || f.driver_tag || "OTHER";
}

/** Findings ranked by |impact_amt| descending; null impacts last. */
export function rankFindings(findings: Finding[]): Finding[] {
  return [...findings].sort((a, b) => {
    const aa = a.impact_amt === null ? -1 : Math.abs(a.impact_amt);
    const bb = b.impact_amt === null ? -1 : Math.abs(b.impact_amt);
    return bb - aa;
  });
}

/** "RSV_v1" -> "v1"; anything else passes through untouched. */
export function ruleSetLabel(versionId: string): string {
  const match = /^RSV_v(\d+)$/.exec(versionId || "");
  return match ? `v${match[1]}` : versionId;
}

/** Reporter prose: **bold** markdown-lite, every movable figure through
 * `<NarrativeText>` (colour + arrow, per Task 1.2). */
export function Prose({ text }: { text: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <b key={i}>
            <NarrativeText text={part} />
          </b>
        ) : (
          <NarrativeText key={i} text={part} />
        ),
      )}
    </>
  );
}
