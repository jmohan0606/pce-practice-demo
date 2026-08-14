/** Round C (docs/rules) 2.1 — status chip that renders Inactive as its own
 * state, visually distinct from Superseded. `active` is independent of status:
 * an inactive PUBLISHED rule shows "Inactive" (amber), a superseded one keeps
 * the muted "Superseded". Title carries the recorded deactivation reason. */
export default function StatusChip({
  status,
  active,
  activeReason,
}: {
  status?: string | null;
  active?: boolean;
  activeReason?: string | null;
}) {
  if (active === false) {
    return (
      <span className="chip warn" title={activeReason || "Rule is inactive — not evaluated in new insight runs; remains queryable."}>
        Inactive
      </span>
    );
  }
  const s = (status || "DRAFT").toUpperCase();
  const cls =
    s === "PUBLISHED"
      ? "chip on"
      : s === "COMPILED"
        ? "chip real"
        : s === "NEEDS_INPUT" || s === "NEEDS_DATA"
          ? "chip warn"
          : "chip tag"; // DRAFT / SUPERSEDED / REJECTED
  const label = s.replace(/_/g, " ");
  return <span className={cls}>{label}</span>;
}
