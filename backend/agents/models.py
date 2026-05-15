from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class TradeTier(str, Enum):
    T1 = "T1"  # large-cap liquid (S&P 500)
    T2 = "T2"  # momentum (volume > 3× 20d avg)


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class AgentInputBundle(BaseModel):
    """Passed to every sub-agent; carries scanner context so agents skip redundant fetches."""
    symbol: str
    tier: TradeTier
    as_of_date: date
    # Populated by the scanner — used by synthesizer so it doesn't re-fetch price
    entry_price: float = 0.0
    avg_volume_20d: float = 0.0
    volume_ratio: float = 0.0


class ScannerOutput(BaseModel):
    symbol: str
    tier: TradeTier
    avg_volume_20d: float
    volume_ratio: float   # today_vol / avg_volume_20d
    price: float          # latest close price
    market_cap: float | None = None


class TAOutput(BaseModel):
    symbol: str
    rsi_14: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    atr_14: float | None = None
    sma_20: float | None = None
    sma_50: float | None = None
    bb_upper: float | None = None
    bb_lower: float | None = None
    score: int = Field(ge=0, le=100)


class SentimentOutput(BaseModel):
    symbol: str
    headline_sentiment: float | None = None  # -1.0 to 1.0
    news_count_24h: int = 0
    score: int = Field(ge=0, le=100)


class PatternOutput(BaseModel):
    symbol: str
    patterns_detected: list[str] = []
    support_level: float | None = None
    resistance_level: float | None = None
    score: int = Field(ge=0, le=100)


class SynthesisOutput(BaseModel):
    symbol: str
    tier: TradeTier
    direction: Direction
    confidence_score: int = Field(ge=0, le=100)
    entry_price: float
    stop_loss: float
    target_price: float
    rationale: str
    ta_score: int = Field(ge=0, le=100)
    sentiment_score: int = Field(ge=0, le=100)
    pattern_score: int = Field(ge=0, le=100)
    as_of_date: date
