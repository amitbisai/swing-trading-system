"use client";

import { cn } from "@/lib/utils";
import type { T1Scan } from "@/lib/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtPrice(raw: string | number | null | undefined): string {
  if (raw == null) return "—";
  const v = typeof raw === "string" ? parseFloat(raw) : raw;
  if (isNaN(v)) return "—";
  return `$${v.toFixed(2)}`;
}

function fmtPctDiff(price: string, ref: string | null): string {
  if (!ref) return "—";
  const p = parseFloat(price);
  const r = parseFloat(ref);
  if (isNaN(p) || isNaN(r) || r === 0) return "—";
  const pct = ((p - r) / r) * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

function pctDiffSign(price: string, ref: string | null): "pos" | "neg" | "neutral" {
  if (!ref) return "neutral";
  const p = parseFloat(price);
  const r = parseFloat(ref);
  if (isNaN(p) || isNaN(r) || r === 0) return "neutral";
  return p >= r ? "pos" : "neg";
}

function fmtAtrPct(atr: number | null, price: string): string {
  if (atr == null) return "—";
  const p = parseFloat(price);
  if (isNaN(p) || p === 0) return "—";
  return `${((atr / p) * 100).toFixed(1)}%`;
}

function fmtVol(raw: string | null): string {
  if (!raw) return "—";
  const v = parseFloat(raw);
  if (isNaN(v)) return "—";
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  return `${(v / 1e3).toFixed(0)}K`;
}

// ── Score pill ────────────────────────────────────────────────────────────────

function ScorePill({ label, score }: { label: string; score: number }) {
  const color =
    score >= 70 ? "bg-emerald-900/40 text-emerald-300 border-emerald-700/50"
    : score >= 50 ? "bg-amber-900/40 text-amber-300 border-amber-700/50"
    : "bg-red-900/40 text-red-300 border-red-700/50";
  return (
    <span className={cn("px-2 py-0.5 rounded text-xs font-semibold border", color)}>
      {label} {score}
    </span>
  );
}

// ── RSI gauge ─────────────────────────────────────────────────────────────────

function RsiBar({ rsi }: { rsi: number | null }) {
  if (rsi == null) return null;
  const pct = Math.min(100, Math.max(0, rsi));
  const color =
    rsi > 70 ? "bg-red-500"
    : rsi < 30 ? "bg-emerald-500"
    : rsi < 50 ? "bg-amber-500"
    : "bg-slate-400";
  const label =
    rsi > 70 ? "Overbought"
    : rsi < 30 ? "Oversold"
    : rsi < 50 ? "Weak"
    : "Neutral";
  return (
    <div className="space-y-1">
      <div className="flex justify-between items-center text-xs">
        <span className="text-slate-500">RSI 14</span>
        <span className={cn("font-semibold tabular-nums", color.replace("bg-", "text-"))}>
          {rsi.toFixed(1)} <span className="font-normal text-slate-500">({label})</span>
        </span>
      </div>
      <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", color)}
          style={{ width: `${pct}%` }}
        />
      </div>
      {/* zone markers */}
      <div className="flex justify-between text-[10px] text-slate-600 px-0.5">
        <span>0</span>
        <span className="text-emerald-700">30</span>
        <span className="text-amber-700">50</span>
        <span className="text-red-700">70</span>
        <span>100</span>
      </div>
    </div>
  );
}

// ── Pattern pill ──────────────────────────────────────────────────────────────

const PATTERN_COLOR: Record<string, string> = {
  HAMMER:            "bg-emerald-900/40 text-emerald-300 border-emerald-700/40",
  BULLISH_ENGULFING: "bg-emerald-900/40 text-emerald-300 border-emerald-700/40",
  UPTREND:           "bg-emerald-900/40 text-emerald-300 border-emerald-700/40",
  SHOOTING_STAR:     "bg-red-900/40 text-red-300 border-red-700/40",
  DOWNTREND:         "bg-red-900/40 text-red-300 border-red-700/40",
  VOLUME_BREAKOUT:   "bg-blue-900/40 text-blue-300 border-blue-700/40",
  DOJI:              "bg-slate-700 text-slate-400 border-slate-600",
};

function PatternPill({ pattern }: { pattern: string }) {
  const cls = PATTERN_COLOR[pattern] ?? "bg-slate-700 text-slate-400 border-slate-600";
  return (
    <span className={cn("px-1.5 py-0.5 rounded text-xs border", cls)}>
      {pattern.replace(/_/g, " ")}
    </span>
  );
}

// ── Metric cell ───────────────────────────────────────────────────────────────

function MetricCell({
  label,
  value,
  sentiment,
}: {
  label: string;
  value: string;
  sentiment?: "pos" | "neg" | "neutral";
}) {
  const valueColor =
    sentiment === "pos" ? "text-emerald-400"
    : sentiment === "neg" ? "text-red-400"
    : "text-white";
  return (
    <div className="bg-slate-900/60 rounded-lg p-2 text-xs">
      <p className="text-slate-500 mb-0.5">{label}</p>
      <p className={cn("font-semibold", valueColor)}>{value}</p>
    </div>
  );
}

// ── Main card ─────────────────────────────────────────────────────────────────

export function T1ScanCard({ scan }: { scan: T1Scan }) {
  const macdUp = scan.macd_hist != null && scan.macd_hist > 0;
  const rvolHigh = scan.rvol != null && scan.rvol >= 1.5;
  const vsSma20Sign = pctDiffSign(scan.price, scan.sma_20);
  const vsSma50Sign = pctDiffSign(scan.price, scan.sma_50);

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800/70 p-4 space-y-3 hover:border-slate-600 transition-colors">
      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-base font-bold text-white">{scan.symbol}</span>
            {/* direction badge */}
            <span
              className={cn(
                "px-2 py-0.5 rounded text-xs font-bold border",
                scan.signal_direction === "LONG"
                  ? "bg-emerald-900/40 text-emerald-300 border-emerald-700/50"
                  : "bg-red-900/40 text-red-300 border-red-700/50",
              )}
            >
              {scan.signal_direction}
            </span>
            {/* AI signal badge */}
            {scan.made_signal && (
              <span className="px-2 py-0.5 rounded text-xs font-bold border bg-blue-900/40 text-blue-300 border-blue-700/50">
                AI Signal
              </span>
            )}
          </div>
          {scan.sector && (
            <p className="text-xs text-slate-500 mt-0.5 truncate">{scan.sector}</p>
          )}
        </div>
        <div className="text-right flex-shrink-0">
          <p className="text-base font-semibold text-white">{fmtPrice(scan.price)}</p>
          <p className="text-xs text-slate-500">{scan.scan_date}</p>
        </div>
      </div>

      {/* ── RSI gauge ── */}
      <RsiBar rsi={scan.rsi_14} />

      {/* ── MACD row ── */}
      {scan.macd_hist != null && (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">MACD</span>
          <span className={cn("font-semibold", macdUp ? "text-emerald-400" : "text-red-400")}>
            {macdUp ? "▲" : "▼"}
          </span>
          <span className={cn("tabular-nums font-medium", macdUp ? "text-emerald-400" : "text-red-400")}>
            {scan.macd_hist.toFixed(4)}
          </span>
          <span className="text-slate-600 text-[10px]">hist</span>
        </div>
      )}

      {/* ── 2×3 metrics grid ── */}
      <div className="grid grid-cols-3 gap-2">
        <MetricCell
          label="vs SMA20"
          value={fmtPctDiff(scan.price, scan.sma_20)}
          sentiment={vsSma20Sign}
        />
        <MetricCell
          label="vs SMA50"
          value={fmtPctDiff(scan.price, scan.sma_50)}
          sentiment={vsSma50Sign}
        />
        <MetricCell
          label="RVOL"
          value={scan.rvol != null ? `${scan.rvol.toFixed(1)}x` : "—"}
          sentiment={rvolHigh ? "pos" : "neutral"}
        />
        <MetricCell
          label="ATR%"
          value={fmtAtrPct(scan.atr_14, scan.price)}
          sentiment="neutral"
        />
        <MetricCell
          label="Support"
          value={fmtPrice(scan.support_level)}
          sentiment="neutral"
        />
        <MetricCell
          label="Resistance"
          value={fmtPrice(scan.resistance_level)}
          sentiment="neutral"
        />
      </div>

      {/* ── Score pills ── */}
      <div className="flex flex-wrap gap-1.5">
        <ScorePill label="TA"   score={scan.ta_score} />
        <ScorePill label="Pat"  score={scan.pattern_score} />
        <ScorePill label="Sent" score={scan.sentiment_score} />
        <span className="ml-auto flex items-center gap-1">
          <span className="text-xs text-slate-500">Bull</span>
          <span className="text-xs font-semibold text-emerald-400">{scan.bullish_confidence}</span>
          <span className="text-xs text-slate-600">/</span>
          <span className="text-xs text-slate-500">Bear</span>
          <span className="text-xs font-semibold text-red-400">{scan.bearish_confidence}</span>
        </span>
      </div>

      {/* ── Pattern pills ── */}
      {scan.patterns_detected.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {scan.patterns_detected.map((p) => (
            <PatternPill key={p} pattern={p} />
          ))}
        </div>
      )}
    </div>
  );
}
