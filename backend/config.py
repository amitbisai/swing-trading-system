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

    # Market data (Alpha Vantage free tier: 25 calls/day)
    alpha_vantage_api_key: str = ""

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
    t1_stop_loss_pct: float = 0.02
    t1_target_pct: float = 0.04
    t2_stop_loss_pct: float = 0.04
    t2_target_pct: float = 0.10
    max_capital_per_trade_pct: float = 0.02
    max_open_positions: int = 8

    # Paper trading
    initial_capital: Decimal = Decimal("100000.0000")

    # LLM
    llm_model: str = "claude-sonnet-4-6"

    def get_cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
