import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Canonical currency formatter. Compact ($1.2M) at/above 1M by default;
 * pass compact:false to force standard grouping.
 */
export function formatCurrency(value: number, opts: { compact?: boolean; decimals?: number } = {}): string {
  const compact = opts.compact ?? Math.abs(value) >= 1_000_000;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: opts.decimals ?? (compact ? 1 : 0),
  }).format(value);
}

/**
 * Accounting-style currency: negatives render in parentheses, per the
 * mockup design language. e.g. formatAccounting(-12500) -> "($12,500)"
 */
export function formatAccounting(value: number, opts: { compact?: boolean; decimals?: number } = {}): string {
  const formatted = formatCurrency(Math.abs(value), opts);
  return value < 0 ? `(${formatted})` : formatted;
}

/** Percent with a fixed number of decimals (no sign). e.g. formatPercent(14.37) -> "14.4%" */
export function formatPercent(value: number, decimals = 1): string {
  return `${value.toFixed(decimals)}%`;
}

/** Percent for deltas: negatives in parentheses. e.g. (-4.2) -> "(4.2%)" */
export function formatDeltaPercent(value: number, decimals = 1): string {
  const body = `${Math.abs(value).toFixed(decimals)}%`;
  return value < 0 ? `(${body})` : body;
}

/** % change from a prior value, guarding divide-by-zero. */
export function pctChange(current: number, prior: number): number {
  if (!prior) return 0;
  return ((current - prior) / Math.abs(prior)) * 100;
}
