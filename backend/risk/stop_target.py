from agents.models import TradeTier
from config import settings


def compute_stop_target(entry_price: float, tier: TradeTier) -> tuple[float, float]:
    """Return (stop_loss, target_price) for a long position."""
    if tier == TradeTier.T1:
        stop = entry_price * (1 - settings.t1_stop_loss_pct)
        target = entry_price * (1 + settings.t1_target_pct)
    else:
        stop = entry_price * (1 - settings.t2_stop_loss_pct)
        target = entry_price * (1 + settings.t2_target_pct)
    return round(stop, 4), round(target, 4)


def risk_reward_ratio(entry: float, stop: float, target: float) -> float:
    risk = entry - stop
    reward = target - entry
    return round(reward / risk, 2) if risk > 0 else 0.0
