"""
PharmaPulse — Discounting Module

Mid-year convention discounting for NPV calculations.

Formula:
    PV = CF / (1 + WACC)^((year - valuation_year) - 0.5)

The -0.5 implements mid-year convention: cashflows are assumed to occur
at the midpoint of each calendar year rather than at year-end.
"""

import math


def discount_cashflow(
    cashflow: float,
    year: int,
    valuation_year: int,
    wacc: float,
) -> float:
    """
    Discounts a single cashflow using mid-year convention.

    Args:
        cashflow: The undiscounted cashflow amount (EUR mm).
        year: The calendar year of the cashflow.
        valuation_year: The base year for discounting.
        wacc: Weighted average cost of capital (e.g. 0.085 for 8.5%).

    Returns:
        Present value of the cashflow in EUR mm.
    """
    if cashflow == 0:
        return 0.0

    # Mid-year convention: cashflow occurs at middle of year
    # Year 0 (valuation_year) → exponent = -0.5
    # Year 1 → exponent = 0.5
    # Year 2 → exponent = 1.5
    exponent = (year - valuation_year) - 0.5

    if exponent < 0:
        # Cashflow in or before valuation year — no discounting needed
        # (but still apply mid-year for partial year)
        pass

    discount_factor = (1 + wacc) ** exponent
    return cashflow / discount_factor


def discount_factor_at(year: int, valuation_year: int, wacc: float) -> float:
    """
    Returns the discount factor for a given year (mid-year convention).
    
    PV = CF × discount_factor
    """
    exponent = (year - valuation_year) - 0.5
    return 1.0 / ((1 + wacc) ** exponent)


