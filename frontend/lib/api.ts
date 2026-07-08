import useSWR from "swr";
import type {
  AnalyticsSummary,
  ApiResponse,
  FinancialSummary,
  OpenTradeResponse,
  PaperTrade,
  PersistentPick,
  PortfolioSnapshot,
  Suggestion,
  T1Scan,
  T2Scan,
  TradeStatus,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Core fetcher ──────────────────────────────────────────────────────────────

async function fetcher<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  const json: ApiResponse<T> = await res.json();
  if (json.error) throw new Error(json.error);
  return json.data;
}

// ── Suggestions ───────────────────────────────────────────────────────────────

export interface SuggestionParams {
  date?: string;        // YYYY-MM-DD
  tier?: "T1" | "T2";
  action?: "LONG" | "SHORT";
  active_only?: boolean;
}

export function useSuggestions(params: SuggestionParams = {}) {
  const qs = new URLSearchParams();
  if (params.date)   qs.set("date",        params.date);
  if (params.tier)   qs.set("tier",        params.tier);
  if (params.action) qs.set("action",      params.action);
  if (params.active_only === false) qs.set("active_only", "false");
  const key = `/api/suggestions/?${qs.toString()}`;
  return useSWR<Suggestion[]>(key, fetcher<Suggestion[]>);
}

/**
 * Symbols repeatedly surfaced by the system (suggestions + T2 scans) over the
 * last `window` days. Flagged when seen on >= `minDays` distinct days.
 */
export function usePersistentPicks(window = 7, minDays = 3) {
  return useSWR<PersistentPick[]>(
    `/api/suggestions/persistent?window=${window}&min_days=${minDays}`,
    fetcher<PersistentPick[]>,
  );
}

export function useSuggestion(id: number | null) {
  return useSWR<Suggestion>(
    id ? `/api/suggestions/${id}` : null,
    fetcher<Suggestion>,
  );
}

// ── Paper trades ──────────────────────────────────────────────────────────────

export function usePaperTrades(status: TradeStatus = "all") {
  return useSWR<PaperTrade[]>(
    `/api/paper-trades/?status=${status}`,
    fetcher<PaperTrade[]>,
  );
}

export async function openTrade(
  suggestion_id: number,
  shares?: number,
): Promise<OpenTradeResponse> {
  const body = shares ? { suggestion_id, shares } : { suggestion_id };
  const res = await fetch(`${API_BASE}/api/paper-trades/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const json: ApiResponse<OpenTradeResponse> = await res.json();
  if (!res.ok || json.error) throw new Error(json.error ?? `HTTP ${res.status}`);
  return json.data;
}

export async function closeTrade(
  trade_id: number,
  exit_price: number,
): Promise<PaperTrade> {
  const res = await fetch(`${API_BASE}/api/paper-trades/${trade_id}/close`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ exit_price, exit_reason: "MANUAL_CLOSE" }),
  });
  const json: ApiResponse<PaperTrade> = await res.json();
  if (!res.ok || json.error) throw new Error(json.error ?? `HTTP ${res.status}`);
  return json.data;
}

// ── Portfolio ─────────────────────────────────────────────────────────────────

export function usePortfolioSnapshot(date?: string) {
  const url = date
    ? `/api/portfolio/snapshot?date=${date}`
    : "/api/portfolio/snapshot";
  return useSWR<PortfolioSnapshot>(url, fetcher<PortfolioSnapshot>);
}

export function usePortfolioHistory(days = 30) {
  return useSWR<PortfolioSnapshot[]>(
    `/api/portfolio/history?days=${days}`,
    fetcher<PortfolioSnapshot[]>,
  );
}

// ── Analytics ─────────────────────────────────────────────────────────────────

export function useAnalyticsSummary() {
  return useSWR<AnalyticsSummary>(
    "/api/analytics/summary",
    fetcher<AnalyticsSummary>,
  );
}

// ── Strategy settings ─────────────────────────────────────────────────────────

export interface StrategySettings {
  max_entries_per_day: number;   // 0 = unlimited
}

export function useStrategySettings() {
  return useSWR<StrategySettings>(
    "/api/strategy-settings/",
    fetcher<StrategySettings>,
  );
}

export async function updateStrategySettings(
  settings: StrategySettings,
): Promise<StrategySettings> {
  const res = await fetch(`${API_BASE}/api/strategy-settings/`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  const json: ApiResponse<StrategySettings> = await res.json();
  if (!res.ok || json.error) throw new Error(json.error ?? `HTTP ${res.status}`);
  return json.data;
}

// ── Market pulse ──────────────────────────────────────────────────────────────

export interface MarketPulse {
  score: number;
  label: "STRONG" | "UPTREND" | "NEUTRAL" | "WEAK" | "AVOID";
  entries_allowed: number;        // -1 = unlimited
  max_entries_per_day: number;
  spy_close: number | null;
  spy_sma50: number | null;
  spy_sma200: number | null;
  breadth_pct: number | null;
}

export function useMarketPulse() {
  return useSWR<MarketPulse>(
    "/api/analytics/market-pulse",
    fetcher<MarketPulse>,
    { revalidateOnFocus: false, dedupingInterval: 300_000 },
  );
}

// ── Outcome analytics ─────────────────────────────────────────────────────────

export interface OutcomeBucket {
  trades: number;
  win_rate_pct: number | null;
  avg_r: number | null;
  total_pnl: number;
  avg_mfe_r: number | null;
  avg_mae_r: number | null;
  avg_exit_efficiency: number | null;
  avg_post_exit_10d_pct: number | null;
}

export interface OutcomeAnalytics {
  total_outcomes: number;
  by_tier: Record<string, OutcomeBucket>;
  by_direction: Record<string, OutcomeBucket>;
  by_exit_reason: Record<string, OutcomeBucket>;
  by_confidence: Record<string, OutcomeBucket>;
  by_ta_score: Record<string, OutcomeBucket>;
  by_sentiment_score: Record<string, OutcomeBucket>;
  by_pattern_score: Record<string, OutcomeBucket>;
  by_pulse: Record<string, OutcomeBucket>;
  by_news_verdict: Record<string, OutcomeBucket>;
  by_levels_adjusted: Record<string, OutcomeBucket>;
}

export function useOutcomeAnalytics() {
  return useSWR<OutcomeAnalytics>(
    "/api/analytics/outcomes",
    fetcher<OutcomeAnalytics>,
    { revalidateOnFocus: false },
  );
}

export interface PulseDay {
  date: string;
  score: number;
  label: string;
  breadth_pct: number | null;
}

export function usePulseHistory(days = 30) {
  return useSWR<PulseDay[]>(
    `/api/analytics/pulse-history?days=${days}`,
    fetcher<PulseDay[]>,
    { revalidateOnFocus: false },
  );
}

// ── Backtest ──────────────────────────────────────────────────────────────────

export interface BacktestParams {
  start?: string;
  end?: string;
  top_n: number;
  min_confidence: number;
  sample: number;
  exit_mode: "intrabar" | "close";
  long_only: boolean;
  atr_stop_mult?: number | null;
  atr_target_mult?: number | null;
  max_holding_days?: number | null;
}

export interface BacktestResultSummary {
  initial_capital: number;
  final_equity: number;
  total_return_pct: number;
  cagr_pct: number;
  max_drawdown_pct: number;
  spy_return_pct: number;
  trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number | null;
  profit_factor: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  avg_holding_days: number | null;
  exits_by_reason: Record<string, number>;
  avg_signals_per_day: number | null;
  zero_signal_days: number;
  trading_days: number;
  avg_pulse: number | null;
  equity_curve: { date: string; equity: number; spy: number | null }[];
  params: Record<string, unknown>;
}

export interface BacktestStatus {
  running: boolean;
  stage: string | null;
  params: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  result: BacktestResultSummary | null;
  error: string | null;
}

export function useBacktestStatus(pollWhileRunning: boolean) {
  return useSWR<BacktestStatus>(
    "/api/backtest/status",
    fetcher<BacktestStatus>,
    {
      refreshInterval: pollWhileRunning ? 3000 : 0,
      revalidateOnFocus: false,
    },
  );
}

export async function runBacktest(params: BacktestParams): Promise<void> {
  const res = await fetch(`${API_BASE}/api/backtest/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const json = await res.json();
  if (!res.ok || json.error) {
    throw new Error(json.detail ?? json.error ?? `HTTP ${res.status}`);
  }
}

// ── T1 Scans ──────────────────────────────────────────────────────────────────

/**
 * signal_only=true (default) — only stocks that became a final T1 suggestion.
 * Pass signal_only=false to fetch all 146+ screened stocks (debug use only).
 */
export function useT1Scans(days = 30, signalOnly = true) {
  return useSWR<T1Scan[]>(
    `/api/t1-scans/?days=${days}&signal_only=${signalOnly}`,
    fetcher<T1Scan[]>,
  );
}

// ── T2 Scans ──────────────────────────────────────────────────────────────────

export function useT2Scans(days = 30) {
  return useSWR<T2Scan[]>(
    `/api/t2-scans/?days=${days}`,
    fetcher<T2Scan[]>,
  );
}

// ── Latest prices ─────────────────────────────────────────────────────────────

export function useLatestPrices(symbols: string[]) {
  const key = symbols.length > 0
    ? `/api/prices/latest?symbols=${symbols.join(",")}`
    : null;
  return useSWR<Record<string, number>>(key, fetcher<Record<string, number>>);
}

// ── Financial Analysis ────────────────────────────────────────────────────────

/**
 * Fetch on-demand financial analysis for one symbol.
 * Pass null to skip (e.g. before the user enters a ticker).
 * revalidateOnFocus=false because the data is expensive to fetch.
 */
export function useFinancials(symbol: string | null) {
  return useSWR<FinancialSummary>(
    symbol ? `/api/financials/${symbol.toUpperCase()}` : null,
    fetcher<FinancialSummary>,
    { revalidateOnFocus: false },
  );
}

/**
 * Fetch financial analysis for multiple symbols in one batch request.
 */
export function useFinancialsBatch(symbols: string[]) {
  const key = symbols.length > 0
    ? `/api/financials/?symbols=${symbols.map(s => s.toUpperCase()).join(",")}`
    : null;
  return useSWR<FinancialSummary[]>(key, fetcher<FinancialSummary[]>, {
    revalidateOnFocus: false,
  });
}

// ── Stocks ────────────────────────────────────────────────────────────────────

export function useStocks(tier?: string) {
  const url = tier ? `/api/stocks/?tier=${tier}` : "/api/stocks/";
  return useSWR<{ symbol: string; name: string; tier: string }[]>(
    url,
    fetcher,
  );
}
