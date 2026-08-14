import Term from "@/components/Term";

const CLASS_BY_LEVEL: Record<string, string> = {
  CRITICAL: "crit",
  HIGH: "high",
  MODERATE: "mod",
  LOW: "low",
  INFO: "info",
};

/** Round A1 severity chip (shared for Round C rule surfaces). Uses the `.sev`
 * classes from globals.css; label + hover definition resolve from the glossary
 * term `severity.<LEVEL>`. Missing severity renders nothing — never guessed. */
export default function SeverityChip({ severity }: { severity?: string | null }) {
  if (!severity) return null;
  const level = severity.toUpperCase();
  const cls = CLASS_BY_LEVEL[level];
  if (!cls) return null;
  return (
    <span className={`sev ${cls}`}>
      <Term code={`severity.${level}`}>{level.charAt(0) + level.slice(1).toLowerCase()}</Term>
    </span>
  );
}
