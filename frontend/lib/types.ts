export type TradeTier = "T1" | "T2";
export type Direction = "LONG" | "SHORT";
export type TradeStatus = "open" | "closed" | "all";

export interface Suggestion {
  id: number;
  symbol: string;
  tier: TradeTier;
  direction: Direction;
  confidence_score: number;
  entry_price: string;
  stop_loss: string;
  target_price: string;
  risk_reward: number;
  rationale: string;
  as_of_date: string;
  ta_score: number;
  sentiment_score: number;
  pattern_score: number;
  is_active: boolean;
}

export interface PaperTrade {
  id: number;
  suggestion_id: number;
  symbol: string;
  direction: Direction;
  entry_date: string;
  entry_price: string;
  shares: number;
  capital_at_risk: string;
  stop_loss: string;
  target_price: string;
  exit_date: string | null;
  exit_price: string | null;
  exit_reason: string | null;
  realized_pnl: string | null;
  is_open: boolean;
}

export interface PortfolioSnapshot {
  snapshot_date: string;
  total_capital: string;
  cash_balance: string;
  invested_capital: string;
  unrealized_pnl: string;
  realized_pnl_today: string;
  cumulative_realized_pnl: string;
  open_positions: number;
  initial_capital: string | null;
}

export interface PersistentPick {
  symbol: string;
  total_days: number;
  suggestion_days: number;
  t2_scan_days: number;
  window_days: number;
  last_seen: string;
  tier: TradeTier | null;
  latest_confidence: number | null;
  latest_direction: Direction | null;
}

export interface CapitalStats {
  initial_capital: string;
  current_capital: string;
  total_return_pct: number;
  unrealized_pnl: string;
  cumulative_realized_pnl: string;
}

export interface TradeStats {
  open_trades: number;
  closed_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate_pct: number;
  total_realized_pnl: string;
  avg_realized_pnl: string;
  best_trade_pnl: string | null;
  worst_trade_pnl: string | null;
}

export interface SuggestionStats {
  total_suggestions: number;
  suggestions_today: number;
  avg_confidence: number;
}

export interface TierPerformance {
  tier: string;
  closed_trades: number;
  winning_trades: number;
  win_rate_pct: number;
  total_realized_pnl: string;
}

export interface AnalyticsSummary {
  as_of: string;
  capital: CapitalStats;
  trades: TradeStats;
  suggestions: SuggestionStats;
  tiers: TierPerformance[];
}

export interface OpenTradeResponse {
  trade: PaperTrade;
  auto_sized: boolean;
}

export type T2SignalTier = "A" | "B" | "C";
export type NewsVerdict = "SUPPORTS" | "NEUTRAL" | "CONTRADICTS";

export interface T2Scan {
  id: number;
  symbol: string;
  scan_date: string;
  signal_tier: T2SignalTier;
  t2_score: number;
  price: string;
  market_cap: string | null;
  rvol: number;
  avg_volume_30d: string | null;
  revenue_growth: number | null;
  earnings_growth: number | null;
  pct_below_52w_high: number | null;
  float_shares: string | null;
  short_ratio: number | null;
  sector: string | null;
  industry: string | null;
  risk_flags: string[];
  signal_summary: string | null;
  catalyst_hint: string | null;
  news_summary: string | null;
  news_verdict: NewsVerdict | null;
}

export interface T1Scan {
  id: number;
  symbol: string;
  scan_date: string;
  price: string;
  rsi_14: number | null;
  macd_hist: number | null;
  sma_20: string | null;
  sma_50: string | null;
  atr_14: number | null;
  bb_upper: string | null;
  bb_lower: string | null;
  rvol: number | null;
  avg_volume_20d: string | null;
  support_level: string | null;
  resistance_level: string | null;
  patterns_detected: string[];
  ta_score: number;
  pattern_score: number;
  sentiment_score: number;
  bullish_confidence: number;
  bearish_confidence: number;
  signal_direction: "LONG" | "SHORT";
  made_signal: boolean;
  sector: string | null;
}

export interface ApiResponse<T> {
  data: T;
  error: string | null;
  timestamp: string;
}

// ── Financial Analysis ────────────────────────────────────────────────────────

export interface EarningsEvent {
  date_str: string | null;
  days_until: number | null;
}

export interface QuarterlyResult {
  period: string;           // YYYY-MM-DD
  revenue: number | null;
  gross_profit: number | null;
  net_income: number | null;
}

export type TradeReadiness = "GO" | "CAUTION" | "AVOID";

export interface FinancialSummary {
  symbol: string;
  name: string;
  sector: string;
  industry: string;
  price: number;
  market_cap: number | null;
  pe_ratio: number | null;
  forward_pe: number | null;
  revenue_growth_yoy: number | null;
  net_margin: number | null;
  debt_to_equity: number | null;
  free_cash_flow: number | null;
  analyst_recommendation: string | null;
  analyst_target_price: number | null;
  next_earnings: EarningsEvent | null;
  quarterly_results: QuarterlyResult[];
  trade_readiness: TradeReadiness;
  risk_flags: string[];
  claude_view: string;
  fetched_at: string;
}
