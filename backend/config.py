from decimal import Decimal
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Always load .env from the repo root, regardless of working directory
_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # Database
    database_url: str = ""
    supabase_url: str = ""
    supabase_service_key: str = ""

    # AI
    anthropic_api_key: str = ""

    # Market data
    alpha_vantage_api_key: str = ""  # Alpha Vantage free tier: 25 calls/day (legacy)
    finnhub_api_key: str = ""        # Finnhub free tier: 60 calls/min — used for batch sentiment

    # Task queue
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # CORS — comma-separated string in .env: CORS_ORIGINS=http://localhost:3000,https://myapp.com
    cors_origins: str = "http://localhost:3000"

    # Risk: T1 = Tier 1 large-cap, T2 = Tier 2 momentum
    # Fixed percentages are the FALLBACK used only when ATR is unavailable.
    t1_stop_loss_pct: float = 0.02
    t1_target_pct: float = 0.04
    t2_stop_loss_pct: float = 0.04
    t2_target_pct: float = 0.10
    max_capital_per_trade_pct: float = 0.02
    # 0 = unlimited open positions
    max_open_positions: int = 0

    # Max NEW trades opened per day, ranked by confidence (top-N discipline —
    # 20-25 daily signals mostly measure market beta; taking only the best few
    # is what differentiates). Overridable at runtime via the app_settings
    # table (set from the Analytics page). 0 = unlimited.
    max_entries_per_day: int = 5

    # ATR-based stops/targets (primary sizing when ATR is available)
    atr_stop_mult: float = 1.5     # stop  = entry ∓ 1.5 × ATR(14)
    atr_target_mult: float = 3.0   # target = entry ± 3.0 × ATR(14)  (2:1 reward:risk)

    # Time-based exit: close any open trade after this many calendar days
    # (~10 trading days — matches the 3–14 day swing thesis). 0 disables.
    max_holding_days: int = 14

    # Dynamic exits (nightly trade manager): when an open position is in
    # profit and its trend is intact, extend the target and ratchet the stop.
    dynamic_exits_enabled: bool = True
    trail_stop_atr_mult: float = 3.0      # chandelier: highest close − 3 × ATR
    target_extend_atr_mult: float = 2.0   # extended target = close + 2 × ATR
    breakeven_after_r: float = 1.0        # move stop to entry once up ≥ 1R

    # Market regime filter: suppress new entries when SPY < its 200-day SMA
    regime_filter_enabled: bool = True
    regime_symbol: str = "SPY"

    # Auto-entry mode:
    #   "intraday" — trades open next market morning at live prices via the
    #                hourly intraday job (realistic; requires that cron service)
    #   "nightly"  — trades open immediately after the nightly agents run at
    #                the suggestion's EOD entry price (fallback if the hourly
    #                job isn't deployed)
    auto_entry_mode: str = "intraday"

    # Paper trading
    initial_capital: Decimal = Decimal("100000.0000")

    # LLM
    llm_model: str = "claude-sonnet-4-6"

    def get_cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
