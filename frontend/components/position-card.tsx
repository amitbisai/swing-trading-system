"use client";

import { cn, formatCurrency, formatPct } from "@/lib/utils";
import { TrendingUp, TrendingDown, Clock } from "lucide-react";
import type { PaperTrade } from "@/lib/types";

interface Props {
  trade: PaperTrade;
}

function PositionBar({
  stop,
  entry,
  target,
  direction,
}: {
  stop: number;
  entry: number;
  target: number;
  direction: "LONG" | "SHORT";
}) {
  const range = target - stop;
  if (range <= 0) return null;

  const entryPct = ((entry - stop) / range) * 100;

  return (
    <div className="relative h-2 rounded-full bg-slate-700 overflow-hidden">
      {/* Stop → Entry segment (red) */}
      <div
        className="absolute left-0 top-0 h-full bg-red-800"
        style={{ width: `${entryPct}%` }}
      />
      {/* Entry → Target segment (green) */}
      <div
        className="absolute top-0 h-full bg-emerald-800"
        style={{ left: `${entryPct}%`, right: "0%" }}
      />
      {/* Entry marker */}
      <div
        className="absolute top-0 h-full w-0.5 bg-white"
        style={{ left: `${entryPct}%` }}
      />
    </div>
  );
}

export function PositionCard({ trade: t }: Props) {
  const isLong = t.direction === "LONG";
  const entry = parseFloat(t.entry_price);
  const stop = parseFloat(t.stop_loss);
  const target = parseFloat(t.target_price);

  const stopPct = Math.abs(((entry - stop) / entry) * 100);
  const targetPct = Math.abs(((target - entry) / entry) * 100);

  const unrealizedPnl = t.realized_pnl !== null ? null : null; // only available after EOD mark

  return (
    <article className="rounded-xl border border-slate-700 bg-slate-800 p-4 space-y-3">

      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-lg font-bold text-white truncate">{t.symbol}</span>
          <span
            className={cn(
              "flex items-center gap-0.5 text-xs font-semibold px-2 py-0.5 rounded-full shrink-0",
              isLong
                ? "bg-emerald-900/60 text-emerald-400"
                : "bg-red-900/60 text-red-400",
            )}
          >
            {isLong ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
            {t.direction}
          </span>
        </div>
        <div className="text-right shrink-0">
          <p className="text-xs text-slate-500">Shares</p>
          <p className="text-sm font-mono text-white">{t.shares}</p>
        </div>
      </div>

      {/* ── Price grid ── */}
      <div className="grid grid-cols-3 gap-1 text-center">
        <div className="rounded-lg bg-slate-900 p-2">
          <p className="text-[10px] text-slate-500 mb-0.5">Entry</p>
          <p className="font-mono text-sm text-white">{formatCurrency(t.entry_price)}</p>
        </div>
        <div className="rounded-lg bg-slate-900 p-2">
          <p className="text-[10px] text-slate-500 mb-0.5">Stop</p>
          <p className="font-mono text-sm text-red-400">{formatCurrency(t.stop_loss)}</p>
        </div>
        <div className="rounded-lg bg-slate-900 p-2">
          <p className="text-[10px] text-slate-500 mb-0.5">Target</p>
          <p className="font-mono text-sm text-emerald-400">{formatCurrency(t.target_price)}</p>
        </div>
      </div>

      {/* ── R:R progress bar (stop → entry → target) ── */}
      <div className="space-y-1.5">
        <PositionBar stop={stop} entry={entry} target={target} direction={t.direction} />
        <div className="flex justify-between text-[10px] text-slate-500 font-mono">
          <span>-{stopPct.toFixed(1)}%</span>
          <span className="text-slate-400">Entry</span>
          <span>+{targetPct.toFixed(1)}%</span>
        </div>
      </div>

      {/* ── P&L / status row ── */}
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-1.5 text-slate-400">
          <Clock className="h-3.5 w-3.5" />
          <span>Since {t.entry_date}</span>
        </div>
        <div className="flex items-center gap-1 text-slate-400">
          <span className="text-[10px]">P&amp;L</span>
          <span className="font-mono text-slate-300">EOD update</span>
        </div>
      </div>

      {/* ── Capital at risk ── */}
      <div className="flex justify-between text-xs text-slate-500">
        <span>Capital at risk</span>
        <span className="font-mono text-slate-300">{formatCurrency(t.capital_at_risk)}</span>
      </div>
    </article>
  );
}

interface ClosedPositionCardProps {
  trade: PaperTrade;
}

export function ClosedPositionCard({ trade: t }: ClosedPositionCardProps) {
  const isLong = t.direction === "LONG";
  const pnl = t.realized_pnl ? parseFloat(t.realized_pnl) : 0;
  const isProfit = pnl >= 0;

  return (
    <article className="rounded-xl border border-slate-700/60 bg-slate-800/60 p-4 space-y-2 opacity-80">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-base font-bold text-slate-300 truncate">{t.symbol}</span>
          <span
            className={cn(
              "text-[10px] font-semibold px-1.5 py-0.5 rounded-full shrink-0",
              isLong ? "bg-emerald-900/40 text-emerald-500" : "bg-red-900/40 text-red-500",
            )}
          >
            {t.direction}
          </span>
          {t.exit_reason && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-700 text-slate-400">
              {t.exit_reason.replace("_", " ")}
            </span>
          )}
        </div>
        <span
          className={cn(
            "text-sm font-mono font-semibold shrink-0",
            isProfit ? "text-emerald-400" : "text-red-400",
          )}
        >
          {isProfit ? "+" : ""}{formatCurrency(t.realized_pnl ?? "0")}
        </span>
      </div>

      <div className="flex justify-between text-xs text-slate-500">
        <span>{t.entry_date} → {t.exit_date ?? "—"}</span>
        <span className="font-mono">
          {t.entry_price} → {t.exit_price ?? "—"}
        </span>
      </div>
    </article>
  );
}
