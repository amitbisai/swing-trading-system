"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface TierStat {
  tier: "T1" | "T2";
  winRate: number;
  trades: number;
}

interface Props {
  stats: TierStat[];
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { value: number; payload: TierStat }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0];
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs shadow-xl">
      <p className="text-slate-300 font-semibold mb-1">{label}</p>
      <p className="text-white font-mono">{d.value.toFixed(1)}% win rate</p>
      <p className="text-slate-400">{d.payload.trades} closed trades</p>
    </div>
  );
}

export function TierComparisonChart({ stats }: Props) {
  if (!stats.length) {
    return (
      <p className="text-sm text-slate-500">
        No closed trades yet — win rates will appear after trades close.
      </p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={stats} margin={{ top: 4, right: 4, left: 0, bottom: 0 }} barSize={48}>
        <XAxis
          dataKey="tier"
          tick={{ fontSize: 12, fill: "#94a3b8", fontWeight: 600 }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          domain={[0, 100]}
          tick={{ fontSize: 10, fill: "#64748b" }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v: number) => `${v}%`}
          width={36}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
        <Bar dataKey="winRate" radius={[4, 4, 0, 0]}>
          {stats.map((entry) => (
            <Cell
              key={entry.tier}
              fill={entry.tier === "T1" ? "#3b82f6" : "#f59e0b"}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
