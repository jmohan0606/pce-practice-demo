"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { tokens } from "@/components/design-system/design-tokens";
import { formatCurrency } from "@/lib/utils";

export type StackedBarPoint = {
  /** X-axis label (e.g. month). */
  label: string;
  /** Bottom (tan) segment — mockup "Recurring". */
  primary: number;
  /** Top (blue) segment — mockup "Non-Recurring". */
  secondary: number;
};

/**
 * Generic tan/blue stacked bar chart matching the mockup design language
 * (docs/ui/mockups.html: .sr recurring tan, .sn non-recurring blue).
 */
export function StackedBarChart({
  data,
  primaryName = "Recurring",
  secondaryName = "Non-Recurring",
  height = 280,
}: {
  data: StackedBarPoint[];
  primaryName?: string;
  secondaryName?: string;
  height?: number;
}) {
  return (
    <div className="w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 12, right: 20, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke={tokens.color.rule2} />
          <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: tokens.color.slate }} />
          <YAxis
            tickFormatter={(value) => formatCurrency(Number(value))}
            tickLine={false}
            axisLine={false}
            width={72}
            tick={{ fontSize: 11, fill: tokens.color.slate2 }}
          />
          <Tooltip formatter={(value) => formatCurrency(Number(value))} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar isAnimationActive={false} dataKey="primary" name={primaryName} stackId="s" fill={tokens.color.chartRecurring} />
          <Bar isAnimationActive={false} dataKey="secondary" name={secondaryName} stackId="s" fill={tokens.color.chartNonrecurring} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
