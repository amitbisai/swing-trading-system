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


def test_position_sizing_respects_capital_limit():
    shares = compute_position_size(
        capital=Decimal("10000"),
        entry_price=Decimal("100"),
        stop_loss=Decimal("98"),
        max_capital_pct=0.02,
    )
    assert shares > 0
    cost = shares * Decimal("100")
    assert cost <= Decimal("10000") * Decimal("0.02")


def test_position_sizing_zero_on_bad_stop():
    shares = compute_position_size(
        capital=Decimal("10000"),
        entry_price=Decimal("100"),
        stop_loss=Decimal("105"),  # stop above entry — invalid
    )
    assert shares == 0
