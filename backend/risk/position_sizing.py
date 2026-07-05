from decimal import Decimal

from config import settings


def compute_position_size(
    capital: Decimal,
    entry_price: Decimal,
    stop_loss: Decimal,
    risk_pct: float | None = None,
    max_position_pct: float | None = None,
    available_cash: Decimal | None = None,
) -> int:
    """
    Risk-based position sizing.

    Number of shares is chosen so that a stop-out loses at most
    ``risk_pct`` of total capital (default settings.risk_per_trade_pct, 1%),
    subject to two ceilings:

      * position value <= ``max_position_pct`` of capital
        (default settings.max_position_pct, 15%)
      * position value <= ``available_cash`` when provided
        (so the paper account can never go cash-negative)

    Works for LONG and SHORT (risk per share is the absolute entry-stop
    distance). Returns 0 when the stop equals the entry or inputs are invalid.
    """
    if entry_price <= 0 or capital <= 0:
        return 0

    risk_per_share = abs(entry_price - stop_loss)
    if risk_per_share <= 0:
        return 0

    risk_pct = risk_pct if risk_pct is not None else settings.risk_per_trade_pct
    max_position_pct = (
        max_position_pct if max_position_pct is not None else settings.max_position_pct
    )

    # Risk budget: shares such that (entry − stop) × shares = risk_pct × capital
    risk_budget = capital * Decimal(str(risk_pct))
    shares_by_risk = int(risk_budget / risk_per_share)

    # Position-value ceiling
    max_position_value = capital * Decimal(str(max_position_pct))
    if available_cash is not None:
        max_position_value = min(max_position_value, available_cash)
    shares_by_value = int(max_position_value / entry_price)

    return max(0, min(shares_by_risk, shares_by_value))
