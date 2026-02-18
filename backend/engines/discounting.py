"""Mid-year discounting utilities."""


def mid_year_discount_factor(year: int, base_year: int, discount_rate: float) -> float:
    """Calculate mid-year discount factor.

    Uses mid-year convention: cashflows are assumed to occur at the
    middle of each year, so the exponent is (year - base_year + 0.5).
    """
    t = year - base_year + 0.5
    if t < 0:
        t = 0
    return 1.0 / ((1.0 + discount_rate) ** t)
