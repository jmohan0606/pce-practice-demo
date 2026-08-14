"use client";

import { type ReactNode, useEffect, useState } from "react";
import { type GlossaryResponse, type GlossaryTerm, getGlossary } from "@/lib/api";
import { useFlag } from "@/lib/flags";

/** Round A2B 1.1 — glossary-driven tooltips.
 *
 * Every explanatory string comes from GET /api/glossary (the one tooltip
 * source, Round A1). Nothing is hardcoded here: a missing term renders the
 * label with no info circle, and the fix is a backend glossary entry, never a
 * frontend string.
 *
 * The glossary is fetched once per session and shared by every subscriber.
 */

let cached: GlossaryResponse | null = null;
let inflight: Promise<GlossaryResponse> | null = null;
const listeners = new Set<(g: GlossaryResponse) => void>();

function load(): void {
  if (cached || inflight) return;
  inflight = getGlossary()
    .then((g) => {
      cached = g;
      listeners.forEach((fn) => fn(g));
      return g;
    })
    .catch((e) => {
      inflight = null; // allow a retry on the next mount
      throw e;
    });
  inflight.catch(() => undefined);
}

export function useGlossary(): GlossaryResponse | null {
  const [glossary, setGlossary] = useState<GlossaryResponse | null>(cached);
  useEffect(() => {
    if (cached) {
      setGlossary(cached);
      return;
    }
    const fn = (g: GlossaryResponse) => setGlossary(g);
    listeners.add(fn);
    load();
    return () => {
      listeners.delete(fn);
    };
  }, []);
  return glossary;
}

/** Look a term up by its full glossary key (e.g. "metric.share", "severity.HIGH"). */
export function useTerm(code: string): GlossaryTerm | null {
  const glossary = useGlossary();
  return glossary?.terms?.[code] ?? null;
}

/** `<Term code="metric.share">% Share</Term>` — label plus a small `i` circle
 * whose tooltip is the glossary definition. With no children the glossary's
 * own term text is the label. */
export default function Term({ code, children }: { code: string; children?: ReactNode }) {
  const term = useTerm(code);
  // Round A2B task 7 — global.tooltips flag: off hides the affordance (the
  // label itself always renders).
  const tooltipsOn = useFlag("global.tooltips");
  return (
    <span>
      {children ?? term?.term ?? code}
      {term?.definition && tooltipsOn !== false ? (
        <i className="info" title={term.definition} aria-label={`Definition: ${term.definition}`}>
          i
        </i>
      ) : null}
    </span>
  );
}
