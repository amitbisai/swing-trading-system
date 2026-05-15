"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { formatCurrency } from "@/lib/utils";
import type { PortfolioSnapshot } from "@/lib/types";

interface Props {
  data: PortfolioSnapshot[];
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { value: number }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const value = payload[0].value;
  const isPositive = value >= 0;
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs shadow-xl">
      <p className="text-slate-400 mb-1">{label}</p>
      <p className={isPositive ? "text-emerald-400 font-mono" : "text-red-400 font-mono"}>
        {isPositive ? "+" : ""}{formatCurrency(String(value))}
      </p>
    </div>
  );
}

export function EquityCurveChart({ data }: Props) {
  if (data.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No history yet — run the nightly job to build an equity curve.
      </p>
    );
  }

  const chartData = data.map((s) => ({
    date: s.snapshot_date,
    pnl: parseFloat(s.cumulative_realized_pnl),
  }));

  const allNegative = chartData.every((d) => d.pnl < 0);
  const strokeColor = allNegative ? "#f87171" : "#34d399";
  const gradientId = allNegative ? "pnlRed" : "pnlGreen";
  const gradientColor = allNegative ? "#f87171" : "#34d399";

  return (
    <ResponsiveContainer width="100%" height={180}>
      <AreaChart data={chartData} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={gradientColor} stopOpacity={0.25} />
            <stop offset="95%" stopColor={gradientColor} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 10, fill: "#64748b" }}
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
        />
        <YAxis
          tick={{ fontSize: 10, fill: "#64748b" }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v: number) => `${v >= 0 ? "+" : ""}$${v}`}
          width={55}
        />
        <Tooltip content={<CustomTooltip />} />
        <Area
          type="monotone"
          dataKey="pnl"
          stroke={strokeColor}
          strokeWidth={2}
          fill={`url(#${gradientId})`}
          dot={false}
          activeDot={{ r: 4, fill: strokeColor }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
