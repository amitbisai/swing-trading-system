"use client";

import { useState } from "react";
import { cn, formatCurrency } from "@/lib/utils";
import { TrendingUp, TrendingDown, Clock, X, Check, Loader2, ArrowRight } from "lucide-react";
import type { PaperTrade } from "@/lib/types";
import { closeTrade } from "@/lib/api";

// ── Position bar (stop → entry → target) ──────────────────────────────────────

function PositionBar({
  stop, entry, target, currentPrice,
}: {
  stop: number; entry: number; target: number; currentPrice?: number;
}) {
  const low   = Math.min(stop, target);
  const high  = Math.max(stop, target);
  const range = high - low;
  if (range <= 0) return null;

  const entryPct   = Math.max(0, Math.min(100, ((entry - low) / range) * 100));
  const currentPct = currentPrice != null
    ? Math.max(0, Math.min(100, ((currentPrice - low) / range) * 100))
    : null;

  return (
    <div className="relative h-2 rounded-full bg-slate-700 overflow-hidden">
      <div className="absolute left-0 top-0 h-full bg-red-800"    style={{ width: `${entryPct}%` }} />
      <div className="absolute top-0 h-full bg-emerald-800"        style={{ left: `${entryPct}%`, right: "0%" }} />
      {/* Entry marker */}
      <div className="absolute top-0 h-full w-0.5 bg-white opacity-70" style={{ left: `${entryPct}%` }} />
      {/* Current price marker */}
      {currentPct != null && (
        <div
          className="absolute top-0 h-full w-1 rounded-sm bg-yellow-400"
          style={{ left: `${currentPct}%`, transform: "translateX(-50%)" }}
        />
      )}
    </div>
  );
}

// ── Open position card ────────────────────────────────────────────────────────

interface PositionCardProps {
  trade: PaperTrade;
  currentPrice?: number;
  onClosed: () => void;
}

export function PositionCard({ trade: t, currentPrice, onClosed }: PositionCardProps) {
  const isLong  = t.direction === "LONG";
  const entry   = parseFloat(t.entry_price);
  const stop    = parseFloat(t.stop_loss);
  const target  = parseFloat(t.target_price);
  const stopPct = Math.abs(((entry - stop)   / entry) * 100);
  const tgtPct  = Math.abs(((target - entry) / entry) * 100);

  // Unrealized P&L from current price
  const unrealizedPnl = currentPrice != null
    ? (isLong ? (currentPrice - entry) : (entry - currentPrice)) * t.shares
    : null;
  const unrealizedPct = currentPrice != null
    ? ((currentPrice - entry) / entry) * 100 * (isLong ? 1 : -1)
    : null;
  const isGain = unrealizedPnl !== null && unrealizedPnl >= 0;

  // Close form state
  const [showClose,  setShowClose]  = useState(false);
  const [exitPrice,  setExitPrice]  = useState(
    currentPrice != null ? currentPrice.toFixed(2) : entry.toFixed(2)
  );
  const [submitting, setSubmitting] = useState(false);
  const [error,      setError]      = useState<string | null>(null);

  async function handleClose() {
    const price = parseFloat(exitPrice);
    if (isNaN(price) || price <= 0) { setError("Enter a valid price."); return; }
    setSubmitting(true);
    setError(null);
    try {
      await closeTrade(t.id, price);
      onClosed();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to close trade.");
      setSubmitting(false);
    }
  }

  const closeLabel   = isLong ? "Sell / Close" : "Buy / Close";
  const confirmLabel = isLong
    ? `Sell ${t.shares} share${t.shares !== 1 ? "s" : ""}`
    : `Buy back ${t.shares} share${t.shares !== 1 ? "s" : ""}`;

  // Preview P&L for the close form
  const previewEp = parseFloat(exitPrice);
  const previewPnl = !isNaN(previewEp) && previewEp > 0
    ? (isLong ? previewEp - entry : entry - previewEp) * t.shares
    : null;

  return (
    <article className="rounded-xl border border-slate-700 bg-slate-800 p-4 space-y-3">

      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-lg font-bold text-white truncate">{t.symbol}</span>
          <span className={cn(
            "flex items-center gap-0.5 text-xs font-semibold px-2 py-0.5 rounded-full shrink-0",
            isLong ? "bg-emerald-900/60 text-emerald-400" : "bg-red-900/60 text-red-400",
          )}>
            {isLong ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
            {t.direction}
          </span>
        </div>
        <div className="text-right shrink-0">
          <p className="text-xs text-slate-500">Shares</p>
          <p className="text-sm font-mono text-white">{t.shares}</p>
        </div>
      </div>

      {/* ── Current price + unrealized P&L ── */}
      <div className="flex items-center justify-between rounded-lg bg-slate-900/80 px-3 py-2">
        <div>
          <p className="text-[10px] text-slate-500 mb-0.5">Last Price</p>
          <p className="font-mono text-base font-semibold text-white">
            {currentPrice != null ? `$${currentPrice.toFixed(2)}` : "—"}
          </p>
        </div>
        {unrealizedPnl != null && (
          <div className="text-right">
            <p className="text-[10px] text-slate-500 mb-0.5">Unrealized P&amp;L</p>
            <p className={cn("font-mono text-base font-semibold", isGain ? "text-emerald-400" : "text-red-400")}>
              {isGain ? "+" : ""}{formatCurrency(unrealizedPnl.toFixed(2))}
            </p>
            {unrealizedPct != null && (
              <p className={cn("text-[10px] font-mono", isGain ? "text-emerald-500" : "text-red-500")}>
                {unrealizedPct >= 0 ? "+" : ""}{unrealizedPct.toFixed(2)}%
              </p>
            )}
          </div>
        )}
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

      {/* ── R:R progress bar with current price marker ── */}
      <div className="space-y-1.5">
        <PositionBar stop={stop} entry={entry} target={target} currentPrice={currentPrice} />
        <div className="flex justify-between text-[10px] text-slate-500 font-mono">
          <span>{isLong ? "-" : "+"}{stopPct.toFixed(1)}%</span>
          <span className="text-slate-400">Entry{currentPrice != null ? " · " : ""}<span className="text-yellow-400">{currentPrice != null ? "Now" : ""}</span></span>
          <span>{isLong ? "+" : "-"}{tgtPct.toFixed(1)}%</span>
        </div>
      </div>

      {/* ── Footer ── */}
      <div className="flex items-center justify-between text-xs text-slate-500">
        <div className="flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5" />
          <span>Since {t.entry_date}</span>
        </div>
        <span className="font-mono text-[10px]">Cap: {formatCurrency(t.capital_at_risk)}</span>
      </div>

      {/* ── Close trade ── */}
      {!showClose ? (
        <button
          onClick={() => {
            setShowClose(true);
            setExitPrice(currentPrice != null ? currentPrice.toFixed(2) : entry.toFixed(2));
            setError(null);
          }}
          className={cn(
            "w-full py-2 rounded-lg text-xs font-semibold border transition-colors",
            isLong
              ? "border-red-700/60 text-red-400 hover:bg-red-900/30"
              : "border-emerald-700/60 text-emerald-400 hover:bg-emerald-900/30",
          )}
        >
          {closeLabel}
        </button>
      ) : (
        <div className="space-y-2 pt-1 border-t border-slate-700">
          <p className="text-xs text-slate-400">
            {isLong
              ? `Selling ${t.shares} share${t.shares !== 1 ? "s" : ""} of ${t.symbol}`
              : `Buying back ${t.shares} share${t.shares !== 1 ? "s" : ""} of ${t.symbol}`}
          </p>

          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 shrink-0">Exit price $</span>
            <input
              type="number" step="0.01" min="0.01"
              value={exitPrice}
              onChange={(e) => setExitPrice(e.target.value)}
              className="flex-1 bg-slate-900 border border-slate-600 rounded-lg px-3 py-1.5
                         text-sm font-mono text-white focus:outline-none focus:border-slate-400
                         [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none
                         [&::-webkit-inner-spin-button]:appearance-none"
              disabled={submitting}
            />
          </div>

          {previewPnl != null && (
            <p className={cn("text-xs font-mono text-right", previewPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
              Est. P&amp;L: {previewPnl >= 0 ? "+" : ""}{formatCurrency(previewPnl.toFixed(2))}
            </p>
          )}

          {error && <p className="text-xs text-red-400">{error}</p>}

          <div className="flex gap-2">
            <button
              onClick={() => { setShowClose(false); setError(null); }}
              disabled={submitting}
              className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg
                         text-xs font-medium border border-slate-600 text-slate-400
                         hover:border-slate-500 hover:text-slate-300 transition-colors disabled:opacity-50"
            >
              <X className="h-3.5 w-3.5" /> Cancel
            </button>
            <button
              onClick={handleClose}
              disabled={submitting}
              className={cn(
                "flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg",
                "text-xs font-semibold transition-colors disabled:opacity-60",
                isLong ? "bg-red-700 hover:bg-red-600 text-white" : "bg-emerald-700 hover:bg-emerald-600 text-white",
              )}
            >
              {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              {submitting ? "Closing…" : confirmLabel}
            </button>
          </div>
        </div>
      )}
    </article>
  );
}

// ── Closed position card ──────────────────────────────────────────────────────

interface ClosedPositionCardProps {
  trade: PaperTrade;
}

export function ClosedPositionCard({ trade: t }: ClosedPositionCardProps) {
  const isLong   = t.direction === "LONG";
  const pnl      = t.realized_pnl ? parseFloat(t.realized_pnl) : 0;
  const isProfit = pnl >= 0;

  const entryVal  = parseFloat(t.entry_price);
  const exitVal   = t.exit_price ? parseFloat(t.exit_price) : null;
  const pnlPct    = exitVal != null && entryVal > 0
    ? ((exitVal - entryVal) / entryVal) * 100 * (isLong ? 1 : -1)
    : null;

  const exitReasonLabel: Record<string, string> = {
    STOP_HIT:     "Stop hit",
    TARGET_HIT:   "Target hit",
    TIME_EXIT:    "Time exit",
    MANUAL_CLOSE: "Closed manually",
  };

  return (
    <article className={cn(
      "rounded-xl border p-4 space-y-2.5",
      isProfit
        ? "border-emerald-900/50 bg-emerald-950/20"
        : "border-red-900/40 bg-red-950/10",
    )}>
      {/* ── Header row ── */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0 flex-wrap">
          <span className="text-base font-bold text-white truncate">{t.symbol}</span>
          <span className={cn(
            "text-[10px] font-semibold px-1.5 py-0.5 rounded-full shrink-0",
            isLong ? "bg-emerald-900/40 text-emerald-500" : "bg-red-900/40 text-red-500",
          )}>
            {t.direction}
          </span>
          {t.exit_reason && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-700/80 text-slate-400">
              {exitReasonLabel[t.exit_reason] ?? t.exit_reason.replace(/_/g, " ")}
            </span>
          )}
        </div>

        {/* P&L — prominent */}
        <div className="text-right shrink-0">
          <p className={cn("text-base font-mono font-bold", isProfit ? "text-emerald-400" : "text-red-400")}>
            {isProfit ? "+" : ""}{formatCurrency(t.realized_pnl ?? "0")}
          </p>
          {pnlPct != null && (
            <p className={cn("text-xs font-mono", isProfit ? "text-emerald-500" : "text-red-500")}>
              {pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%
            </p>
          )}
        </div>
      </div>

      {/* ── Entry → Exit price row ── */}
      <div className="flex items-center gap-2 text-sm font-mono">
        <span className="text-slate-400">${entryVal.toFixed(2)}</span>
        <ArrowRight className="h-3.5 w-3.5 text-slate-600 shrink-0" />
        <span className={cn("font-semibold", isProfit ? "text-emerald-400" : "text-red-400")}>
          {exitVal != null ? `$${exitVal.toFixed(2)}` : "—"}
        </span>
        <span className="text-slate-600 text-xs ml-auto font-sans">
          ×{t.shares} share{t.shares !== 1 ? "s" : ""}
        </span>
      </div>

      {/* ── Date row ── */}
      <div className="flex justify-between text-[11px] text-slate-500">
        <span>{t.entry_date} → {t.exit_date ?? "—"}</span>
        <span>Cap: {formatCurrency(t.capital_at_risk)}</span>
      </div>
    </article>
  );
}
