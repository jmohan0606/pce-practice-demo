import { Delta } from "@/components/Num";
import { EM_DASH, money, percent } from "@/lib/format";

/** Round 3 task 6.2 — every number shows its comparison.
 *
 * Any figure displayed carries the prior-month value or delta beneath it,
 * colour-coded with an up/down arrow — not just revenue: counts, volumes,
 * accounts, transactions.
 *
 *   <CompareValue current={12480} prior={11890} kind="money" priorLabel="Apr 2026" />
 *
 * renders the current value with `▲ $590 vs Apr 2026` beneath. When no prior
 * exists nothing is invented — the comparison line is simply absent.
 */
export function CompareValue({
  current,
  prior,
  kind = "money",
  priorLabel,
  showPrior = false,
}: {
  current: number | null | undefined;
  prior: number | null | undefined;
  kind?: "money" | "count" | "pct";
  priorLabel?: string;
  /** show the prior value itself ("Apr: $11,890") instead of the delta */
  showPrior?: boolean;
}) {
  const fmt = (n: number | null | undefined) =>
    kind === "money"
      ? money(n)
      : kind === "pct"
        ? percent(n)
        : n === null || n === undefined
          ? EM_DASH
          : n.toLocaleString("en-US");
  return (
    <span className="cmpv">
      <span className="cmpv-cur">{fmt(current)}</span>
      {prior !== null && prior !== undefined ? (
        <span className="cmpv-sub">
          {showPrior ? (
            <>
              {priorLabel ? `${priorLabel}: ` : "prior: "}
              {fmt(prior)}{" "}
            </>
          ) : null}
          <Delta value={(current ?? 0) - prior} kind={kind} />
          {!showPrior && priorLabel ? ` vs ${priorLabel}` : null}
        </span>
      ) : null}
    </span>
  );
}
