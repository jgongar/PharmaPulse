"""Revenue uptake curves and LOE erosion."""

import math


def linear_uptake(years_since_launch: int, time_to_peak: int, peak_sales: float) -> float:
    """Linear ramp to peak sales."""
    if years_since_launch < 0:
        return 0.0
    if years_since_launch >= time_to_peak:
        return peak_sales
    return peak_sales * (years_since_launch / time_to_peak)


def logistic_uptake(years_since_launch: int, time_to_peak: int, peak_sales: float) -> float:
    """Logistic (S-curve) ramp to peak sales."""
    if years_since_launch < 0:
        return 0.0
    # Logistic curve centered at time_to_peak/2, steepness k=6/time_to_peak
    midpoint = time_to_peak / 2.0
    k = 6.0 / max(time_to_peak, 1)
    fraction = 1.0 / (1.0 + math.exp(-k * (years_since_launch - midpoint)))
    return peak_sales * fraction


def apply_loe_erosion(base_sales: float, years_since_expiry: int, erosion_pct: float) -> float:
    """Apply loss-of-exclusivity erosion after patent expiry.

    erosion_pct is the fraction of sales lost in the first year post-expiry.
    Subsequent years erode further.
    """
    if years_since_expiry < 0:
        return base_sales
    if years_since_expiry == 0:
        return base_sales * (1.0 - erosion_pct)
    # After first year of erosion, sales drop to near zero
    remaining = base_sales * (1.0 - erosion_pct) * (0.5 ** years_since_expiry)
    return max(remaining, 0.0)


def get_revenue(year: int, launch_year: int, patent_expiry_year: int,
                peak_sales: float, time_to_peak: int,
                generic_erosion_pct: float, uptake_curve: str = "linear") -> float:
    """Calculate gross revenue for a given year."""
    years_since_launch = year - launch_year

    if years_since_launch < 0:
        return 0.0

    if uptake_curve == "logistic":
        base = logistic_uptake(years_since_launch, time_to_peak, peak_sales)
    else:
        base = linear_uptake(years_since_launch, time_to_peak, peak_sales)

    years_since_expiry = year - patent_expiry_year
    return apply_loe_erosion(base, years_since_expiry, generic_erosion_pct)
