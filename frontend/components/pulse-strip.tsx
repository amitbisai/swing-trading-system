"use client";

import { usePulseHistory } from "@/lib/api";

const BAR_COLOR = (score: number) =>
  score >= 75 ? "bg-emerald-500" :
  score >= 60 ? "bg-emerald-700" :
  score >= 45 ? "bg-amber-500" :
  score >= 30 ? "bg-orange-500" :
  "bg-red-500";

/**
 * Mini timeline of the daily market pulse (0–100). Height + colour encode the
 * score; hover shows date/score/breadth. Renders nothing until the pulse log
 * has data (it accumulates one row per trading day).
 */
export function PulseStrip() {
  const { data } = usePulseHistory(30);
  if (!data?.length) return null;

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-4 space-y-2">
      <div className="flex items-baseline justify-between">
        <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wide">
          Market pulse — last {data.length} trading day{data.length !== 1 ? "s" : ""}
        </h3>
        <span className="text-[10px] text-slate-600">
          height &amp; colour = market health → entries allowed
        </span>
      </div>
      <div className="flex items-end gap-[3px] h-16">
        {data.map((d) => (
          <div
            key={d.date}
            className={`flex-1 rounded-sm ${BAR_COLOR(d.score)} opacity-80 hover:opacity-100 transition-opacity min-w-[4px]`}
            style={{ height: `${Math.max(d.score, 4)}%` }}
            title={`${d.date} — pulse ${d.score}/100 (${d.label})${
              d.breadth_pct != null ? ` · breadth ${(d.breadth_pct * 100).toFixed(0)}%` : ""
            }`}
          />
        ))}
      </div>
      <div className="flex justify-between text-[10px] text-slate-600 font-mono">
        <span>{data[0].date}</span>
        <span>{data[data.length - 1].date}</span>
      </div>
    </div>
  );
}
