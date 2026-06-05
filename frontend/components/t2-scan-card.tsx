"use client";

import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { T2Scan, T2SignalTier, NewsVerdict } from "@/lib/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtCap(raw: string | null): string {
  if (!raw) return "—";
  const v = parseFloat(raw);
  if (isNaN(v)) return "—";
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  return `$${(v / 1e6).toFixed(0)}M`;
}

function fmtVol(raw: string | null): string {
  if (!raw) return "—";
  const v = parseFloat(raw);
  if (isNaN(v)) return "—";
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  return `${(v / 1e3).toFixed(0)}K`;
}

/**
 * Parse "+3.2% today" out of signal_summary so it can be shown as a metric cell.
 * Returns the numeric value (e.g. 3.2) or null if not found.
 */
function parseTodayChange(summary: string | null): number | null {
  if (!summary) return null;
  const m = summary.match(/([+-]?\d+\.?\d*)%\s*today/i);
  return m ? parseFloat(m[1]) : null;
}

/**
 * Parse "⚠️ earnings Nd" out of signal_summary.
 * Returns days (e.g. 15) or null.
 */
function parseEarningsDays(summary: string | null): number | null {
  if (!summary) return null;
  const m = summary.match(/earnings\s+(\d+)d/i);
  return m ? parseInt(m[1], 10) : null;
}

// ── Tier badge ────────────────────────────────────────────────────────────────

const TIER_CONFIG: Record<T2SignalTier, { label: string; cls: string }> = {
  A: { label: "Tier A", cls: "bg-emerald-900/40 text-emerald-300 border-emerald-700/50" },
  B: { label: "Tier B", cls: "bg-blue-900/40    text-blue-300    border-blue-700/50"    },
  C: { label: "Tier C", cls: "bg-slate-800       text-slate-400   border-slate-700"      },
};

function TierBadge({ tier }: { tier: T2SignalTier }) {
  const { label, cls } = TIER_CONFIG[tier];
  return (
    <span className={cn("px-2 py-0.5 rounded text-xs font-bold border", cls)}>
      {label}
    </span>
  );
}

// ── T2 score bar ──────────────────────────────────────────────────────────────

function ScoreBar({ score }: { score: number }) {
  const pct   = Math.min(100, Math.max(0, score));
  const color = pct >= 65 ? "bg-emerald-500" : pct >= 45 ? "bg-blue-500" : "bg-slate-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-semibold text-white tabular-nums w-8 text-right">
        {pct.toFixed(0)}
      </span>
    </div>
  );
}

// ── Risk flags ────────────────────────────────────────────────────────────────
// Each flag has its own severity colour so traders can triage at a glance.

const FLAG_STYLE: Record<string, string> = {
  earnings_approaching:  "bg-orange-900/50 text-orange-300 border-orange-700/50",
  pre_revenue_biotech:   "bg-red-900/40    text-red-300    border-red-700/40",
  extreme_volatility:    "bg-red-900/40    text-red-300    border-red-700/40",
  high_short_interest:   "bg-orange-900/40 text-orange-300 border-orange-700/40",
  parabolic_extension:   "bg-red-900/40    text-red-300    border-red-700/40",
  weak_fundamentals:     "bg-amber-900/40  text-amber-400  border-amber-700/40",
  very_low_float:        "bg-amber-900/40  text-amber-400  border-amber-700/40",
  thin_liquidity:        "bg-amber-900/40  text-amber-400  border-amber-700/40",
};

const FLAG_LABEL: Record<string, string> = {
  earnings_approaching:  "⚠️ Earnings soon",
  pre_revenue_biotech:   "🔴 Pre-revenue biotech",
  extreme_volatility:    "🔴 Extreme volatility",
  high_short_interest:   "🟠 High short interest",
  parabolic_extension:   "🔴 Parabolic — extended",
  weak_fundamentals:     "🟡 Weak fundamentals",
  very_low_float:        "🟡 Very low float",
  thin_liquidity:        "🟡 Thin liquidity",
};

function RiskPill({ flag }: { flag: string }) {
  const cls   = FLAG_STYLE[flag] ?? "bg-amber-900/40 text-amber-400 border-amber-700/40";
  const label = FLAG_LABEL[flag] ?? flag.replace(/_/g, " ");
  return (
    <span className={cn("px-1.5 py-0.5 rounded text-xs border font-medium", cls)}>
      {label}
    </span>
  );
}

// ── News block ────────────────────────────────────────────────────────────────

const VERDICT_CONFIG: Record<NewsVerdict, { label: string; dot: string; text: string }> = {
  SUPPORTS:    { label: "News supports",    dot: "bg-emerald-400", text: "text-emerald-400" },
  NEUTRAL:     { label: "News neutral",     dot: "bg-slate-400",   text: "text-slate-400"   },
  CONTRADICTS: { label: "News contradicts", dot: "bg-red-400",     text: "text-red-400"     },
};

function NewsBlock({ summary, verdict }: { summary: string | null; verdict: NewsVerdict | null }) {
  const cfg = verdict ? VERDICT_CONFIG[verdict] : VERDICT_CONFIG.NEUTRAL;
  return (
    <div className="pt-3 border-t border-slate-700/60 space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className={cn("w-2 h-2 rounded-full flex-shrink-0", cfg.dot)} />
        <span className={cn("text-xs font-medium", cfg.text)}>{cfg.label}</span>
      </div>
      {summary && <p className="text-xs text-slate-400 leading-relaxed">{summary}</p>}
    </div>
  );
}

// ── Metric cell ───────────────────────────────────────────────────────────────

function MetricCell({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-slate-900/60 rounded-lg p-2 text-xs">
      <p className="text-slate-500 mb-0.5">{label}</p>
      <p className={cn("font-semibold", color ?? "text-white")}>{value}</p>
    </div>
  );
}

// ── Main card ─────────────────────────────────────────────────────────────────

export function T2ScanCard({ scan }: { scan: T2Scan }) {
  const revGrowthPct  = scan.revenue_growth  != null ? scan.revenue_growth  * 100 : null;
  const earnGrowthPct = scan.earnings_growth != null ? scan.earnings_growth * 100 : null;

  // Parse derived fields out of signal_summary
  const todayChangePct  = parseTodayChange(scan.signal_summary);
  const earningsDays    = parseEarningsDays(scan.signal_summary);

  // Determine earnings banner urgency
  const hasEarningsFlag = scan.risk_flags.includes("earnings_approaching");
  const earningsUrgent  = earningsDays != null && earningsDays <= 14;

  // Strip the "⚠️ earnings Nd" token from signal_summary before displaying it
  // (we render it as a proper banner instead)
  const cleanSummary = scan.signal_summary
    ?.replace(/[⚠️\s]*earnings\s+\d+d\s*\|?\s*/gi, "")
    ?.replace(/\|\s*$/, "")
    ?.trim() ?? null;

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800/70 overflow-hidden hover:border-slate-600 transition-colors">

      {/* ── Earnings banner — shown when earnings_approaching flag present ─── */}
      {hasEarningsFlag && earningsDays != null && (
        <div className={cn(
          "flex items-center gap-2 px-4 py-2 text-xs font-medium border-b",
          earningsUrgent
            ? "bg-orange-900/60 text-orange-200 border-orange-700/60"
            : "bg-yellow-900/40 text-yellow-300 border-yellow-700/40",
        )}>
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span>
            Earnings in <strong>{earningsDays} day{earningsDays === 1 ? "" : "s"}</strong>
            {earningsUrgent ? " — trade with caution" : " — monitor closely"}
          </span>
        </div>
      )}

      <div className="p-4 space-y-3">

        {/* ── Header ─────────────────────────────────────────────────────────── */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-base font-bold text-white">{scan.symbol}</span>
              <TierBadge tier={scan.signal_tier} />
              {scan.catalyst_hint && (
                <span className="px-1.5 py-0.5 rounded text-xs bg-violet-900/40 text-violet-300 border border-violet-700/40">
                  {scan.catalyst_hint}
                </span>
              )}
            </div>
            {scan.sector && (
              <p className="text-xs text-slate-500 mt-0.5 truncate">
                {scan.sector}{scan.industry ? ` / ${scan.industry}` : ""}
              </p>
            )}
          </div>
          <div className="text-right flex-shrink-0">
            <p className="text-base font-semibold text-white">
              ${parseFloat(scan.price).toFixed(2)}
            </p>
            {/* Today's change — parsed from signal_summary */}
            {todayChangePct != null && (
              <p className={cn(
                "text-xs font-medium tabular-nums",
                todayChangePct >= 0 ? "text-emerald-400" : "text-red-400",
              )}>
                {todayChangePct >= 0 ? "+" : ""}{todayChangePct.toFixed(1)}% today
              </p>
            )}
            <p className="text-xs text-slate-500">{scan.scan_date}</p>
          </div>
        </div>

        {/* ── T2 Score bar ──────────────────────────────────────────────────── */}
        <div>
          <div className="flex justify-between items-center mb-1">
            <span className="text-xs text-slate-500">T2 Score</span>
          </div>
          <ScoreBar score={scan.t2_score} />
        </div>

        {/* ── Metrics grid ──────────────────────────────────────────────────── */}
        <div className="grid grid-cols-3 gap-2">
          <MetricCell
            label="RVOL"
            value={`${scan.rvol.toFixed(1)}×`}
            color={scan.rvol >= 2.5 ? "text-emerald-400" : scan.rvol >= 1.5 ? "text-blue-300" : "text-white"}
          />
          <MetricCell label="Mkt Cap"  value={fmtCap(scan.market_cap)} />
          <MetricCell label="Avg Vol"  value={fmtVol(scan.avg_volume_30d)} />
          <MetricCell
            label="52W Hi"
            value={scan.pct_below_52w_high != null
              ? `${(scan.pct_below_52w_high * 100).toFixed(1)}% off`
              : "—"}
            color={(scan.pct_below_52w_high ?? 1) < 0.05 ? "text-emerald-400" : "text-white"}
          />
          <MetricCell
            label="Rev Gr"
            value={revGrowthPct != null
              ? `${revGrowthPct > 0 ? "+" : ""}${revGrowthPct.toFixed(0)}%`
              : "—"}
            color={revGrowthPct != null
              ? (revGrowthPct > 0 ? "text-emerald-400" : "text-red-400")
              : "text-slate-400"}
          />
          <MetricCell
            label="Earn Gr"
            value={earnGrowthPct != null
              ? `${earnGrowthPct > 0 ? "+" : ""}${earnGrowthPct.toFixed(0)}%`
              : "—"}
            color={earnGrowthPct != null
              ? (earnGrowthPct > 0 ? "text-emerald-400" : "text-red-400")
              : "text-slate-400"}
          />
        </div>

        {/* ── Signal summary (cleaned) ───────────────────────────────────────── */}
        {cleanSummary && (
          <p className="text-xs text-slate-300 leading-relaxed bg-slate-900/40 rounded-lg px-3 py-2">
            {cleanSummary}
          </p>
        )}

        {/* ── Risk flags ────────────────────────────────────────────────────── */}
        {scan.risk_flags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {/* Sort: red flags first */}
            {[...scan.risk_flags]
              .sort((a, b) => {
                const order: Record<string, number> = {
                  pre_revenue_biotech:  0,
                  extreme_volatility:   0,
                  parabolic_extension:  0,
                  earnings_approaching: 1,
                  high_short_interest:  1,
                  weak_fundamentals:    2,
                  very_low_float:       2,
                  thin_liquidity:       2,
                };
                return (order[a] ?? 3) - (order[b] ?? 3);
              })
              .map(f => <RiskPill key={f} flag={f} />)
            }
          </div>
        )}

        {/* ── News verdict ──────────────────────────────────────────────────── */}
        <NewsBlock summary={scan.news_summary} verdict={scan.news_verdict as NewsVerdict | null} />

      </div>
    </div>
  );
}
