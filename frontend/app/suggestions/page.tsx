"use client";

import { useState } from "react";
import { SuggestionCard } from "@/components/suggestion-card";
import { T2ScanCard } from "@/components/t2-scan-card";
import { useSuggestions, useT2Scans } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2, RefreshCw } from "lucide-react";

type Tier = "T1" | "T2" | "";
type Dir  = "LONG" | "SHORT" | "";
type Tab  = "signals" | "t2-scans";

// ── Shared pill ───────────────────────────────────────────────────────────────

function FilterPill<T extends string>({
  label, value, active, onClick,
}: {
  label: string; value: T; active: boolean; onClick: (v: T | "") => void;
}) {
  return (
    <button
      onClick={() => onClick(active ? "" : value)}
      className={cn(
        "px-3 py-1 rounded-full text-xs font-medium border transition-colors",
        active
          ? "bg-slate-200 text-slate-900 border-transparent"
          : "bg-transparent text-slate-400 border-slate-700 hover:border-slate-500 hover:text-slate-300",
      )}
    >
      {label}
    </button>
  );
}

// ── Signals tab ───────────────────────────────────────────────────────────────

function SignalsTab() {
  const [tier, setTier]           = useState<Tier>("");
  const [dir, setDir]             = useState<Dir>("");
  const [activeOnly, setActiveOnly] = useState(true);

  const { data, error, isLoading, mutate } = useSuggestions({
    ...(tier ? { tier } : {}),
    ...(dir  ? { action: dir } : {}),
    active_only: activeOnly,
  });

  return (
    <div className="space-y-4">
      {/* filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <FilterPill<Tier> label="T1" value="T1" active={tier === "T1"} onClick={setTier} />
        <FilterPill<Tier> label="T2" value="T2" active={tier === "T2"} onClick={setTier} />
        <div className="w-px bg-slate-700 self-stretch mx-1" />
        <FilterPill<Dir> label="Long"  value="LONG"  active={dir === "LONG"}  onClick={setDir} />
        <FilterPill<Dir> label="Short" value="SHORT" active={dir === "SHORT"} onClick={setDir} />
        <div className="w-px bg-slate-700 self-stretch mx-1" />
        <button
          onClick={() => setActiveOnly((p) => !p)}
          className={cn(
            "px-3 py-1 rounded-full text-xs font-medium border transition-colors",
            activeOnly
              ? "bg-slate-200 text-slate-900 border-transparent"
              : "bg-transparent text-slate-400 border-slate-700 hover:border-slate-500",
          )}
        >
          Active only
        </button>
        <button
          onClick={() => mutate()}
          className="ml-auto p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
        </div>
      ) : error ? (
        <div className="rounded-xl border border-red-900/50 bg-red-950/30 p-4 text-sm text-red-400">
          Failed to load suggestions. Check that the backend is running.
        </div>
      ) : !data?.length ? (
        <div className="rounded-xl border border-slate-700 bg-slate-800 p-8 text-center">
          <p className="text-slate-400 text-sm">No signals match your filters.</p>
          <p className="text-slate-600 text-xs mt-1">
            Run <code className="text-slate-500">make agents</code> to generate today&apos;s signals.
          </p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {data.map((s) => <SuggestionCard key={s.id} suggestion={s} />)}
        </div>
      )}

      {data && (
        <p className="text-center text-xs text-slate-600">
          {data.length} signal{data.length !== 1 ? "s" : ""}
        </p>
      )}
    </div>
  );
}

// ── T2 Scans tab ──────────────────────────────────────────────────────────────

function T2ScansTab() {
  const [days, setDays]               = useState(30);
  const [tierFilter, setTierFilter]   = useState<"A" | "B" | "C" | "">("");
  const { data, error, isLoading, mutate } = useT2Scans(days);

  const filtered = tierFilter
    ? (data ?? []).filter((s) => s.signal_tier === tierFilter)
    : (data ?? []);

  // Group by scan_date for timeline display
  const byDate = filtered.reduce<Record<string, typeof filtered>>((acc, scan) => {
    (acc[scan.scan_date] ??= []).push(scan);
    return acc;
  }, {});
  const dates = Object.keys(byDate).sort((a, b) => b.localeCompare(a));

  return (
    <div className="space-y-4">
      {/* controls */}
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-xs text-slate-500">Tier:</span>
        {(["A", "B", "C"] as const).map((t) => (
          <FilterPill<"A" | "B" | "C">
            key={t} label={`Tier ${t}`} value={t}
            active={tierFilter === t}
            onClick={(v) => setTierFilter(v as "A" | "B" | "C" | "")}
          />
        ))}
        <div className="w-px bg-slate-700 self-stretch mx-1" />
        <span className="text-xs text-slate-500">History:</span>
        {([7, 14, 30] as const).map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={cn(
              "px-3 py-1 rounded-full text-xs font-medium border transition-colors",
              days === d
                ? "bg-slate-200 text-slate-900 border-transparent"
                : "bg-transparent text-slate-400 border-slate-700 hover:border-slate-500 hover:text-slate-300",
            )}
          >
            {d}d
          </button>
        ))}
        <button
          onClick={() => mutate()}
          className="ml-auto p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      {/* legend */}
      <div className="flex flex-wrap gap-3 text-xs text-slate-500">
        <span className="text-emerald-400 font-medium">Tier A</span> = strong institutional accumulation
        <span className="mx-1">·</span>
        <span className="text-blue-400 font-medium">Tier B</span> = emerging momentum
        <span className="mx-1">·</span>
        <span className="text-slate-400 font-medium">Tier C</span> = watchlist
      </div>

      {isLoading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
        </div>
      ) : error ? (
        <div className="rounded-xl border border-red-900/50 bg-red-950/30 p-4 text-sm text-red-400">
          Failed to load T2 scan data. Check that the backend is running.
        </div>
      ) : dates.length === 0 ? (
        <div className="rounded-xl border border-slate-700 bg-slate-800 p-8 text-center">
          <p className="text-slate-400 text-sm">No T2 scan results in the last {days} days.</p>
          <p className="text-slate-600 text-xs mt-1">
            Run after US market close (10 PM IST) to see today&apos;s candidates.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {dates.map((d) => (
            <div key={d}>
              {/* date divider */}
              <div className="flex items-center gap-3 mb-3">
                <span className="text-xs font-semibold text-slate-400">{d}</span>
                <div className="flex-1 h-px bg-slate-700" />
                <span className="text-xs text-slate-600">{byDate[d].length} stock{byDate[d].length !== 1 ? "s" : ""}</span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {byDate[d].map((scan) => <T2ScanCard key={scan.id} scan={scan} />)}
              </div>
            </div>
          ))}
        </div>
      )}

      {data && filtered.length > 0 && (
        <p className="text-center text-xs text-slate-600">
          {filtered.length} scan record{filtered.length !== 1 ? "s" : ""}
          {tierFilter ? ` (Tier ${tierFilter})` : ""} over last {days} days
        </p>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SuggestionsPage() {
  const [tab, setTab] = useState<Tab>("signals");

  return (
    <div className="px-4 py-5 max-w-2xl mx-auto space-y-4">
      {/* ── Header ── */}
      <h1 className="text-xl font-bold text-white">Signals</h1>

      {/* ── Tab bar ── */}
      <div className="flex rounded-xl bg-slate-800/60 p-1 border border-slate-700 gap-1">
        <button
          onClick={() => setTab("signals")}
          className={cn(
            "flex-1 py-2 rounded-lg text-sm font-medium transition-colors",
            tab === "signals"
              ? "bg-slate-700 text-white shadow-sm"
              : "text-slate-400 hover:text-slate-300",
          )}
        >
          AI Signals
        </button>
        <button
          onClick={() => setTab("t2-scans")}
          className={cn(
            "flex-1 py-2 rounded-lg text-sm font-medium transition-colors",
            tab === "t2-scans"
              ? "bg-slate-700 text-white shadow-sm"
              : "text-slate-400 hover:text-slate-300",
          )}
        >
          T2 Scan History
        </button>
      </div>

      {/* ── Content ── */}
      {tab === "signals" ? <SignalsTab /> : <T2ScansTab />}
    </div>
  );
}
