"use client";

import { useState, useEffect, useRef, KeyboardEvent } from "react";
import useSWR from "swr";
import { Loader2, RefreshCw, Search, X, Zap } from "lucide-react";
import { FinancialCard, FinancialCardSkeleton } from "@/components/financial-card";
import type { ApiResponse, FinancialSummary } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const LS_KEY = "financials-symbols";   // localStorage key

// ── Persistence hook ──────────────────────────────────────────────────────────
// Initialises from localStorage on first render; syncs every change back.

function usePersistedSymbols() {
  const [symbols, setSymbols] = useState<string[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      const raw = localStorage.getItem(LS_KEY);
      return raw ? (JSON.parse(raw) as string[]) : [];
    } catch {
      return [];
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(symbols));
    } catch {
      // private-mode or storage full — ignore
    }
  }, [symbols]);

  return [symbols, setSymbols] as const;
}

// ── Per-symbol SWR fetcher ────────────────────────────────────────────────────

function useFinancial(symbol: string) {
  return useSWR<FinancialSummary>(
    `${API_BASE}/api/financials/${symbol}`,
    async (url: string) => {
      const res = await fetch(url);
      const json: ApiResponse<FinancialSummary> = await res.json();
      if (!res.ok || json.error) throw new Error(json.error ?? `HTTP ${res.status}`);
      return json.data;
    },
    { revalidateOnFocus: false, revalidateOnReconnect: false },
  );
}

// ── Individual card wrapper ───────────────────────────────────────────────────

function SymbolCard({ symbol, onRemove }: { symbol: string; onRemove: () => void }) {
  const { data, error, isLoading, isValidating, mutate } = useFinancial(symbol);

  // First-time load → skeleton
  if (isLoading) return <FinancialCardSkeleton />;

  // Fetch failed
  if (error || !data) {
    return (
      <div className="bg-slate-800 rounded-xl border border-red-800/50 p-4">
        <div className="flex justify-between items-start gap-3">
          <div className="min-w-0">
            <p className="font-bold text-white">{symbol}</p>
            <p className="text-red-400 text-sm mt-1 break-words">
              {error?.message ?? "Failed to load data"}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => mutate()}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
              title="Retry"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
            <button
              onClick={onRemove}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-700 transition-colors"
              aria-label="Remove"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <FinancialCard
      data={data}
      isRefreshing={isValidating}
      onRefresh={() => mutate()}
      onRemove={onRemove}
    />
  );
}

// ── Quick-add presets ─────────────────────────────────────────────────────────

const QUICK_PRESETS = [
  { label: "Mag-7",   symbols: ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"] },
  { label: "Semis",   symbols: ["NVDA", "AMD", "AVGO", "AMBA", "MRVL", "QCOM"] },
  { label: "AI Play", symbols: ["NVDA", "MSFT", "PLTR", "AI", "SOUN"] },
] as const;

// ── Page ──────────────────────────────────────────────────────────────────────

export default function FinancialsPage() {
  const [symbols, setSymbols] = usePersistedSymbols();
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function addSymbol(raw: string) {
    const sym = raw.trim().toUpperCase().replace(/[^A-Z.]/g, "");
    if (!sym || sym.length > 10) return;
    if (symbols.includes(sym)) { setInput(""); return; }
    if (symbols.length >= 10) return;
    setSymbols(prev => [...prev, sym]);
    setInput("");
  }

  function removeSymbol(sym: string) {
    setSymbols(prev => prev.filter(s => s !== sym));
  }

  function handleKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addSymbol(input);
    }
  }

  function loadPreset(syms: readonly string[]) {
    const next = [...symbols];
    for (const s of syms) {
      if (!next.includes(s) && next.length < 10) next.push(s);
    }
    setSymbols(next);
  }

  function clearAll() {
    setSymbols([]);
    setInput("");
    inputRef.current?.focus();
  }

  return (
    <main className="min-h-screen bg-slate-900 px-4 py-6 pb-24 sm:pb-6">
      <div className="max-w-6xl mx-auto">

        {/* ── Page header ────────────────────────────────────────────────────── */}
        <div className="mb-6">
          <h1 className="text-white font-bold text-2xl">Financial Analysis</h1>
          <p className="text-slate-400 text-sm mt-0.5">
            On-demand fundamentals, earnings risk, and AI swing-trade assessment
          </p>
        </div>

        {/* ── Search bar ─────────────────────────────────────────────────────── */}
        <div className="mb-4">
          <div className="flex gap-2">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500 pointer-events-none" />
              <input
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value.toUpperCase())}
                onKeyDown={handleKey}
                placeholder="Enter ticker (e.g. AMBA) and press Enter"
                className="w-full bg-slate-800 border border-slate-600 rounded-lg pl-9 pr-4 py-2.5
                           text-white placeholder-slate-500 text-sm focus:outline-none
                           focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50"
                maxLength={10}
                autoComplete="off"
                spellCheck={false}
              />
            </div>
            <button
              onClick={() => addSymbol(input)}
              disabled={!input.trim()}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed
                         text-white text-sm font-medium px-4 rounded-lg transition-colors"
            >
              Add
            </button>
            {symbols.length > 0 && (
              <button
                onClick={clearAll}
                className="text-slate-400 hover:text-white text-sm px-3 rounded-lg
                           border border-slate-700 hover:border-slate-500 transition-colors"
              >
                Clear all
              </button>
            )}
          </div>

          {/* Quick-add presets */}
          <div className="flex flex-wrap gap-2 mt-2">
            {QUICK_PRESETS.map(({ label, symbols: syms }) => (
              <button
                key={label}
                onClick={() => loadPreset(syms)}
                className="flex items-center gap-1 text-xs text-slate-400 hover:text-white
                           border border-slate-700 hover:border-slate-500 rounded-full
                           px-3 py-1 transition-colors"
              >
                <Zap className="h-3 w-3" />
                {label}
              </button>
            ))}
            <span className="text-xs text-slate-600 self-center ml-1">
              {symbols.length}/10 saved
            </span>
          </div>
        </div>

        {/* ── Active symbol chips ─────────────────────────────────────────────── */}
        {symbols.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-5">
            {symbols.map(sym => (
              <span
                key={sym}
                className="flex items-center gap-1.5 bg-slate-700 text-slate-200
                           text-xs font-medium px-2.5 py-1 rounded-full"
              >
                {sym}
                <button
                  onClick={() => removeSymbol(sym)}
                  className="text-slate-500 hover:text-white transition-colors"
                  aria-label={`Remove ${sym}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}

        {/* ── Empty state ────────────────────────────────────────────────────── */}
        {symbols.length === 0 && (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <Search className="h-12 w-12 text-slate-700 mb-4" />
            <p className="text-slate-400 font-medium">No stocks added yet</p>
            <p className="text-slate-600 text-sm mt-1 max-w-xs">
              Enter a ticker above or use a quick-add preset to see earnings risk,
              fundamentals, and a Claude swing-trade view. Your watchlist is saved
              automatically.
            </p>
          </div>
        )}

        {/* ── Card grid ──────────────────────────────────────────────────────── */}
        {symbols.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {symbols.map(sym => (
              <SymbolCard
                key={sym}
                symbol={sym}
                onRemove={() => removeSymbol(sym)}
              />
            ))}
          </div>
        )}

      </div>
    </main>
  );
}
