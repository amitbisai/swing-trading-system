"use client";

import { useState } from "react";
import { TrendingUp, TrendingDown, Loader2, CheckCircle, AlertCircle } from "lucide-react";
import { cn, formatCurrency } from "@/lib/utils";
import { openTrade } from "@/lib/api";
import type { Suggestion } from "@/lib/types";

interface Props {
  suggestion: Suggestion;
  currentPrice?: number;
}

function ConfidenceBar({ score }: { score: number }) {
  const color =
    score >= 70 ? "bg-emerald-500" :
    score >= 55 ? "bg-amber-500" :
    "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-slate-700">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${score}%` }} />
      </div>
      <span className="text-xs font-mono text-slate-300 w-10 text-right">{score}/100</span>
    </div>
  );
}

function ScorePill({ label, score }: { label: string; score: number }) {
  const color =
    score >= 70 ? "text-emerald-400 bg-emerald-900/40" :
    score >= 50 ? "text-amber-400 bg-amber-900/40" :
    "text-red-400 bg-red-900/40";
  return (
    <span className={cn("text-[10px] font-mono px-1.5 py-0.5 rounded", color)}>
      {label} {score}
    </span>
  );
}

export function SuggestionCard({ suggestion: s, currentPrice }: Props) {
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");

  const isLong = s.direction === "LONG";

  async function handleOpenTrade() {
    setStatus("loading");
    setErrorMsg("");
    try {
      await openTrade(s.id);
      setStatus("done");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Failed to open trade");
      setStatus("error");
    }
  }

  return (
    <article className="rounded-xl border border-slate-700 bg-slate-800 p-4 space-y-3">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xl font-bold text-white truncate">{s.symbol}</span>
          <span
            className={cn(
              "flex items-center gap-0.5 text-xs font-semibold px-2 py-0.5 rounded-full shrink-0",
              isLong
                ? "bg-emerald-900/60 text-emerald-400"
                : "bg-red-900/60 text-red-400",
            )}
          >
            {isLong ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
            {s.direction}
          </span>
        </div>
        <span
          className={cn(
            "text-[11px] font-medium px-2 py-0.5 rounded-full shrink-0",
            s.tier === "T1"
              ? "bg-blue-900/60 text-blue-400"
              : "bg-amber-900/60 text-amber-400",
          )}
        >
          {s.tier}
        </span>
      </div>

      {/* ── Confidence bar ────────────────────────────────────────────────── */}
      <div>
        <p className="text-[10px] text-slate-500 mb-1 uppercase tracking-wide">Confidence</p>
        <ConfidenceBar score={s.confidence_score} />
      </div>

      {/* ── Sub-scores ───────────────────────────────────────────────────── */}
      <div className="flex gap-1.5">
        <ScorePill label="TA"   score={s.ta_score} />
        <ScorePill label="Sent" score={s.sentiment_score} />
        <ScorePill label="Pat"  score={s.pattern_score} />
      </div>

      {/* ── Last price ───────────────────────────────────────────────────── */}
      {currentPrice !== undefined && (
        <div className="flex items-center justify-between px-0.5">
          <span className="text-[10px] text-slate-500 uppercase tracking-wide">Last Price</span>
          <span className="font-mono text-sm font-semibold text-white">
            ${currentPrice.toFixed(2)}
          </span>
        </div>
      )}

      {/* ── Price levels ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-1 text-center">
        <div className="rounded-lg bg-slate-900 p-2">
          <p className="text-[10px] text-slate-500 mb-0.5">Signal Entry</p>
          <p className="font-mono text-sm text-white">{formatCurrency(s.entry_price)}</p>
        </div>
        <div className="rounded-lg bg-slate-900 p-2">
          <p className="text-[10px] text-slate-500 mb-0.5">Stop</p>
          <p className="font-mono text-sm text-red-400">{formatCurrency(s.stop_loss)}</p>
        </div>
        <div className="rounded-lg bg-slate-900 p-2">
          <p className="text-[10px] text-slate-500 mb-0.5">Target</p>
          <p className="font-mono text-sm text-emerald-400">{formatCurrency(s.target_price)}</p>
        </div>
      </div>

      {/* ── R:R + date ───────────────────────────────────────────────────── */}
      <div className="flex justify-between text-xs text-slate-500">
        <span>R:R <span className="text-slate-300 font-mono">{s.risk_reward.toFixed(1)}×</span></span>
        <span>{s.as_of_date}</span>
      </div>

      {/* ── Rationale ────────────────────────────────────────────────────── */}
      <p className="text-xs text-slate-400 leading-relaxed line-clamp-3">{s.rationale}</p>

      {/* ── Action ───────────────────────────────────────────────────────── */}
      {status === "done" ? (
        <div className="flex items-center gap-1.5 text-emerald-400 text-xs">
          <CheckCircle className="h-4 w-4" />
          Trade opened (auto-sized)
        </div>
      ) : status === "error" ? (
        <div className="flex items-start gap-1.5 text-red-400 text-xs">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          {errorMsg}
        </div>
      ) : (
        <button
          onClick={handleOpenTrade}
          disabled={status === "loading"}
          className={cn(
            "w-full rounded-lg py-2 text-sm font-semibold transition-colors",
            isLong
              ? "bg-emerald-700 hover:bg-emerald-600 text-white"
              : "bg-red-700 hover:bg-red-600 text-white",
            status === "loading" && "opacity-60 cursor-not-allowed",
          )}
        >
          {status === "loading" ? (
            <span className="flex items-center justify-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" /> Opening…
            </span>
          ) : (
            `Open ${s.direction} Trade`
          )}
        </button>
      )}
    </article>
  );
}
