import Chip from "@/components/Chip";

/** Round A2B 1.3 — driver chips resolve labels at read time.
 *
 * The API serializes driver_code (stable identity) and driver_label /
 * driver_definition resolved server-side at read time (Round A1 task 1).
 * This component renders exactly what the API returned for THIS response —
 * the label is never cached across a rename — and carries the definition on
 * the chip itself as its tooltip.
 */
export default function DriverChip({
  code,
  label,
  definition,
}: {
  code: string;
  /** Server-resolved display label; falls back to the stable code, never invented. */
  label?: string | null;
  definition?: string | null;
}) {
  return (
    <Chip variant="tag" title={definition ?? undefined}>
      {label && label.trim() ? label : code}
    </Chip>
  );
}
