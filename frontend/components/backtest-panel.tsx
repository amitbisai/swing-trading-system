"use client";

import { useState } from "react";
import { FlaskConical, Loader2, Play } from "lucide-react";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Legend,
  CartesianGrid,
} from "recharts";
import { cn } from "@/lib/utils";
import {
  runBacktest,
  useBacktestStatus,
  type BacktestParams,
  type BacktestResultSummary,
} from "@/lib/api";

// ── Small form primitives ─────────────────────────────────────────────────────

function Field({
  label, children, hint,
}: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block space-y-1">
      <span className="text-[11px] text-slate-400">{label}</span>
      {children}
      {hint && <span className="block text-[10px] text-slate-600">{hint}</span>}
    </label>
  );
}

const inputCls =
  "w-full bg-slate-900 border border-slate-600 rounded-lg px-2.5 py-1.5 text-sm " +
  "font-mono text-white focus:outline-none focus:border-slate-400 " +
  "[appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none " +
  "[&::-webkit-inner-spin-button]:appearance-none [color-scheme:dark]";

function iso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export function BacktestPanel() {
  const today = new Date();
  const yearAgo = new Date(today.getTime() - 365 * 86400_000);

  const [form, setForm] = useState({
    start: iso(yearAgo),
    end: iso(today),
    top_n: "5",
    min_confidence: "63",
    sample: "150",
    exit_mode: "intrabar" as "intrabar" | "close",
    long_only: true,
    atr_stop_mult: "",
    atr_target_mult: "",
    max_holding_days: "",
  });
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [kicked, setKicked] = useState(false);

  const { data: status, mutate } = useBacktestStatus(kicked || false);
  const running = status?.running ?? false;

  function set<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleRun() {
    setSubmitError(null);
    const params: BacktestParams = {
      start: form.start,
      end: form.end,
      top_n: parseInt(form.top_n) || 5,
      min_confidence: parseInt(form.min_confidence) || 63,
      sample: parseInt(form.sample) || 150,
      exit_mode: form.exit_mode,
      long_only: form.long_only,
      atr_stop_mult: form.atr_stop_mult ? parseFloat(form.atr_stop_mult) : null,
      atr_target_mult: form.atr_target_mult ? parseFloat(form.atr_target_mult) : null,
      max_holding_days: form.max_holding_days ? parseInt(form.max_holding_days) : null,
    };
    try {
      await runBacktest(params);
      setKicked(true);
      await mutate();
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : "Failed to start backtest.");
    }
  }

  return (
    <div className="space-y-4">
      {/* ── Parameters ── */}
      <section className="rounded-xl border border-slate-700 bg-slate-800 p-4 space-y-3">
        <div className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-medium text-white">Backtest parameters</h2>
        </div>
        <p className="text-[11px] text-slate-500">
          Replays the live ruleset over history (T1 strategy; sentiment neutral,
          T2 + earnings gate excluded). Leave the override fields blank to test
          the currently deployed values.
        </p>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Field label="Start">
            <input type="date" className={inputCls} value={form.start}
                   onChange={(e) => set("start", e.target.value)} disabled={running} />
          </Field>
          <Field label="End">
            <input type="date" className={inputCls} value={form.end}
                   onChange={(e) => set("end", e.target.value)} disabled={running} />
          </Field>
          <Field label="Top-N / day">
            <input type="number" min={0} max={50} className={inputCls} value={form.top_n}
                   onChange={(e) => set("top_n", e.target.value)} disabled={running} />
          </Field>
          <Field label="Min confidence">
            <input type="number" min={0} max={100} className={inputCls} value={form.min_confidence}
                   onChange={(e) => set("min_confidence", e.target.value)} disabled={running} />
          </Field>
          <Field label="Universe sample" hint="≤250 (memory cap)">
            <input type="number" min={20} max={250} className={inputCls} value={form.sample}
                   onChange={(e) => set("sample", e.target.value)} disabled={running} />
          </Field>
          <Field label="Exit mode" hint="intrabar = stops vs daily low (harsher)">
            <select className={inputCls} value={form.exit_mode} disabled={running}
                    onChange={(e) => set("exit_mode", e.target.value as "intrabar" | "close")}>
              <option value="intrabar">intrabar</option>
              <option value="close">close</option>
            </select>
          </Field>
          <Field label="ATR stop × (override)" hint="live: 1.5">
            <input type="number" step="0.1" placeholder="1.5" className={inputCls}
                   value={form.atr_stop_mult}
                   onChange={(e) => set("atr_stop_mult", e.target.value)} disabled={running} />
          </Field>
          <Field label="Max holding days (override)" hint="live: 14">
            <input type="number" min={0} max={60} placeholder="14" className={inputCls}
                   value={form.max_holding_days}
                   onChange={(e) => set("max_holding_days", e.target.value)} disabled={running} />
          </Field>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <label className="flex items-center gap-1.5 text-xs text-slate-300">
            <input type="checkbox" checked={form.long_only} disabled={running}
                   onChange={(e) => set("long_only", e.target.checked)}
                   className="accent-emerald-600" />
            Long only
          </label>
          <button
            onClick={handleRun}
            disabled={running}
            className={cn(
              "ml-auto flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold",
              "bg-emerald-700 hover:bg-emerald-600 text-white transition-colors",
              "disabled:opacity-50 disabled:cursor-not-allowed",
            )}
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {running ? "Running…" : "Run backtest"}
          </button>
        </div>

        {submitError && <p className="text-xs text-red-400">{submitError}</p>}
        {running && (
          <div className="flex items-center gap-2 text-xs text-slate-400 bg-slate-900/70 rounded-lg px-3 py-2">
            <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
            <span>{status?.stage ?? "starting…"}</span>
            <span className="ml-auto text-slate-600">
              first run downloads price data (~1–5 min)
            </span>
          </div>
        )}
        {status?.error && !running && (
          <p className="text-xs text-red-400 bg-red-950/30 border border-red-900/50 rounded-lg px-3 py-2">
            Backtest failed: {status.error}
          </p>
        )}
      </section>

      {/* ── Result ── */}
      {status?.result && !running && <BacktestResultView r={status.result} />}
    </div>
  );
}

// ── Result view ───────────────────────────────────────────────────────────────

function Metric({ label, value, positive, negative }: {
  label: string; value: string; positive?: boolean; negative?: boolean;
}) {
  return (
    <div className="rounded-lg bg-slate-900 p-2.5">
      <p className="text-[10px] text-slate-500 mb-0.5">{label}</p>
      <p className={cn(
        "font-mono text-sm font-semibold",
        positive ? "text-emerald-400" : negative ? "text-red-400" : "text-white",
      )}>
        {value}
      </p>
    </div>
  );
}

function BacktestResultView({ r }: { r: BacktestResultSummary }) {
  const beatSpy = r.total_return_pct >= r.spy_return_pct;
  const p = r.params as { start?: string; end?: string; top_n?: number };

  return (
    <section className="rounded-xl border border-slate-700 bg-slate-800 p-4 space-y-4">
      <div className="flex items-baseline justify-between flex-wrap gap-1">
        <h2 className="text-sm font-medium text-white">
          Result — {p.start} → {p.end}
        </h2>
        <span className={cn(
          "text-[11px] font-semibold px-2 py-0.5 rounded-full",
          beatSpy ? "bg-emerald-900/50 text-emerald-400" : "bg-amber-900/50 text-amber-400",
        )}>
          {beatSpy ? "beat" : "trailed"} SPY by {Math.abs(r.total_return_pct - r.spy_return_pct).toFixed(1)} pts
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Metric label="Total return" value={`${r.total_return_pct >= 0 ? "+" : ""}${r.total_return_pct.toFixed(2)}%`}
                positive={r.total_return_pct >= 0} negative={r.total_return_pct < 0} />
        <Metric label="SPY buy & hold" value={`${r.spy_return_pct >= 0 ? "+" : ""}${r.spy_return_pct.toFixed(2)}%`} />
        <Metric label="CAGR" value={`${r.cagr_pct >= 0 ? "+" : ""}${r.cagr_pct.toFixed(2)}%`}
                positive={r.cagr_pct >= 0} negative={r.cagr_pct < 0} />
        <Metric label="Max drawdown" value={`${r.max_drawdown_pct.toFixed(2)}%`} negative />
        <Metric label="Trades" value={`${r.trades} (${r.wins}W/${r.losses}L)`} />
        <Metric label="Win rate" value={r.win_rate_pct != null ? `${r.win_rate_pct.toFixed(1)}%` : "—"}
                positive={(r.win_rate_pct ?? 0) >= 50} />
        <Metric label="Profit factor" value={r.profit_factor != null ? r.profit_factor.toFixed(2) : "—"}
                positive={(r.profit_factor ?? 0) >= 1.2} negative={(r.profit_factor ?? 2) < 1} />
        <Metric label="Avg holding" value={r.avg_holding_days != null ? `${r.avg_holding_days.toFixed(1)}d` : "—"} />
      </div>

      {/* equity vs SPY */}
      <div>
        <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-2">
          Equity curve vs SPY (same starting capital)
        </p>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={r.equity_curve} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#64748b" }}
                   tickLine={false} axisLine={false} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10, fill: "#64748b" }} tickLine={false} axisLine={false}
                   domain={["auto", "auto"]} width={58}
                   tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
            <Tooltip
              contentStyle={{
                background: "#0f172a", border: "1px solid #334155",
                borderRadius: 8, fontSize: 11,
              }}
              formatter={(value: number, name: string) => [
                `$${value.toLocaleString()}`, name === "equity" ? "Strategy" : "SPY",
              ]}
            />
            <Legend wrapperStyle={{ fontSize: 11 }}
                    formatter={(v: string) => (v === "equity" ? "Strategy" : "SPY")} />
            <Line type="monotone" dataKey="equity" stroke="#34d399" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="spy" stroke="#64748b" strokeWidth={1.5}
                  strokeDasharray="4 3" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* exits + coverage */}
      <div className="flex flex-wrap gap-2 text-[11px]">
        {Object.entries(r.exits_by_reason).map(([reason, n]) => (
          <span key={reason} className="px-2 py-1 rounded-full bg-slate-900 text-slate-400 font-mono">
            {reason}: {n}
          </span>
        ))}
        {r.avg_signals_per_day != null && (
          <span className="px-2 py-1 rounded-full bg-slate-900 text-slate-400 font-mono">
            signals/day: {r.avg_signals_per_day}
          </span>
        )}
        <span className="px-2 py-1 rounded-full bg-slate-900 text-slate-400 font-mono">
          zero-signal days: {r.zero_signal_days}/{r.trading_days}
        </span>
        {r.avg_pulse != null && (
          <span className="px-2 py-1 rounded-full bg-slate-900 text-slate-400 font-mono">
            avg pulse: {r.avg_pulse}
          </span>
        )}
      </div>
    </section>
  );
}
