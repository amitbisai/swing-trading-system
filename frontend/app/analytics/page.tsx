"use client";

import { useEffect, useState } from "react";
import { Check, Loader2, Settings2 } from "lucide-react";
import { StatCard } from "@/components/stat-card";
import { EquityCurveChart } from "@/components/analytics-chart";
import { TierComparisonChart } from "@/components/tier-comparison";
import {
  updateStrategySettings,
  useAnalyticsSummary,
  usePortfolioHistory,
  useStrategySettings,
} from "@/lib/api";
import { formatCurrency } from "@/lib/utils";

// ── Strategy settings (top-N daily entry cap) ─────────────────────────────────

function StrategySettingsCard() {
  const { data: current, mutate } = useStrategySettings();
  const [value, setValue] = useState<string>("");
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");

  useEffect(() => {
    if (current) setValue(String(current.max_entries_per_day));
  }, [current]);

  async function handleSave() {
    const n = parseInt(value, 10);
    if (isNaN(n) || n < 0 || n > 100) {
      setErrorMsg("Enter a number between 0 and 100 (0 = unlimited).");
      setStatus("error");
      return;
    }
    setStatus("saving");
    setErrorMsg("");
    try {
      await updateStrategySettings({ max_entries_per_day: n });
      await mutate();
      setStatus("saved");
      setTimeout(() => setStatus("idle"), 2000);
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : "Failed to save.");
      setStatus("error");
    }
  }

  const dirty = current !== undefined && value !== String(current.max_entries_per_day);

  return (
    <section className="space-y-2">
      <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wide">Strategy</h2>
      <div className="rounded-xl border border-slate-700 bg-slate-800 p-4 space-y-2">
        <div className="flex items-center gap-2">
          <Settings2 className="h-4 w-4 text-slate-400 shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-white">Top-N trades per day</p>
            <p className="text-xs text-slate-500">
              Auto-entry takes only the N highest-confidence signals each day. 0 = unlimited.
            </p>
          </div>
          <input
            type="number" min={0} max={100} step={1}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-16 bg-slate-900 border border-slate-600 rounded-lg px-2 py-1.5
                       text-sm font-mono text-white text-center focus:outline-none
                       focus:border-slate-400 [appearance:textfield]
                       [&::-webkit-outer-spin-button]:appearance-none
                       [&::-webkit-inner-spin-button]:appearance-none"
            disabled={status === "saving" || current === undefined}
          />
          <button
            onClick={handleSave}
            disabled={!dirty || status === "saving"}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-700
                       hover:bg-slate-600 text-white transition-colors
                       disabled:opacity-40 disabled:cursor-not-allowed
                       flex items-center gap-1.5"
          >
            {status === "saving" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : status === "saved" ? (
              <Check className="h-3.5 w-3.5 text-emerald-400" />
            ) : null}
            {status === "saved" ? "Saved" : "Save"}
          </button>
        </div>
        {status === "error" && <p className="text-xs text-red-400">{errorMsg}</p>}
      </div>
    </section>
  );
}

export default function AnalyticsPage() {
  const { data: summary, isLoading: summaryLoading } = useAnalyticsSummary();
  const { data: history, isLoading: historyLoading } = usePortfolioHistory(60);

  // Real per-tier performance from the backend (trades joined to their
  // suggestion's tier).
  const tierStats = (summary?.tiers ?? []).map((t) => ({
    tier: t.tier as "T1" | "T2",
    winRate: t.win_rate_pct,
    trades: t.closed_trades,
  }));

  if (summaryLoading) {
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
      </div>
    );
  }

  return (
    <div className="px-4 py-5 max-w-2xl mx-auto space-y-6">
      <h1 className="text-xl font-bold text-white">Analytics</h1>

      {/* ── Strategy settings ── */}
      <StrategySettingsCard />

      {/* ── Capital stats ── */}
      {summary && (
        <section className="space-y-2">
          <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wide">Capital</h2>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <StatCard
              label="Current Capital"
              value={formatCurrency(summary.capital.current_capital)}
              mono
            />
            <StatCard
              label="Total Return"
              value={`${summary.capital.total_return_pct >= 0 ? "+" : ""}${summary.capital.total_return_pct.toFixed(2)}%`}
              positive={summary.capital.total_return_pct >= 0}
              negative={summary.capital.total_return_pct < 0}
              mono
            />
            <StatCard
              label="Realized P&L"
              value={formatCurrency(summary.capital.cumulative_realized_pnl)}
              positive={parseFloat(summary.capital.cumulative_realized_pnl) >= 0}
              negative={parseFloat(summary.capital.cumulative_realized_pnl) < 0}
              mono
            />
          </div>
        </section>
      )}

      {/* ── Equity curve ── */}
      <section className="space-y-3">
        <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wide">Equity Curve (60d)</h2>
        <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
          {historyLoading ? (
            <div className="flex justify-center py-10">
              <Loader2 className="h-5 w-5 animate-spin text-slate-500" />
            </div>
          ) : (
            <EquityCurveChart data={history ?? []} />
          )}
        </div>
      </section>

      {/* ── Trade stats ── */}
      {summary && (
        <section className="space-y-2">
          <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wide">Trade Performance</h2>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatCard
              label="Win Rate"
              value={`${summary.trades.win_rate_pct.toFixed(1)}%`}
              positive={summary.trades.win_rate_pct >= 50}
              negative={summary.trades.win_rate_pct < 50}
            />
            <StatCard
              label="Closed Trades"
              value={String(summary.trades.closed_trades)}
              sub={`${summary.trades.winning_trades}W / ${summary.trades.losing_trades}L`}
            />
            <StatCard
              label="Avg P&L"
              value={formatCurrency(summary.trades.avg_realized_pnl)}
              positive={parseFloat(summary.trades.avg_realized_pnl) >= 0}
              negative={parseFloat(summary.trades.avg_realized_pnl) < 0}
              mono
            />
            <StatCard
              label="Open Trades"
              value={String(summary.trades.open_trades)}
            />
          </div>
          {summary.trades.best_trade_pnl && summary.trades.worst_trade_pnl && (
            <div className="grid grid-cols-2 gap-2">
              <StatCard
                label="Best Trade"
                value={formatCurrency(summary.trades.best_trade_pnl)}
                positive
                mono
              />
              <StatCard
                label="Worst Trade"
                value={formatCurrency(summary.trades.worst_trade_pnl)}
                negative
                mono
              />
            </div>
          )}
        </section>
      )}

      {/* ── Tier comparison ── */}
      <section className="space-y-3">
        <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wide">T1 vs T2 Win Rate</h2>
        <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
          <TierComparisonChart stats={tierStats} />
        </div>
      </section>

      {/* ── Suggestion stats ── */}
      {summary && (
        <section className="space-y-2">
          <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wide">Signal Coverage</h2>
          <div className="grid grid-cols-3 gap-2">
            <StatCard label="Total Signals" value={String(summary.suggestions.total_suggestions)} />
            <StatCard label="Today" value={String(summary.suggestions.suggestions_today)} />
            <StatCard
              label="Avg Confidence"
              value={`${summary.suggestions.avg_confidence.toFixed(0)}/100`}
              positive={summary.suggestions.avg_confidence >= 70}
            />
          </div>
        </section>
      )}

      {summary && (
        <p className="text-center text-xs text-slate-600">As of {summary.as_of}</p>
      )}
    </div>
  );
}
