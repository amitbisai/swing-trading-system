import useSWR from "swr";
import type {
  AnalyticsSummary,
  ApiResponse,
  OpenTradeResponse,
  PaperTrade,
  PortfolioSnapshot,
  Suggestion,
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

// ── T2 Scans ──────────────────────────────────────────────────────────────────

export function useT2Scans(days = 30) {
  return useSWR<T2Scan[]>(
    `/api/t2-scans/?days=${days}`,
    fetcher<T2Scan[]>,
  );
}

// ── Stocks ────────────────────────────────────────────────────────────────────

export function useStocks(tier?: string) {
  const url = tier ? `/api/stocks/?tier=${tier}` : "/api/stocks/";
  return useSWR<{ symbol: string; name: string; tier: string }[]>(
    url,
    fetcher,
  );
}
