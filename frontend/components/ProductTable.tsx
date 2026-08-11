import type { ContributionRow, ContributionTotal, ProductContribution } from "@/lib/api";
import { arrow, money, percent } from "@/lib/format";

function ChangeCells({ entry }: { entry: ContributionRow | ContributionTotal }) {
  const dirClass = entry.change_amt < 0 ? "dn" : entry.change_amt > 0 ? "up" : "";
  return (
    <>
      <td className={`num ${dirClass}`}>
        {entry.change_amt === 0 ? "—" : `${arrow(entry.change_amt)} ${money(entry.change_amt)}`}
      </td>
      <td className={`num ${dirClass}`}>{percent(entry.change_pct)}</td>
    </>
  );
}

/** The product-contribution table: class sections, subtotals, grand total. */
export default function ProductTable({
  data,
  fromLabel,
  toLabel,
}: {
  data: ProductContribution;
  fromLabel: string;
  toLabel: string;
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
          <SectionRows key={section.class_id} section={section} />
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

function SectionRows({ section }: { section: ProductContribution["sections"][number] }) {
  return (
    <>
      <tr className="sect">
        <td colSpan={6}>{section.class_name}</td>
      </tr>
      {section.rows.map((row) => (
        <tr key={row.group_id}>
          <td>
            {row.display_prefix ? <span className="pfx">{row.display_prefix} – </span> : null}
            {row.group_name}
          </td>
          <td className="num">{money(row.from_amt)}</td>
          <td className="num">{money(row.to_amt)}</td>
          <ChangeCells entry={row} />
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
