"use client";

import { cn } from "@/lib/utils";
import type { T2Scan, T2SignalTier, NewsVerdict } from "@/lib/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: string | number | null | undefined, prefix = "", suffix = ""): string {
  if (n == null) return "—";
  const v = typeof n === "string" ? parseFloat(n) : n;
  if (isNaN(v)) return "—";
  return `${prefix}${v.toLocaleString()}${suffix}`;
}

function fmtPct(n: number | null | undefined, decimals = 1): string {
  if (n == null) return "—";
  return `${(n * 100).toFixed(decimals)}%`;
}

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

// ── Sub-components ────────────────────────────────────────────────────────────

const TIER_CONFIG: Record<T2SignalTier, { label: string; bg: string; text: string; border: string }> = {
  A: { label: "Tier A", bg: "bg-emerald-900/40", text: "text-emerald-300", border: "border-emerald-700/50" },
  B: { label: "Tier B", bg: "bg-blue-900/40",    text: "text-blue-300",    border: "border-blue-700/50"    },
  C: { label: "Tier C", bg: "bg-slate-800",       text: "text-slate-400",  border: "border-slate-700"      },
};

const VERDICT_CONFIG: Record<NewsVerdict, { label: string; dot: string; text: string }> = {
  SUPPORTS:    { label: "News supports",    dot: "bg-emerald-400", text: "text-emerald-400" },
  NEUTRAL:     { label: "News neutral",     dot: "bg-slate-400",   text: "text-slate-400"   },
  CONTRADICTS: { label: "News contradicts", dot: "bg-red-400",     text: "text-red-400"     },
};

function TierBadge({ tier }: { tier: T2SignalTier }) {
  const cfg = TIER_CONFIG[tier];
  return (
    <span className={cn("px-2 py-0.5 rounded text-xs font-bold border", cfg.bg, cfg.text, cfg.border)}>
      {cfg.label}
    </span>
  );
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, score));
  const color = pct >= 65 ? "bg-emerald-500" : pct >= 45 ? "bg-blue-500" : "bg-slate-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-semibold text-white tabular-nums w-8 text-right">{pct.toFixed(0)}</span>
    </div>
  );
}

function RiskFlag({ flag }: { flag: string }) {
  return (
    <span className="px-1.5 py-0.5 rounded text-xs bg-amber-900/40 text-amber-400 border border-amber-700/40">
      {flag.replace(/_/g, " ")}
    </span>
  );
}

function NewsBlock({ summary, verdict }: { summary: string | null; verdict: NewsVerdict | null }) {
  const cfg = verdict ? VERDICT_CONFIG[verdict] : VERDICT_CONFIG.NEUTRAL;
  return (
    <div className="mt-3 pt-3 border-t border-slate-700/60 space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className={cn("w-2 h-2 rounded-full flex-shrink-0", cfg.dot)} />
        <span className={cn("text-xs font-medium", cfg.text)}>{cfg.label}</span>
      </div>
      {summary && (
        <p className="text-xs text-slate-400 leading-relaxed">{summary}</p>
      )}
    </div>
  );
}

// ── Main card ─────────────────────────────────────────────────────────────────

export function T2ScanCard({ scan }: { scan: T2Scan }) {
  const revGrowthPct = scan.revenue_growth != null ? scan.revenue_growth * 100 : null;
  const earnGrowthPct = scan.earnings_growth != null ? scan.earnings_growth * 100 : null;

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800/70 p-4 space-y-3 hover:border-slate-600 transition-colors">
      {/* ── Header ── */}
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
          <p className="text-base font-semibold text-white">${parseFloat(scan.price).toFixed(2)}</p>
          <p className="text-xs text-slate-500">{scan.scan_date}</p>
        </div>
      </div>

      {/* ── T2 Score bar ── */}
      <div>
        <div className="flex justify-between items-center mb-1">
          <span className="text-xs text-slate-500">T2 Score</span>
        </div>
        <ScoreBar score={scan.t2_score} />
      </div>

      {/* ── Key metrics grid ── */}
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="bg-slate-900/60 rounded-lg p-2">
          <p className="text-slate-500 mb-0.5">RVOL</p>
          <p className="font-semibold text-white">{scan.rvol.toFixed(1)}x</p>
        </div>
        <div className="bg-slate-900/60 rounded-lg p-2">
          <p className="text-slate-500 mb-0.5">Mkt Cap</p>
          <p className="font-semibold text-white">{fmtCap(scan.market_cap)}</p>
        </div>
        <div className="bg-slate-900/60 rounded-lg p-2">
          <p className="text-slate-500 mb-0.5">Avg Vol</p>
          <p className="font-semibold text-white">{fmtVol(scan.avg_volume_30d)}</p>
        </div>
        <div className="bg-slate-900/60 rounded-lg p-2">
          <p className="text-slate-500 mb-0.5">52W Hi</p>
          <p className={cn("font-semibold", (scan.pct_below_52w_high ?? 1) < 0.05 ? "text-emerald-400" : "text-white")}>
            {scan.pct_below_52w_high != null ? `${(scan.pct_below_52w_high * 100).toFixed(1)}% off` : "—"}
          </p>
        </div>
        <div className="bg-slate-900/60 rounded-lg p-2">
          <p className="text-slate-500 mb-0.5">Rev Gr</p>
          <p className={cn("font-semibold", revGrowthPct != null && revGrowthPct > 0 ? "text-emerald-400" : revGrowthPct != null && revGrowthPct < 0 ? "text-red-400" : "text-slate-400")}>
            {revGrowthPct != null ? `${revGrowthPct > 0 ? "+" : ""}${revGrowthPct.toFixed(0)}%` : "—"}
          </p>
        </div>
        <div className="bg-slate-900/60 rounded-lg p-2">
          <p className="text-slate-500 mb-0.5">Earn Gr</p>
          <p className={cn("font-semibold", earnGrowthPct != null && earnGrowthPct > 0 ? "text-emerald-400" : earnGrowthPct != null && earnGrowthPct < 0 ? "text-red-400" : "text-slate-400")}>
            {earnGrowthPct != null ? `${earnGrowthPct > 0 ? "+" : ""}${earnGrowthPct.toFixed(0)}%` : "—"}
          </p>
        </div>
      </div>

      {/* ── Signal summary ── */}
      {scan.signal_summary && (
        <p className="text-xs text-slate-400 leading-relaxed">{scan.signal_summary}</p>
      )}

      {/* ── Risk flags ── */}
      {scan.risk_flags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {scan.risk_flags.map((f) => <RiskFlag key={f} flag={f} />)}
        </div>
      )}

      {/* ── News verdict ── */}
      <NewsBlock summary={scan.news_summary} verdict={scan.news_verdict as NewsVerdict | null} />
    </div>
  );
}
