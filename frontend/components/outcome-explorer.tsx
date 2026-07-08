"use client";

import { useState } from "react";
import { Lightbulb } from "lucide-react";
import { cn } from "@/lib/utils";
import { useOutcomeAnalytics, type OutcomeAnalytics, type OutcomeBucket } from "@/lib/api";

// ── Shared helpers ────────────────────────────────────────────────────────────

const R_COLOR = (r: number | null) =>
  r == null ? "text-slate-500" : r > 0 ? "text-emerald-400" : "text-red-400";

function fmtR(r: number | null): string {
  if (r == null) return "—";
  return `${r > 0 ? "+" : ""}${r.toFixed(2)}R`;
}

// ── Variable picker + bucket bars ─────────────────────────────────────────────

const DIMENSIONS: { key: keyof OutcomeAnalytics; label: string }[] = [
  { key: "by_confidence",      label: "Confidence" },
  { key: "by_ta_score",        label: "TA" },
  { key: "by_sentiment_score", label: "Sentiment" },
  { key: "by_pattern_score",   label: "Pattern" },
  { key: "by_pulse",           label: "Pulse" },
  { key: "by_tier",            label: "Tier" },
  { key: "by_news_verdict",    label: "News" },
  { key: "by_levels_adjusted", label: "Trailing" },
];

/**
 * "What's driving profitability" — pick a signal variable, see win rate and
 * average R-multiple per bucket. This is the live counterpart of the backtest:
 * evidence for which inputs (sentiment, TA, pulse regime…) actually predict
 * profitable trades.
 */
export function OutcomeExplorer() {
  const { data } = useOutcomeAnalytics();
  const [dim, setDim] = useState<keyof OutcomeAnalytics>("by_confidence");

  const total = data?.total_outcomes ?? 0;

  return (
    <section className="space-y-2">
      <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wide">
        What&apos;s driving performance
      </h2>
      <div className="rounded-xl border border-slate-700 bg-slate-800 p-4 space-y-3">
        {total === 0 ? (
          <p className="text-sm text-slate-500">
            No closed trades yet — every exit automatically logs its signal
            scores, market context, and result here. Win rates and R-multiples
            per variable will appear as trades complete.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-1.5">
              {DIMENSIONS.map((d) => (
                <button
                  key={d.key}
                  onClick={() => setDim(d.key)}
                  className={cn(
                    "px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors",
                    dim === d.key
                      ? "bg-slate-200 text-slate-900 border-transparent"
                      : "text-slate-400 border-slate-700 hover:border-slate-500",
                  )}
                >
                  {d.label}
                </button>
              ))}
            </div>

            <BucketBars buckets={(data![dim] ?? {}) as Record<string, OutcomeBucket>} />

            {total < 20 && (
              <p className="text-[11px] text-slate-600">
                ⚠ Small sample ({total} closed trade{total !== 1 ? "s" : ""}) —
                treat as directional only until ~50+.
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}

function BucketBars({ buckets }: { buckets: Record<string, OutcomeBucket> }) {
  const entries = Object.entries(buckets);
  if (!entries.length) {
    return <p className="text-sm text-slate-500">No data for this variable yet.</p>;
  }
  return (
    <div className="space-y-2">
      {entries.map(([label, b]) => (
        <div key={label} className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-[11px] font-mono text-slate-400 text-right">
            {label}
          </span>
          {/* win-rate bar */}
          <div className="flex-1 h-4 rounded bg-slate-900 overflow-hidden relative">
            <div
              className={cn(
                "h-full rounded",
                (b.win_rate_pct ?? 0) >= 50 ? "bg-emerald-700" : "bg-red-900",
              )}
              style={{ width: `${b.win_rate_pct ?? 0}%` }}
            />
            <span className="absolute inset-y-0 left-2 flex items-center text-[10px] text-slate-300 font-mono">
              {b.win_rate_pct != null ? `${b.win_rate_pct.toFixed(0)}% win` : "—"}
            </span>
          </div>
          <span className={cn("w-14 shrink-0 text-[11px] font-mono text-right", R_COLOR(b.avg_r))}>
            {fmtR(b.avg_r)}
          </span>
          <span className="w-8 shrink-0 text-[10px] text-slate-600 font-mono text-right">
            n={b.trades}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Exit tuning card ──────────────────────────────────────────────────────────

const EXIT_LABELS: Record<string, string> = {
  STOP_HIT: "Stop hit",
  TARGET_HIT: "Target hit",
  TIME_EXIT: "Time exit",
  MANUAL_CLOSE: "Manual",
};

/**
 * Exit tuning — MFE/MAE analysis per exit reason, with plain-language insights
 * once the sample is meaningful. Directly answers "would longer holding /
 * wider stops have earned more?" without any manual analysis.
 */
export function ExitTuningCard() {
  const { data } = useOutcomeAnalytics();
  const buckets = data?.by_exit_reason ?? {};
  const entries = Object.entries(buckets).filter(([k]) => k !== "unknown");
  if (!entries.length) return null;

  // Auto-insights (only with a workable sample per group)
  const insights: string[] = [];
  const stop = buckets["STOP_HIT"];
  const time = buckets["TIME_EXIT"];
  if (stop && stop.trades >= 10 && (stop.avg_post_exit_10d_pct ?? 0) > 1) {
    insights.push(
      `Stopped-out trades recover +${stop.avg_post_exit_10d_pct!.toFixed(1)}% on average within 10 days — stops may be too tight (consider a wider ATR_STOP_MULT and verify in a backtest).`,
    );
  }
  if (
    time && time.trades >= 10 &&
    (time.avg_exit_efficiency ?? 1) < 0.5 &&
    (time.avg_post_exit_10d_pct ?? 0) > 0
  ) {
    insights.push(
      `Time-exited trades captured only ${(time.avg_exit_efficiency! * 100).toFixed(0)}% of their best price and kept rising +${time.avg_post_exit_10d_pct!.toFixed(1)}% after exit — a longer MAX_HOLDING_DAYS is worth backtesting.`,
    );
  }

  return (
    <section className="space-y-2">
      <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wide">
        Exit tuning (MFE / MAE)
      </h2>
      <div className="rounded-xl border border-slate-700 bg-slate-800 p-4 space-y-3">
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-slate-500 text-left">
                <th className="pb-2 font-medium">Exit</th>
                <th className="pb-2 font-medium text-right">n</th>
                <th className="pb-2 font-medium text-right">Avg R</th>
                <th className="pb-2 font-medium text-right" title="Best price reached during the hold, in R">Best (MFE)</th>
                <th className="pb-2 font-medium text-right" title="Worst drawdown during the hold, in R">Worst (MAE)</th>
                <th className="pb-2 font-medium text-right" title="Captured gain ÷ max available gain">Captured</th>
                <th className="pb-2 font-medium text-right" title="Stock move in the 10 days AFTER exit">After +10d</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {entries.map(([reason, b]) => (
                <tr key={reason} className="border-t border-slate-700/60">
                  <td className="py-1.5 font-sans text-slate-300">
                    {EXIT_LABELS[reason] ?? reason}
                  </td>
                  <td className="py-1.5 text-right text-slate-400">{b.trades}</td>
                  <td className={cn("py-1.5 text-right", R_COLOR(b.avg_r))}>{fmtR(b.avg_r)}</td>
                  <td className="py-1.5 text-right text-emerald-500">{fmtR(b.avg_mfe_r)}</td>
                  <td className="py-1.5 text-right text-red-500">{fmtR(b.avg_mae_r)}</td>
                  <td className="py-1.5 text-right text-slate-300">
                    {b.avg_exit_efficiency != null
                      ? `${(b.avg_exit_efficiency * 100).toFixed(0)}%`
                      : "—"}
                  </td>
                  <td className={cn(
                    "py-1.5 text-right",
                    (b.avg_post_exit_10d_pct ?? 0) > 0 ? "text-emerald-400" : "text-slate-400",
                  )}>
                    {b.avg_post_exit_10d_pct != null
                      ? `${b.avg_post_exit_10d_pct > 0 ? "+" : ""}${b.avg_post_exit_10d_pct.toFixed(1)}%`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {insights.length > 0 ? (
          <div className="space-y-1.5">
            {insights.map((text, i) => (
              <p key={i} className="flex gap-1.5 text-[11px] text-amber-300/90 bg-amber-950/30 border border-amber-900/40 rounded-lg px-2.5 py-1.5">
                <Lightbulb className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                {text}
              </p>
            ))}
          </div>
        ) : (
          <p className="text-[10px] text-slate-600">
            Insights appear automatically once each exit type has ≥10 trades.
          </p>
        )}
      </div>
    </section>
  );
}
