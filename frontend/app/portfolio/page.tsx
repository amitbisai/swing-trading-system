"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { StatCard } from "@/components/stat-card";
import { PositionCard, ClosedPositionCard } from "@/components/position-card";
import { usePaperTrades, usePortfolioSnapshot } from "@/lib/api";
import { formatCurrency, formatPct } from "@/lib/utils";
import { cn } from "@/lib/utils";

type Tab = "open" | "closed";

export default function PortfolioPage() {
  const [tab, setTab] = useState<Tab>("open");

  const { data: snapshot } = usePortfolioSnapshot();
  const { data: openTrades, isLoading: openLoading } = usePaperTrades("open");
  const { data: closedTrades, isLoading: closedLoading } = usePaperTrades("closed");

  const isLoading = tab === "open" ? openLoading : closedLoading;
  const trades = tab === "open" ? openTrades : closedTrades;

  const totalCapital = snapshot ? parseFloat(snapshot.total_capital) : null;
  const initialCapital = 100000; // from env ideally — use 100k as display default
  const returnPct = totalCapital ? ((totalCapital - initialCapital) / initialCapital) * 100 : null;
  const isPositive = returnPct !== null && returnPct >= 0;

  return (
    <div className="px-4 py-5 max-w-2xl mx-auto space-y-4">
      <h1 className="text-xl font-bold text-white">Portfolio</h1>

      {/* ── Stats bar ── */}
      {snapshot ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <StatCard
            label="Total Capital"
            value={formatCurrency(snapshot.total_capital)}
            mono
          />
          <StatCard
            label="Cash"
            value={formatCurrency(snapshot.cash_balance)}
            mono
          />
          <StatCard
            label="Unrealized P&L"
            value={formatCurrency(snapshot.unrealized_pnl)}
            positive={parseFloat(snapshot.unrealized_pnl) >= 0}
            negative={parseFloat(snapshot.unrealized_pnl) < 0}
            mono
          />
          <StatCard
            label="Return"
            value={returnPct !== null ? `${isPositive ? "+" : ""}${returnPct.toFixed(2)}%` : "—"}
            positive={isPositive}
            negative={!isPositive && returnPct !== null}
            mono
          />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="rounded-xl border border-slate-700 bg-slate-800 p-4 animate-pulse h-16" />
          ))}
        </div>
      )}

      {/* ── Tabs ── */}
      <div className="flex border border-slate-700 rounded-lg overflow-hidden w-fit">
        {(["open", "closed"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "px-4 py-1.5 text-sm font-medium transition-colors capitalize",
              tab === t
                ? "bg-slate-700 text-white"
                : "text-slate-400 hover:text-white",
            )}
          >
            {t}
            {t === "open" && openTrades !== undefined && (
              <span className="ml-1.5 text-xs text-slate-500">({openTrades.length})</span>
            )}
          </button>
        ))}
      </div>

      {/* ── Positions ── */}
      {isLoading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
        </div>
      ) : !trades?.length ? (
        <div className="rounded-xl border border-slate-700 bg-slate-800 p-8 text-center">
          <p className="text-slate-400 text-sm">
            {tab === "open" ? "No open positions." : "No closed trades yet."}
          </p>
          {tab === "open" && (
            <p className="text-slate-600 text-xs mt-1">
              Open a trade from the Signals page.
            </p>
          )}
        </div>
      ) : tab === "open" ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {trades.map((t) => (
            <PositionCard key={t.id} trade={t} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {trades.map((t) => (
            <ClosedPositionCard key={t.id} trade={t} />
          ))}
        </div>
      )}

      {snapshot && (
        <p className="text-center text-xs text-slate-600">
          As of {snapshot.snapshot_date} · {snapshot.open_positions} open position{snapshot.open_positions !== 1 ? "s" : ""}
        </p>
      )}
    </div>
  );
}
