"use client";

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { tokens } from "@/components/design-system/design-tokens";
import { formatCurrency } from "@/lib/utils";

export type TrendPoint = {
  /** X-axis label (e.g. month or period). */
  label: string;
  value: number;
};

/** Generic single-series trend chart in the navy/blue design language. */
export function TrendChart({
  data,
  name = "Value",
  height = 280,
}: {
  data: TrendPoint[];
  name?: string;
  height?: number;
}) {
  return (
    <div className="w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 12, right: 20, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="trendGradient" x1="0" x2="0" y1="0" y2="1">
              <stop offset="5%" stopColor={tokens.color.chartNonrecurring} stopOpacity={0.35} />
              <stop offset="95%" stopColor={tokens.color.chartNonrecurring} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke={tokens.color.rule2} />
          <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: tokens.color.slate }} />
          <YAxis
            tickFormatter={(value) => formatCurrency(Number(value))}
            tickLine={false}
            axisLine={false}
            width={72}
            tick={{ fontSize: 11, fill: tokens.color.slate2 }}
          />
          <Tooltip formatter={(value) => [formatCurrency(Number(value)), name]} />
          <Area
            isAnimationActive={false}
            type="monotone"
            dataKey="value"
            name={name}
            stroke={tokens.color.navyHi}
            strokeWidth={2.5}
            fill="url(#trendGradient)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
