/** Mandatory formatting helpers — used everywhere a figure is rendered.
 *
 * Negatives are ALWAYS parentheses, never a minus sign.
 * Zero renders as an em dash, never "$0".
 */

export const EM_DASH = "—";

/** money(6580210) -> "$6,580,210" ; money(-3670) -> "($3,670)" ; 0/null -> "—" */
export function money(n: number | null | undefined): string {
  if (n === null || n === undefined) return EM_DASH;
  const rounded = Math.round(Math.abs(n));
  if (rounded === 0) return EM_DASH;
  const body = `$${rounded.toLocaleString("en-US")}`;
  return n < 0 ? `(${body})` : body;
}

/** percent(3.58) -> "3.6%" ; percent(-2.61) -> "(2.6%)" ; null -> "—" */
export function percent(n: number | null | undefined): string {
  if (n === null || n === undefined) return EM_DASH;
  const body = `${Math.abs(n).toFixed(1)}%`;
  return n < 0 ? `(${body})` : body;
}

/** arrow: n>0 -> "▲" ; n<0 -> "▼" ; 0/null -> "—" */
export function arrow(n: number | null | undefined): string {
  if (n === null || n === undefined || n === 0) return EM_DASH;
  return n > 0 ? "▲" : "▼";
}

/** Compact axis label: 7000000 -> "$7.0M", 5250000 -> "$5.25M", 0 -> "$0". */
export function moneyAxis(n: number): string {
  if (n === 0) return "$0";
  if (Math.abs(n) >= 1_000_000) {
    const m = n / 1_000_000;
    const text = Number.isInteger(m * 10) ? m.toFixed(1) : m.toFixed(2);
    return `$${text}M`;
  }
  if (Math.abs(n) >= 1_000) {
    const k = n / 1_000;
    const text = Number.isInteger(k) ? k.toFixed(0) : k.toFixed(1);
    return `$${text}K`;
  }
  return `$${Math.round(n)}`;
}

/** The y-axis max: the largest month rounded up to a clean value (6.58M -> 7.0M). */
export function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(value)));
  for (const f of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 7.5, 8, 9, 10]) {
    if (f * pow >= value) return f * pow;
  }
  return 10 * pow;
}
