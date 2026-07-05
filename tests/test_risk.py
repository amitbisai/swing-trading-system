from decimal import Decimal

import pytest

from agents.models import TradeTier
from risk.stop_target import compute_stop_target, risk_reward_ratio
from risk.position_sizing import compute_position_size


def test_t1_stop_target():
    stop, target = compute_stop_target(100.0, TradeTier.T1)
    assert stop == pytest.approx(98.0, rel=1e-4)   # 2% stop
    assert target == pytest.approx(104.0, rel=1e-4)  # 4% target


def test_t2_stop_target():
    stop, target = compute_stop_target(100.0, TradeTier.T2)
    assert stop == pytest.approx(96.0, rel=1e-4)   # 4% stop
    assert target == pytest.approx(110.0, rel=1e-4)  # 10% target


def test_t1_risk_reward_is_2():
    stop, target = compute_stop_target(100.0, TradeTier.T1)
    rr = risk_reward_ratio(100.0, stop, target)
    assert rr == pytest.approx(2.0, rel=1e-2)


def test_t2_risk_reward_is_2_point_5():
    stop, target = compute_stop_target(100.0, TradeTier.T2)
    rr = risk_reward_ratio(100.0, stop, target)
    assert rr == pytest.approx(2.5, rel=1e-2)


def test_position_sizing_risk_based():
    # capital 100k, 1% risk = $1,000 budget, $2 risk/share → 500 shares by risk,
    # but 15% position cap = $15,000 / $100 = 150 shares → 150 wins
    shares = compute_position_size(
        capital=Decimal("100000"),
        entry_price=Decimal("100"),
        stop_loss=Decimal("98"),
        risk_pct=0.01,
        max_position_pct=0.15,
    )
    assert shares == 150
    # risk if stopped out never exceeds the 1% budget
    assert shares * Decimal("2") <= Decimal("100000") * Decimal("0.01") * 2  # capped below budget


def test_position_sizing_risk_budget_binds_on_wide_stop():
    # wide stop ($10 risk/share): 1% of 100k = $1,000 → 100 shares by risk;
    # position cap 15% = 150 shares → risk constraint wins
    shares = compute_position_size(
        capital=Decimal("100000"),
        entry_price=Decimal("100"),
        stop_loss=Decimal("90"),
        risk_pct=0.01,
        max_position_pct=0.15,
    )
    assert shares == 100
    assert shares * Decimal("10") == Decimal("1000")


def test_position_sizing_capped_by_available_cash():
    shares = compute_position_size(
        capital=Decimal("100000"),
        entry_price=Decimal("100"),
        stop_loss=Decimal("98"),
        risk_pct=0.01,
        max_position_pct=0.15,
        available_cash=Decimal("5000"),
    )
    assert shares == 50   # $5,000 cash / $100 — cash is the binding ceiling


def test_position_sizing_short_direction():
    # SHORT: stop above entry — |entry − stop| is the risk per share
    shares = compute_position_size(
        capital=Decimal("100000"),
        entry_price=Decimal("100"),
        stop_loss=Decimal("104"),
        risk_pct=0.01,
        max_position_pct=0.15,
    )
    assert shares > 0


def test_position_sizing_zero_on_zero_risk():
    shares = compute_position_size(
        capital=Decimal("10000"),
        entry_price=Decimal("100"),
        stop_loss=Decimal("100"),  # stop == entry — undefined risk
    )
    assert shares == 0
