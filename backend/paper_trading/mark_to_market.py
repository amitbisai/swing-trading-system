"""
Mark-to-market helpers.

All prices are Decimal to match numeric(12,4) DB columns.
Direction is a plain string ("LONG" | "SHORT") so this module has
no dependency on agents.models (avoids a circular import).
"""

from __future__ import annotations

from decimal import Decimal


def check_exit(
    close_price: Decimal,
    stop_loss: Decimal,
    target_price: Decimal,
    direction: str,
) -> str | None:
    """
    Return the exit reason string if the trade should be closed today, else None.

    Exit reasons:
      "STOP_HIT"   — price moved against the position past the stop level
      "TARGET_HIT" — price reached the profit target

    For LONG:  stop is below entry, target is above entry.
    For SHORT: stop is above entry, target is below entry.
    """
    if direction == "LONG":
        if close_price <= stop_loss:
            return "STOP_HIT"
        if close_price >= target_price:
            return "TARGET_HIT"
    elif direction == "SHORT":
        if close_price >= stop_loss:
            return "STOP_HIT"
        if close_price <= target_price:
            return "TARGET_HIT"
    return None


def compute_unrealized_pnl(
    entry_price: Decimal,
    current_price: Decimal,
    shares: int,
    direction: str = "LONG",
) -> Decimal:
    if direction == "SHORT":
        return (entry_price - current_price) * Decimal(str(shares))
    return (current_price - entry_price) * Decimal(str(shares))


def compute_realized_pnl(
    entry_price: Decimal,
    exit_price: Decimal,
    shares: int,
    direction: str = "LONG",
) -> Decimal:
    if direction == "SHORT":
        return (entry_price - exit_price) * Decimal(str(shares))
    return (exit_price - entry_price) * Decimal(str(shares))


# ── Legacy aliases kept so any existing callers don't break ──────────────────

def hit_stop(current_price: Decimal, stop_loss: Decimal) -> bool:
    return current_price <= stop_loss


def hit_target(current_price: Decimal, target_price: Decimal) -> bool:
    return current_price >= target_price
