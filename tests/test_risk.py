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


# ── Market pulse → entries allowed ────────────────────────────────────────────

def test_entries_allowed_scales_with_pulse():
    from risk.market_pulse import entries_allowed

    assert entries_allowed(5, 80) == 5   # strong market: full allocation
    assert entries_allowed(5, 65) == 3   # uptrend: 60%
    assert entries_allowed(5, 50) == 2   # neutral: 40%
    assert entries_allowed(5, 35) == 1   # weak: 20%, at least 1
    assert entries_allowed(5, 20) == 0   # avoid: sit out


def test_entries_allowed_unlimited_cap_gates_on_off():
    from risk.market_pulse import entries_allowed

    assert entries_allowed(0, 80) == 10_000   # uncapped, healthy market
    assert entries_allowed(0, 20) == 0        # uncapped but weak market → sit out


# ── Capital pacing ────────────────────────────────────────────────────────────

def test_per_trade_cash_cap_splits_daily_budget():
    from datetime import date

    from paper_trading.engine import EntryPlan, per_trade_cash_cap

    plan = EntryPlan(
        as_of=date.today(),
        capital=Decimal("100000"),
        cash=Decimal("100000"),
        entered_today=0,
        deployed_today=Decimal("0"),
        allowed_today=5,
        pulse_score=80,
        pulse_label="STRONG",
    )
    # daily budget 25% = 25,000 across 5 entries → 5,000 each
    assert per_trade_cash_cap(plan, opened=0, spent=Decimal("0")) == Decimal("5000")
    # after 2 entries costing 10k, 3 remain sharing 15k → 5,000 each
    assert per_trade_cash_cap(plan, opened=2, spent=Decimal("10000")) == Decimal("5000")
    # all entries used → 0
    assert per_trade_cash_cap(plan, opened=5, spent=Decimal("25000")) == Decimal("0")


def test_per_trade_cash_cap_respects_reserve():
    from datetime import date

    from paper_trading.engine import EntryPlan, per_trade_cash_cap

    plan = EntryPlan(
        as_of=date.today(),
        capital=Decimal("100000"),
        cash=Decimal("12000"),        # only 12k cash left
        entered_today=0,
        deployed_today=Decimal("0"),
        allowed_today=1,
        pulse_score=80,
        pulse_label="STRONG",
    )
    # reserve floor 10% = 10,000 → only 2,000 usable despite 25k daily budget
    assert per_trade_cash_cap(plan, opened=0, spent=Decimal("0")) == Decimal("2000")
