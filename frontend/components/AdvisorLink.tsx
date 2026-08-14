import Link from "next/link";

/** Round A2B 1.4 — EVERY advisor reference anywhere uses this.
 *
 * Renders `Sandra Mehta (V000002)` linking to the advisor page filtered to
 * that advisor. A blank name falls back to the SID alone — never "Unknown".
 */
export default function AdvisorLink({ sid, name }: { sid: string; name?: string | null }) {
  const label = name && name.trim() ? `${name.trim()} (${sid})` : sid;
  return (
    <Link className="advlink" href={`/advisor?sid=${encodeURIComponent(sid)}`}>
      {label}
    </Link>
  );
}
