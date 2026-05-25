"use client";

import { useState } from "react";
import { cn, formatCurrency } from "@/lib/utils";
import { TrendingUp, TrendingDown, Clock, X, Check, Loader2 } from "lucide-react";
import type { PaperTrade } from "@/lib/types";
import { closeTrade } from "@/lib/api";

// ── Position bar (stop → entry → target) ──────────────────────────────────────

function PositionBar({
  stop,
  entry,
  target,
}: {
  stop: number;
  entry: number;
  target: number;
}) {
  // For both LONG and SHORT the bar always goes low→high left→right
  const low    = Math.min(stop, target);
  const high   = Math.max(stop, target);
  const range  = high - low;
  if (range <= 0) return null;

  const entryPct = ((entry - low) / range) * 100;

  return (
    <div className="relative h-2 rounded-full bg-slate-700 overflow-hidden">
      <div className="absolute left-0 top-0 h-full bg-red-800"   style={{ width: `${entryPct}%` }} />
      <div className="absolute top-0 h-full bg-emerald-800"       style={{ left: `${entryPct}%`, right: "0%" }} />
      <div className="absolute top-0 h-full w-0.5 bg-white"       style={{ left: `${entryPct}%` }} />
    </div>
  );
}

// ── Open position card ────────────────────────────────────────────────────────

interface PositionCardProps {
  trade: PaperTrade;
  onClosed: () => void;   // called after a successful close to refresh the list
}

export function PositionCard({ trade: t, onClosed }: PositionCardProps) {
  const isLong  = t.direction === "LONG";
  const entry   = parseFloat(t.entry_price);
  const stop    = parseFloat(t.stop_loss);
  const target  = parseFloat(t.target_price);
  const stopPct = Math.abs(((entry - stop)   / entry) * 100);
  const tgtPct  = Math.abs(((target - entry) / entry) * 100);

  // ── Close-trade inline form state ─────────────────────────────────────────
  const [showClose,  setShowClose]  = useState(false);
  const [exitPrice,  setExitPrice]  = useState(entry.toFixed(2));
  const [submitting, setSubmitting] = useState(false);
  const [error,      setError]      = useState<string | null>(null);

  async function handleClose() {
    const price = parseFloat(exitPrice);
    if (isNaN(price) || price <= 0) {
      setError("Enter a valid price.");
      return;
    }
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

  // Button label reflects what the user is actually doing
  const closeLabel = isLong ? "Sell / Close" : "Buy / Close";
  const confirmLabel = isLong
    ? `Sell ${t.shares} share${t.shares !== 1 ? "s" : ""}`
    : `Buy back ${t.shares} share${t.shares !== 1 ? "s" : ""}`;

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

      {/* ── R:R progress bar ── */}
      <div className="space-y-1.5">
        <PositionBar stop={stop} entry={entry} target={target} />
        <div className="flex justify-between text-[10px] text-slate-500 font-mono">
          <span>{isLong ? "-" : "+"}{stopPct.toFixed(1)}%</span>
          <span className="text-slate-400">Entry</span>
          <span>{isLong ? "+" : "-"}{tgtPct.toFixed(1)}%</span>
        </div>
      </div>

      {/* ── Footer row ── */}
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-1.5 text-slate-400">
          <Clock className="h-3.5 w-3.5" />
          <span>Since {t.entry_date}</span>
        </div>
        <span className="font-mono text-slate-500 text-[10px]">
          Cap at risk: {formatCurrency(t.capital_at_risk)}
        </span>
      </div>

      {/* ── Close trade section ── */}
      {!showClose ? (
        <button
          onClick={() => { setShowClose(true); setExitPrice(entry.toFixed(2)); setError(null); }}
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
              : `Buying back ${t.shares} share${t.shares !== 1 ? "s" : ""} of ${t.symbol}`
            }
          </p>

          {/* Exit price input */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 shrink-0">Exit price $</span>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={exitPrice}
              onChange={(e) => setExitPrice(e.target.value)}
              className="flex-1 bg-slate-900 border border-slate-600 rounded-lg px-3 py-1.5
                         text-sm font-mono text-white focus:outline-none focus:border-slate-400
                         [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none
                         [&::-webkit-inner-spin-button]:appearance-none"
              disabled={submitting}
            />
          </div>

          {/* Estimated P&L preview */}
          {(() => {
            const ep = parseFloat(exitPrice);
            if (!isNaN(ep) && ep > 0) {
              const pnl = isLong
                ? (ep - entry) * t.shares
                : (entry - ep) * t.shares;
              const isGain = pnl >= 0;
              return (
                <p className={cn("text-xs font-mono text-right", isGain ? "text-emerald-400" : "text-red-400")}>
                  Est. P&L: {isGain ? "+" : ""}{formatCurrency(pnl.toFixed(2))}
                </p>
              );
            }
            return null;
          })()}

          {error && <p className="text-xs text-red-400">{error}</p>}

          {/* Confirm / Cancel */}
          <div className="flex gap-2">
            <button
              onClick={() => { setShowClose(false); setError(null); }}
              disabled={submitting}
              className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg
                         text-xs font-medium border border-slate-600 text-slate-400
                         hover:border-slate-500 hover:text-slate-300 transition-colors disabled:opacity-50"
            >
              <X className="h-3.5 w-3.5" />
              Cancel
            </button>
            <button
              onClick={handleClose}
              disabled={submitting}
              className={cn(
                "flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg",
                "text-xs font-semibold transition-colors disabled:opacity-60",
                isLong
                  ? "bg-red-700 hover:bg-red-600 text-white"
                  : "bg-emerald-700 hover:bg-emerald-600 text-white",
              )}
            >
              {submitting
                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                : <Check className="h-3.5 w-3.5" />
              }
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
  const isLong  = t.direction === "LONG";
  const pnl     = t.realized_pnl ? parseFloat(t.realized_pnl) : 0;
  const isProfit = pnl >= 0;

  const exitReasonLabel: Record<string, string> = {
    STOP_HIT:     "Stop hit",
    TARGET_HIT:   "Target hit",
    MANUAL_CLOSE: "Closed manually",
  };

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
              {exitReasonLabel[t.exit_reason] ?? t.exit_reason.replace(/_/g, " ")}
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
        <span className="font-mono">{t.entry_price} → {t.exit_price ?? "—"}</span>
      </div>
    </article>
  );
}
