"use client";

import { useState } from "react";
import { SuggestionCard } from "@/components/suggestion-card";
import { useSuggestions } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2, RefreshCw } from "lucide-react";

type Tier = "T1" | "T2" | "";
type Dir = "LONG" | "SHORT" | "";

function FilterPill<T extends string>({
  label,
  value,
  active,
  onClick,
}: {
  label: string;
  value: T;
  active: boolean;
  onClick: (v: T | "") => void;
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

export default function SuggestionsPage() {
  const [tier, setTier] = useState<Tier>("");
  const [dir, setDir] = useState<Dir>("");
  const [activeOnly, setActiveOnly] = useState(true);

  const { data, error, isLoading, mutate } = useSuggestions({
    ...(tier ? { tier } : {}),
    ...(dir ? { action: dir } : {}),
    active_only: activeOnly,
  });

  return (
    <div className="px-4 py-5 max-w-2xl mx-auto space-y-4">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white">Signals</h1>
        <button
          onClick={() => mutate()}
          className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
          aria-label="Refresh"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      {/* ── Filters ── */}
      <div className="flex flex-wrap gap-2">
        <FilterPill<Tier> label="T1" value="T1" active={tier === "T1"} onClick={setTier} />
        <FilterPill<Tier> label="T2" value="T2" active={tier === "T2"} onClick={setTier} />
        <div className="w-px bg-slate-700 self-stretch mx-1" />
        <FilterPill<Dir> label="Long" value="LONG" active={dir === "LONG"} onClick={setDir} />
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
      </div>

      {/* ── Content ── */}
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
          <p className="text-slate-600 text-xs mt-1">Run <code className="text-slate-500">make agents</code> to generate today's signals.</p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {data.map((s) => (
            <SuggestionCard key={s.id} suggestion={s} />
          ))}
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
