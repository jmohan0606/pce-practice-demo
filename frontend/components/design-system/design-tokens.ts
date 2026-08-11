/**
 * Practice Management design tokens — the exact values from the :root palette
 * in docs/ui/mockups.html. Components use these token names (via the tailwind
 * `pm-*` colors or this object), never raw hex.
 */
export const tokens = {
  color: {
    // brand / chrome
    navy: "#16365C",
    navyHi: "#1E4675",
    ink: "#1A2430",
    // text
    slate: "#5A6B7D",
    slate2: "#8A9AAA",
    // surface
    canvas: "#F4F6F9",
    panel: "#FBFCFD",
    card: "#FFFFFF",
    totalBg: "#EAF0F7",
    // rules / borders
    rule: "#E2E7ED",
    rule2: "#EFF2F6",
    // chart (tan recurring / blue non-recurring stacked bars)
    chartRecurring: "#C5B88F",
    chartNonrecurring: "#6699C2",
    // semantic
    positive: "#157F4C",
    positiveBg: "#E8F5EE",
    positiveBorder: "#B5D9C6",
    negative: "#B3261E",
    negativeBg: "#FBECEA",
    negativeBorder: "#EFC6C2",
    // chips
    realBg: "#E6F4EC",
    realText: "#1A6B42",
    derivedBg: "#FBF0DC",
    derivedText: "#8A5A00",
    tagBg: "#EDF1F5",
    tagText: "#4A5B6D",
    // AI accents
    ai: "#4C4EA3",
    aiBg: "#EEEEF8",
    aiBorder: "#C9CAE8",
  },
  font: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
  type: {
    brand: "text-[16px] font-semibold",
    pageTitle: "text-[18px] font-semibold",
    cardTitle: "text-[16px] font-semibold",
    body: "text-[14px]",
    meta: "text-[12.5px]",
    tableHeader: "text-[11px] font-semibold tracking-[0.03em]",
    chip: "text-[10.5px] font-semibold uppercase tracking-[0.03em]",
  },
} as const;

export type ChipKind = "real" | "derived" | "tag" | "aigen" | "pos" | "neg";

/** Chip palette (mockups.html .chip variants). */
export const chipStyle: Record<ChipKind, { color: string; bg: string }> = {
  real: { color: tokens.color.realText, bg: tokens.color.realBg },
  derived: { color: tokens.color.derivedText, bg: tokens.color.derivedBg },
  tag: { color: tokens.color.tagText, bg: tokens.color.tagBg },
  aigen: { color: tokens.color.ai, bg: tokens.color.aiBg },
  pos: { color: tokens.color.positive, bg: tokens.color.positiveBg },
  neg: { color: tokens.color.negative, bg: tokens.color.negativeBg },
};
