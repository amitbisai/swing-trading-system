from agents.models import Direction, TradeTier
from config import settings


def compute_stop_target(
    entry_price: float,
    tier: TradeTier,
    direction: Direction = Direction.LONG,
) -> tuple[float, float]:
    """
    Return (stop_loss, target_price) for a position.

    LONG : stop below entry, target above entry.
    SHORT: stop above entry, target below entry.
    """
    if tier == TradeTier.T1:
        stop_pct   = settings.t1_stop_loss_pct
        target_pct = settings.t1_target_pct
    else:
        stop_pct   = settings.t2_stop_loss_pct
        target_pct = settings.t2_target_pct

    if direction == Direction.SHORT:
        stop   = entry_price * (1 + stop_pct)
        target = entry_price * (1 - target_pct)
    else:
        stop   = entry_price * (1 - stop_pct)
        target = entry_price * (1 + target_pct)

    return round(stop, 4), round(target, 4)


def risk_reward_ratio(entry: float, stop: float, target: float) -> float:
    risk   = abs(entry - stop)
    reward = abs(target - entry)
    return round(reward / risk, 2) if risk > 0 else 0.0
