from datetime import date

import pytest

from agents.models import AgentInputBundle, TradeTier
from agents.ta_agent import run_ta
from agents.pattern import run_pattern
from agents.sentiment import run_sentiment


@pytest.mark.asyncio
async def test_ta_agent_returns_valid_output():
    bundle = AgentInputBundle(symbol="AAPL", tier=TradeTier.T1, as_of_date=date.today())
    result = await run_ta(bundle)
    assert result.symbol == "AAPL"
    assert 0 <= result.score <= 100


@pytest.mark.asyncio
async def test_pattern_agent_returns_valid_output():
    bundle = AgentInputBundle(symbol="MSFT", tier=TradeTier.T1, as_of_date=date.today())
    result = await run_pattern(bundle)
    assert result.symbol == "MSFT"
    assert 0 <= result.score <= 100
    assert isinstance(result.patterns_detected, list)


@pytest.mark.asyncio
async def test_sentiment_agent_returns_valid_output():
    bundle = AgentInputBundle(symbol="GOOGL", tier=TradeTier.T1, as_of_date=date.today())
    result = await run_sentiment(bundle)
    assert result.symbol == "GOOGL"
    assert 0 <= result.score <= 100
