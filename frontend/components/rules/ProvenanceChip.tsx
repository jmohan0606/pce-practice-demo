import Term from "@/components/Term";

/** Round C (docs/rules) 1.2 — the provenance chip, rendered everywhere a rule
 * appears so the client always sees where a rule came from. Label comes from
 * the API's provenance_label (RULE_PROVENANCE_TAGS); the glossary term
 * `provenance.<code>` supplies the hover definition. Unknown/legacy codes
 * render as-is — never invented, never hidden. */
export default function ProvenanceChip({
  provenance,
  provenanceLabel,
}: {
  provenance?: string | null;
  provenanceLabel?: string | null;
}) {
  if (!provenance) return null;
  const cls =
    provenance === "DOCUMENT_DERIVED"
      ? "chip real"
      : provenance.startsWith("MANUALLY_WRITTEN")
        ? "chip derived"
        : "chip tag";
  return (
    <span className={cls}>
      <Term code={`provenance.${provenance}`}>{provenanceLabel || provenance}</Term>
    </span>
  );
}
