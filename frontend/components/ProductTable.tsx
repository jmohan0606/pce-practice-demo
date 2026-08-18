import type { ContributionRow, ContributionSection, ContributionTotal, ProductContribution } from "@/lib/api";
import { arrow, money, percent } from "@/lib/format";

/** Change + Change % cells. When `onDrill` is provided (product rows only —
 * subtotals and the grand total never pass it) the Change figure is a real
 * button: dashed underline, colour preserved, keyboard-operable. */
function ChangeCells({
  entry,
  onDrill,
}: {
  entry: ContributionRow | ContributionTotal;
  onDrill?: () => void;
}) {
  const dirClass = entry.change_amt < 0 ? "dn" : entry.change_amt > 0 ? "up" : "";
  const changeText =
    entry.change_amt === 0 ? "—" : `${arrow(entry.change_amt)} ${money(entry.change_amt)}`;
  return (
    <>
      <td className="num">
        {onDrill && entry.change_amt !== 0 ? (
          <button
            className={`drill ${dirClass}`.trim()}
            onClick={onDrill}
            title="See what drove this change"
          >
            {changeText}
          </button>
        ) : (
          <span className={dirClass || undefined}>{changeText}</span>
        )}
      </td>
      <td className={`num ${dirClass}`.trim()}>{percent(entry.change_pct)}</td>
    </>
  );
}

/** The product-contribution table: class sections, subtotals, grand total. */
export default function ProductTable({
  data,
  fromLabel,
  toLabel,
  onDrill,
}: {
  data: ProductContribution;
  fromLabel: string;
  toLabel: string;
  /** Round G 4.1 — makes each product row's Change figure a drill button. */
  onDrill?: (row: ContributionRow, section: ContributionSection) => void;
}) {
  return (
    <table>
      <thead>
        <tr>
          <th style={{ width: "34%" }}>Product</th>
          <th className="num">{fromLabel}</th>
          <th className="num">{toLabel}</th>
          <th className="num">Change</th>
          <th className="num">Change %</th>
          <th className="num">% Share of Total</th>
        </tr>
      </thead>
      <tbody>
        {data.sections.map((section) => (
          <SectionRows key={section.class_id} section={section} onDrill={onDrill} />
        ))}
        <tr className="tot">
          <td>Total Credited Revenue</td>
          <td className="num">{money(data.total.from_amt)}</td>
          <td className="num">{money(data.total.to_amt)}</td>
          <ChangeCells entry={data.total} />
          <td className="num">{data.total.share_pct.toFixed(1)}%</td>
        </tr>
      </tbody>
    </table>
  );
}

function SectionRows({
  section,
  onDrill,
}: {
  section: ContributionSection;
  onDrill?: (row: ContributionRow, section: ContributionSection) => void;
}) {
  return (
    <>
      <tr className="sect">
        <td colSpan={6}>{section.class_name}</td>
      </tr>
      {section.rows.map((row) => (
        <tr key={row.group_id}>
          <td>
            {/* Round 5 task 11.2 — prefix + name are ONE identically styled
                label: "TWHS – Structured Products". */}
            {row.display_prefix ? `${row.display_prefix} – ` : ""}
            {row.group_name}
          </td>
          <td className="num">{money(row.from_amt)}</td>
          <td className="num">{money(row.to_amt)}</td>
          <ChangeCells entry={row} onDrill={onDrill ? () => onDrill(row, section) : undefined} />
          <td className="num share">{percent(row.share_pct)}</td>
        </tr>
      ))}
      <tr className="sub">
        <td>{section.class_name} Subtotal</td>
        <td className="num">{money(section.subtotal.from_amt)}</td>
        <td className="num">{money(section.subtotal.to_amt)}</td>
        <ChangeCells entry={section.subtotal} />
        <td className="num share">{percent(section.subtotal.share_pct)}</td>
      </tr>
    </>
  );
}
