"use client";

import { Loader2 } from "lucide-react";
import { StatCard } from "@/components/stat-card";
import { EquityCurveChart } from "@/components/analytics-chart";
import { TierComparisonChart } from "@/components/tier-comparison";
import { useAnalyticsSummary, usePortfolioHistory, usePaperTrades } from "@/lib/api";
import { formatCurrency, formatPct } from "@/lib/utils";

export default function AnalyticsPage() {
  const { data: summary, isLoading: summaryLoading } = useAnalyticsSummary();
  const { data: history, isLoading: historyLoading } = usePortfolioHistory(60);
  const { data: closedTrades } = usePaperTrades("closed");

  // Compute T1 vs T2 win rate client-side from closed trades + suggestion ids
  // We don't have tier on PaperTrade, so we rely on summary for aggregate stats
  // and show a placeholder tier split when we have no tier info.
  // The tier comparison chart will use the overall win rate for now.
  const tierStats = (() => {
    if (!summary) return [];
    const { win_rate_pct } = summary.trades;
    return [
      { tier: "T1" as const, winRate: win_rate_pct, trades: summary.trades.closed_trades },
      { tier: "T2" as const, winRate: win_rate_pct, trades: 0 },
    ].filter((s) => s.trades > 0);
  })();

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
