"use client";

import { AlertTriangle, BrainCircuit, RefreshCw } from "lucide-react";
import type { FinancialSummary, QuarterlyResult } from "@/lib/types";
import { cn } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined, decimals = 2): string {
  if (n == null) return "—";
  return n.toLocaleString("en-US", { maximumFractionDigits: decimals, minimumFractionDigits: decimals });
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  const sign = n >= 0 ? "+" : "";
  return `${sign}${(n * 100).toFixed(1)}%`;
}

function fmtLarge(n: number | null | undefined): string {
  if (n == null) return "—";
  if (Math.abs(n) >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (Math.abs(n) >= 1e9)  return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6)  return `$${(n / 1e6).toFixed(1)}M`;
  return `$${n.toFixed(0)}`;
}

// ── Readiness badge ───────────────────────────────────────────────────────────

function ReadinessBadge({ readiness }: { readiness: string }) {
  const map = {
    GO:      { bg: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40", label: "GO" },
    CAUTION: { bg: "bg-yellow-500/20  text-yellow-400  border-yellow-500/40",  label: "CAUTION" },
    AVOID:   { bg: "bg-red-500/20     text-red-400     border-red-500/40",     label: "AVOID" },
  } as const;
  const cfg = map[readiness as keyof typeof map] ?? map.CAUTION;
  return (
    <span className={cn("px-2 py-0.5 rounded-full text-xs font-bold border", cfg.bg)}>
      {cfg.label}
    </span>
  );
}

// ── Quarterly mini bar chart ──────────────────────────────────────────────────

function RevenueBar({ quarters }: { quarters: QuarterlyResult[] }) {
  if (!quarters.length) return null;

  const revs = quarters.map(q => q.revenue ?? 0);
  const max = Math.max(...revs, 1);

  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Revenue (quarterly)</p>
      <div className="flex items-end gap-1.5 h-14">
        {[...quarters].reverse().map((q, i) => {
          const pct = max > 0 ? ((q.revenue ?? 0) / max) * 100 : 0;
          const isLatest = i === quarters.length - 1;
          return (
            <div key={q.period} className="flex-1 flex flex-col items-center gap-0.5">
              <div
                className={cn(
                  "w-full rounded-t transition-all",
                  isLatest ? "bg-blue-500" : "bg-slate-600",
                )}
                style={{ height: `${Math.max(pct, 4)}%` }}
                title={fmtLarge(q.revenue)}
              />
              <span className="text-[9px] text-slate-500 truncate w-full text-center">
                {q.period.slice(0, 7)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main card ─────────────────────────────────────────────────────────────────

interface FinancialCardProps {
  data: FinancialSummary;
  onRemove?: () => void;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}

export function FinancialCard({ data, onRemove, onRefresh, isRefreshing }: FinancialCardProps) {
  const {
    symbol, name, sector, price,
    market_cap, pe_ratio, forward_pe,
    revenue_growth_yoy, net_margin,
    debt_to_equity, analyst_recommendation, analyst_target_price,
    next_earnings, quarterly_results,
    trade_readiness, risk_flags, claude_view,
  } = data;

  const earningsUrgent  = next_earnings?.days_until != null && next_earnings.days_until <= 7;
  const earningsComing  = next_earnings?.days_until != null && next_earnings.days_until <= 14;
  const revGrowthPos    = revenue_growth_yoy != null && revenue_growth_yoy > 0;

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden flex flex-col">

      {/* ── Earnings banner (only when ≤14 days) ────────────────────────────── */}
      {earningsComing && next_earnings?.date_str && (
        <div className={cn(
          "flex items-center gap-2 px-4 py-2 text-xs font-medium",
          earningsUrgent
            ? "bg-red-900/60 text-red-300 border-b border-red-700"
            : "bg-yellow-900/40 text-yellow-300 border-b border-yellow-700/50",
        )}>
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span>
            {earningsUrgent ? "⚠️ EARNINGS IN " : "Earnings in "}
            <strong>{next_earnings.days_until} day{next_earnings.days_until === 1 ? "" : "s"}</strong>
            {" — "}{next_earnings.date_str}
            {earningsUrgent && " — HIGH GAP RISK"}
          </span>
        </div>
      )}

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="px-4 pt-4 pb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-bold text-white text-lg leading-none">{symbol}</span>
            <ReadinessBadge readiness={trade_readiness} />
          </div>
          <p className="text-slate-400 text-sm mt-0.5 truncate">{name}</p>
          <p className="text-slate-500 text-xs">{sector}</p>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          <p className="text-white font-bold text-lg">${fmt(price)}</p>
          {analyst_target_price && (
            <p className="text-slate-400 text-xs">
              Target:{" "}
              <span className={analyst_target_price > price ? "text-emerald-400" : "text-red-400"}>
                ${fmt(analyst_target_price)}
              </span>
            </p>
          )}
          {/* Refresh + Remove buttons */}
          <div className="flex items-center gap-1 mt-0.5">
            {onRefresh && (
              <button
                onClick={onRefresh}
                disabled={isRefreshing}
                title="Refresh data"
                className="p-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-slate-700
                           disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", isRefreshing && "animate-spin")} />
              </button>
            )}
            {onRemove && (
              <button
                onClick={onRemove}
                title="Remove"
                className="p-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-slate-700 transition-colors"
              >
                <span className="text-xs leading-none">✕</span>
              </button>
            )}
          </div>
          {/* Fetched-at timestamp */}
          {fetched_at && (
            <p className="text-[10px] text-slate-600" title={fetched_at}>
              {isRefreshing ? "Refreshing…" : `as of ${new Date(fetched_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`}
            </p>
          )}
        </div>
      </div>

      {/* ── Metrics grid ─────────────────────────────────────────────────────── */}
      <div className="px-4 pb-3 grid grid-cols-2 sm:grid-cols-3 gap-2">
        {[
          { label: "Market Cap",   value: fmtLarge(market_cap) },
          { label: "P/E (TTM)",    value: pe_ratio != null ? `${fmt(pe_ratio, 1)}×` : "—" },
          { label: "Fwd P/E",      value: forward_pe != null ? `${fmt(forward_pe, 1)}×` : "—" },
          {
            label: "Rev Growth YoY",
            value: fmtPct(revenue_growth_yoy),
            color: revenue_growth_yoy != null
              ? (revGrowthPos ? "text-emerald-400" : "text-red-400")
              : "text-slate-400",
          },
          {
            label: "Net Margin",
            value: fmtPct(net_margin),
            color: net_margin != null
              ? (net_margin > 0 ? "text-emerald-400" : "text-red-400")
              : "text-slate-400",
          },
          { label: "Debt/Equity", value: debt_to_equity != null ? `${fmt(debt_to_equity, 2)}×` : "—" },
          {
            label: "Analyst",
            value: analyst_recommendation
              ? analyst_recommendation.toUpperCase()
              : "—",
            color: analyst_recommendation
              ? ({ buy: "text-emerald-400", hold: "text-yellow-400", sell: "text-red-400" }[analyst_recommendation.toLowerCase()] ?? "text-slate-300")
              : "text-slate-400",
          },
          {
            label: "Next Earnings",
            value: next_earnings?.date_str
              ? `${next_earnings.date_str} (${next_earnings.days_until}d)`
              : "—",
            color: earningsUrgent ? "text-red-400" : earningsComing ? "text-yellow-400" : "text-slate-300",
          },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-slate-700/50 rounded-lg px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-0.5">{label}</p>
            <p className={cn("text-sm font-semibold", color ?? "text-slate-200")}>{value}</p>
          </div>
        ))}
      </div>

      {/* ── Revenue bars ─────────────────────────────────────────────────────── */}
      {quarterly_results.length > 0 && (
        <div className="px-4 pb-3">
          <RevenueBar quarters={quarterly_results} />
        </div>
      )}

      {/* ── Risk flags ───────────────────────────────────────────────────────── */}
      {risk_flags.length > 0 && (
        <div className="px-4 pb-3">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Risk Flags</p>
          <ul className="space-y-1">
            {risk_flags.map((flag, i) => (
              <li key={i} className="text-xs text-slate-300 flex items-start gap-1.5">
                <span className="shrink-0 mt-0.5">{flag.slice(0, 2)}</span>
                <span>{flag.slice(2).trim()}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Claude view ──────────────────────────────────────────────────────── */}
      <div className="mx-4 mb-4 mt-auto rounded-lg bg-slate-700/40 border border-slate-600/50 px-3 py-2.5">
        <div className="flex items-center gap-1.5 mb-1">
          <BrainCircuit className="h-3.5 w-3.5 text-violet-400" />
          <span className="text-[10px] uppercase tracking-wider text-violet-400 font-medium">Claude View</span>
        </div>
        <p className="text-slate-300 text-xs leading-relaxed">{claude_view}</p>
      </div>

    </div>
  );
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

export function FinancialCardSkeleton() {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 animate-pulse">
      <div className="flex justify-between mb-3">
        <div className="space-y-1.5">
          <div className="h-5 w-20 bg-slate-700 rounded" />
          <div className="h-3.5 w-32 bg-slate-700 rounded" />
        </div>
        <div className="h-6 w-16 bg-slate-700 rounded" />
      </div>
      <div className="grid grid-cols-3 gap-2 mb-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-12 bg-slate-700 rounded-lg" />
        ))}
      </div>
      <div className="h-16 bg-slate-700 rounded-lg mb-3" />
      <div className="h-14 bg-slate-700 rounded-lg" />
    </div>
  );
}
