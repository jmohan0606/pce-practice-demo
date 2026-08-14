/** Round C (docs/rules) 1.1 — where a rule applies. Distinct from the
 * evaluation `scopes` (which the plan CAN run at): applies_to says which
 * entities the rule SHOULD apply to. ALL renders nothing (the default —
 * chips are for the exceptions, not the norm). */
export default function AppliesToChip({
  appliesTo,
  appliesToKey,
}: {
  appliesTo?: string | null;
  appliesToKey?: string | null;
}) {
  if (!appliesTo || appliesTo === "ALL") return null;
  const label =
    appliesTo === "PRACTICE"
      ? "Practice only"
      : appliesTo === "ADVISOR"
        ? `Advisor${appliesToKey ? ` ${appliesToKey}` : "-level"}`
        : appliesTo === "PRODUCT"
          ? `Product${appliesToKey ? ` ${appliesToKey}` : "-level"}`
          : appliesTo;
  return (
    <span
      className="chip aigen"
      title={`Applies to ${label} — other evaluations skip this rule with a reason.`}
    >
      {label}
    </span>
  );
}
