from decimal import Decimal


def compute_position_size(
    capital: Decimal,
    entry_price: Decimal,
    stop_loss: Decimal,
    max_capital_pct: float = 0.02,
) -> int:
    """
    Return number of shares to buy.
    Caps at max_capital_pct of total capital AND limits risk to max_capital_pct.
    Both constraints use numeric(12,4)-safe Decimal arithmetic.
    """
    risk_per_share = entry_price - stop_loss
    if risk_per_share <= 0:
        return 0

    max_capital_alloc = capital * Decimal(str(max_capital_pct))

    # Risk-based sizing: how many shares before max loss = max_capital_alloc?
    shares_by_risk = int(max_capital_alloc / risk_per_share)

    # Capital-based ceiling: never invest more than max_capital_alloc
    shares_by_capital = int(max_capital_alloc / entry_price)

    return min(shares_by_risk, shares_by_capital)
