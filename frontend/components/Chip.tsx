import type { ReactNode } from "react";

export type ChipVariant = "real" | "derived" | "tag" | "aigen" | "pos" | "neg" | "dummy";

export default function Chip({
  variant,
  title,
  children,
}: {
  variant: ChipVariant;
  /** Optional hover tooltip — driver chips pass the driver's definition. */
  title?: string;
  children: ReactNode;
}) {
  return (
    <span className={`chip ${variant}`} title={title}>
      {children}
    </span>
  );
}
