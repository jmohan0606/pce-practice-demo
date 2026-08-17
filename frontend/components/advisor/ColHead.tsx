"use client";

import { useTerm } from "@/components/Term";
import { useFlag } from "@/lib/flags";

/** Round 3 review B8 — an `i` info tooltip on EVERY column header, sourced
 * from the glossary (<Term>/useGlossary machinery). When the glossary has no
 * entry for the key yet, the label still renders with a sensible fallback
 * title — the missing keys are reported so the backend glossary can grow.
 */
export default function ColHead({
  code,
  label,
  fallback,
}: {
  /** Glossary term key, e.g. "crm.days_to_close". */
  code: string;
  /** Rendered header label (already labelized — never a raw field name). */
  label: string;
  /** Tooltip text used when the glossary has no entry for the key. */
  fallback: string;
}) {
  const term = useTerm(code);
  const tooltipsOn = useFlag("global.tooltips");
  const definition = term?.definition || fallback;
  return (
    <span>
      {label}
      {tooltipsOn !== false && definition ? (
        <i className="info" title={definition} aria-label={`Definition: ${definition}`}>
          i
        </i>
      ) : null}
    </span>
  );
}
