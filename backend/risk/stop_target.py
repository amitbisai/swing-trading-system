from agents.models import Direction, TradeTier
from config import settings


def compute_stop_target(
    entry_price: float,
    tier: TradeTier,
    direction: Direction = Direction.LONG,
    atr: float | None = None,
) -> tuple[float, float]:
    """
    Return (stop_loss, target_price) for a position.

    Volatility-aware: when *atr* (14-day Average True Range) is available the
    stop is placed at ``atr_stop_mult × ATR`` and the target at
    ``atr_target_mult × ATR`` from entry, so noisy stocks get wider stops and
    quiet stocks tighter ones (fixed-percentage stops get shaken out by normal
    daily range on volatile names).

    The ATR distances are clamped to sane bounds relative to entry price so a
    bad/stale ATR can't produce a 40% stop or a 0.1% stop.

    Falls back to the legacy fixed percentages when ATR is unavailable.

    LONG : stop below entry, target above entry.
    SHORT: stop above entry, target below entry.
    """
    if tier == TradeTier.T1:
        fallback_stop_pct   = settings.t1_stop_loss_pct
        fallback_target_pct = settings.t1_target_pct
    else:
        fallback_stop_pct   = settings.t2_stop_loss_pct
        fallback_target_pct = settings.t2_target_pct

    if atr is not None and atr > 0 and entry_price > 0:
        stop_dist   = atr * settings.atr_stop_mult
        target_dist = atr * settings.atr_target_mult

        # Clamp stop distance to [1%, 10%] of entry; keep target at the same
        # reward:risk ratio if the stop was clamped.
        min_stop = entry_price * 0.01
        max_stop = entry_price * 0.10
        clamped = min(max(stop_dist, min_stop), max_stop)
        if clamped != stop_dist:
            target_dist = clamped * (settings.atr_target_mult / settings.atr_stop_mult)
            stop_dist = clamped
    else:
        stop_dist   = entry_price * fallback_stop_pct
        target_dist = entry_price * fallback_target_pct

    if direction == Direction.SHORT:
        stop   = entry_price + stop_dist
        target = entry_price - target_dist
    else:
        stop   = entry_price - stop_dist
        target = entry_price + target_dist

    return round(stop, 4), round(target, 4)


def risk_reward_ratio(entry: float, stop: float, target: float) -> float:
    risk   = abs(entry - stop)
    reward = abs(target - entry)
    return round(reward / risk, 2) if risk > 0 else 0.0
