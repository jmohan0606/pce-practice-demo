import type { ReactNode } from "react";
import { EM_DASH, arrow, money, percent } from "@/lib/format";

/** Round A2B 1.2 — one number-rendering surface, used everywhere.
 *
 * The client asked for colour and arrows on EVERY number that can move —
 * tables, KPI strips, modals, and inside narrative prose. Convention
 * (format.ts, project-wide): negatives are parentheses, never a minus sign;
 * zero/null is an em dash.
 */

/** Plain money, no movement colouring: `$182,340` / `($3,670)` / `—`. */
export function Money({ value }: { value: number | null | undefined }) {
  return <span className="num-inline">{money(value)}</span>;
}

/** Plain percent: `12.7%` / `(4.7%)` / `—`. */
export function Pct({ value }: { value: number | null | undefined }) {
  return <span className="num-inline">{percent(value)}</span>;
}

/** A figure that MOVED: green ▲ / red ▼ (negative in parentheses) / em dash.
 *
 * kind="money"  → `▲ $14,380` | `▼ ($1,365)`
 * kind="pct"    → `▲ 7.2%`    | `▼ (4.7%)`
 * kind="count"  → `▲ +44`     | `▼ −13`  (counts keep the sign, mockup-style)
 */
export function Delta({
  value,
  kind = "money",
}: {
  value: number | null | undefined;
  kind?: "money" | "pct" | "count";
}) {
  if (value === null || value === undefined || value === 0) return <span>{EM_DASH}</span>;
  const cls = value > 0 ? "up" : "dn";
  let body: string;
  if (kind === "money") body = money(value);
  else if (kind === "pct") body = percent(value);
  else body = value > 0 ? `+${Math.abs(value).toLocaleString("en-US")}` : `−${Math.abs(value).toLocaleString("en-US")}`;
  return (
    <span className={cls}>
      {arrow(value)} {body}
    </span>
  );
}

/** 1.2 — figures inside narrative prose are colour-coded and arrowed.
 *
 * The Reporter emits plain prose; this parses and wraps every movable figure
 * so nothing renders unstyled. Sign follows the project-wide convention the
 * backend already writes: a parenthesised figure — `($4,200)`, `(4.7%)` — is
 * negative (red, ▼); a bare currency/percent figure or an explicitly signed
 * count — `$62,456`, `7.2%`, `+44` — is positive (green, ▲). Unsigned bare
 * counts stay plain: "13 accounts" is a quantity, not a movement.
 */
const FIGURE = /(\(\$[\d,]+(?:\.\d+)?\)|\(\d+(?:\.\d+)?%\)|\$[\d,]+(?:\.\d+)?|\d+(?:\.\d+)?%|\+[\d,]+\b|[▲▼]\s?)/g;

export function NarrativeText({ text }: { text: string }) {
  const parts = text.split(FIGURE);
  const out: ReactNode[] = [];
  let pendingArrow: "up" | "dn" | null = null;
  // Direction of the last styled figure — a parenthesised PERCENT that
  // immediately follows one (only whitespace between) is a restatement of the
  // same move ("rose $34,166 (4.0%)"), not a negative, and inherits it.
  let lastDir: "up" | "dn" | null = null;
  let sinceLastFigure = "";
  parts.forEach((part, i) => {
    if (!part) return;
    if (part.startsWith("▲") || part.startsWith("▼")) {
      // reporter already arrowed it — colour the figure that follows
      pendingArrow = part.startsWith("▲") ? "up" : "dn";
      return;
    }
    const parenPct = /^\(\d+(?:\.\d+)?%\)$/.test(part);
    const negative = /^\(.*\)$/.test(part) && /[\d]/.test(part);
    const positive = /^(\$[\d,]|(?:\d+(?:\.\d+)?%)|\+[\d,])/.test(part);
    if (negative || positive) {
      let cls: "up" | "dn";
      // A movement verb right before the figure decides its direction:
      // "lost $54,977.60" / "fell 4.7%" are declines even unparenthesised.
      const declineContext = /\b(lost|loss(?:es)?\s+(?:of|was|were)|fell|fall(?:ing)? (?:of|by)|dropped|declined?(?: by)?|down|shrank|decrease[ds]?(?: by)?)\W*$/i.test(
        sinceLastFigure.slice(-30),
      );
      if (parenPct && lastDir && /^\s*$/.test(sinceLastFigure)) cls = lastDir;
      else if (negative || declineContext) cls = "dn";
      else cls = pendingArrow ?? "up";
      out.push(
        <span key={i} className={cls}>
          {cls === "dn" ? "▼" : "▲"} {part}
        </span>,
      );
      lastDir = cls;
      sinceLastFigure = "";
      pendingArrow = null;
    } else {
      out.push(part);
      sinceLastFigure = part;
      pendingArrow = null;
    }
  });
  return <>{out}</>;
}
