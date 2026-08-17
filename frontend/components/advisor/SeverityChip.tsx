"use client";

import { useTerm } from "@/components/Term";

/** Round 3 review B7 — coaching points carry the same severity model as
 * rules and exceptions. Renders the shared .sev chip classes from
 * globals.css (crit / high / mod / low / info). */
const SEV_CLASS: Record<string, string> = {
  CRITICAL: "crit",
  HIGH: "high",
  MODERATE: "mod",
  LOW: "low",
  INFO: "info",
};

export default function SeverityChip({
  severity,
  basis,
}: {
  severity?: string | null;
  basis?: string | null;
}) {
  const level = (severity || "").toUpperCase();
  const term = useTerm(`severity.${level}`);
  if (!SEV_CLASS[level]) return null;
  const title = [term?.definition, basis].filter(Boolean).join(" — ");
  return (
    <span className={`sev ${SEV_CLASS[level]}`} title={title || undefined}>
      {level.charAt(0) + level.slice(1).toLowerCase()}
    </span>
  );
}
