import type { ReactNode } from "react";

export type ChipVariant = "real" | "derived" | "tag" | "aigen" | "pos" | "neg";

export default function Chip({ variant, children }: { variant: ChipVariant; children: ReactNode }) {
  return <span className={`chip ${variant}`}>{children}</span>;
}
