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

export interface AnalyticsSummary {
  as_of: string;
  capital: CapitalStats;
  trades: TradeStats;
  suggestions: SuggestionStats;
}

export interface OpenTradeResponse {
  trade: PaperTrade;
  auto_sized: boolean;
}

export interface ApiResponse<T> {
  data: T;
  error: string | null;
  timestamp: string;
}
