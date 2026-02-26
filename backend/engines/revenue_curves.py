"""
PharmaPulse — Revenue Curve Module

Computes annual revenue for a commercial row using the 3-phase uptake curve:
  1. RAMP-UP (Launch → Launch + time_to_peak): logistic or linear
  2. PLATEAU (after ramp-up, for plateau_years): uptake = 1.0
  3. POST-LOE EROSION (after LOE): cliff + linear decline to floor

Handles fractional launch and LOE years by integrating within calendar years.

Spec reference: Section 5.8
"""

import math
from typing import Optional


def _logistic_uptake(tau: float, k: float, midpoint: float) -> float:
    """
    Logistic uptake value for normalized time tau ∈ [0, 1].
    
    uptake(tau) = 1 / (1 + exp(-k * (tau - midpoint)))
    
    Clipped to [0, 1].
    """
    raw = 1.0 / (1.0 + math.exp(-k * (tau - midpoint)))
    return max(0.0, min(1.0, raw))


def _linear_uptake(tau: float) -> float:
    """
    Linear uptake value for normalized time tau ∈ [0, 1].
    """
    return max(0.0, min(1.0, tau))


def _uptake_at_time(
    t: float,
    launch_date: float,
    time_to_peak: float,
    plateau_years: float,
    loe_year: float,
    loe_cliff_rate: float,
    erosion_floor_pct: float,
    years_to_erosion_floor: float,
    curve_type: str = "logistic",
    logistic_k: float = 5.5,
    logistic_midpoint: float = 0.5,
) -> float:
    """
    Returns the uptake multiplier (0–1+) at continuous time t.
    
    Phases:
    1. Before launch: 0
    2. Ramp-up (launch → launch + time_to_peak): logistic or linear from 0 to 1
    3. Plateau (peak → peak + plateau_years, capped at LOE): 1.0
    4. LOE cliff: immediate drop to (1 - loe_cliff_rate) → stays at that level
    5. Post-LOE erosion: linear decline from (1 - loe_cliff_rate) to erosion_floor_pct
    6. Floor: stays at erosion_floor_pct
    """
    if t < launch_date:
        return 0.0

    peak_date = launch_date + time_to_peak
    # Note: plateau ends at LOE (or peak_date + plateau_years, whichever is earlier)
    plateau_end = min(peak_date + plateau_years, loe_year)

    # Phase 1: Ramp-up
    if t < peak_date:
        tau = (t - launch_date) / time_to_peak if time_to_peak > 0 else 1.0
        tau = min(1.0, tau)
        if curve_type == "logistic":
            return _logistic_uptake(tau, logistic_k, logistic_midpoint)
        else:
            return _linear_uptake(tau)

    # Phase 2: Plateau (before LOE)
    if t < loe_year:
        return 1.0

    # Phase 3: LOE cliff + erosion
    # At LOE: revenue drops instantly by loe_cliff_rate
    # e.g., loe_cliff_rate=0.85 means revenue drops TO 85% of peak → post_cliff = 0.85
    # Wait — spec says "loe_cliff_rate (e.g., 0.85 = revenue drops to 85%)"
    # So post-cliff uptake = loe_cliff_rate (NOT 1 - loe_cliff_rate)
    # Actually, re-reading: "At LOE: apply loe_cliff_rate (e.g., 0.85 = revenue drops to 85%)"
    # This means the revenue DROPS TO 85% of peak. So post-cliff multiplier = 0.85?
    # No — "drops to 85%" is ambiguous. But the field is "loe_cliff_rate" = 0.85.
    # In the seed data, loe_cliff_rate=0.85 with erosion_floor=0.50.
    # Interpretation: revenue drops BY loe_cliff_rate at LOE.
    # So post-cliff = 1.0 - loe_cliff_rate? That would give 0.15 which seems too low.
    # 
    # Better interpretation from spec: "revenue drops to 85%" means the remaining
    # fraction after cliff is (1 - loe_cliff_rate) — wait that gives 0.15.
    # 
    # Most pharma models: cliff_rate = fraction LOST. E.g. 0.85 means 85% lost → 15% remains.
    # But the seed data has erosion_floor=0.50 which would be higher than post-cliff.
    #
    # Actually rereading the spec: "loe_cliff_rate (e.g., 0.85 = revenue drops to 85%)"
    # → "drops TO 85%" means remaining = 0.85. Then erosion from 0.85 down to 0.50 floor.
    # This makes sense with the seed data.

    post_cliff_level = loe_cliff_rate  # Revenue drops TO this fraction of peak
    erosion_start = loe_year
    erosion_end = loe_year + years_to_erosion_floor

    if years_to_erosion_floor <= 0 or t >= erosion_end:
        return erosion_floor_pct

    # Linear decline from post_cliff_level to erosion_floor_pct
    time_into_erosion = t - erosion_start
    fraction = time_into_erosion / years_to_erosion_floor
    fraction = min(1.0, fraction)

    uptake = post_cliff_level + (erosion_floor_pct - post_cliff_level) * fraction
    return uptake


def compute_annual_revenue(
    peak_revenue: float,
    launch_date: float,
    time_to_peak: float,
    plateau_years: float,
    loe_year: float,
    loe_cliff_rate: float,
    erosion_floor_pct: float,
    years_to_erosion_floor: float,
    revenue_curve_type: str,
    logistic_k: float,
    logistic_midpoint: float,
    year: int,
    num_integration_steps: int = 12,
) -> float:
    """
    Computes annual revenue for a single calendar year by numerically
    integrating the uptake curve over that year.

    Args:
        peak_revenue: Peak annual revenue in EUR mm at full uptake.
        launch_date: Fractional year of commercial launch (e.g. 2029.75).
        time_to_peak: Years from launch to peak sales.
        plateau_years: Years of plateau at peak after ramp-up.
        loe_year: Fractional year of loss of exclusivity.
        loe_cliff_rate: Fraction of peak revenue REMAINING after LOE cliff.
        erosion_floor_pct: Final erosion floor as fraction of peak.
        years_to_erosion_floor: Years of post-cliff linear erosion.
        revenue_curve_type: "logistic" or "linear".
        logistic_k: Steepness parameter for logistic curve.
        logistic_midpoint: Midpoint parameter for logistic curve.
        year: Calendar year to calculate revenue for.
        num_integration_steps: Number of sub-intervals for numerical integration.

    Returns:
        Annual revenue in EUR mm for the given calendar year.
    """
    if peak_revenue <= 0:
        return 0.0

    year_start = float(year)
    year_end = float(year + 1)

    # Quick check: if entire year is before launch, revenue = 0
    if year_end <= launch_date:
        return 0.0

    # Numerical integration using trapezoidal rule over the year
    # Subdivide the year into num_integration_steps intervals
    dt = 1.0 / num_integration_steps
    total_uptake = 0.0

    for i in range(num_integration_steps):
        t_left = year_start + i * dt
        t_right = year_start + (i + 1) * dt
        t_mid = (t_left + t_right) / 2.0

        # Trapezoidal: (f(left) + f(right)) / 2 × dt
        u_left = _uptake_at_time(
            t_left, launch_date, time_to_peak, plateau_years,
            loe_year, loe_cliff_rate, erosion_floor_pct,
            years_to_erosion_floor, revenue_curve_type,
            logistic_k, logistic_midpoint,
        )
        u_right = _uptake_at_time(
            t_right, launch_date, time_to_peak, plateau_years,
            loe_year, loe_cliff_rate, erosion_floor_pct,
            years_to_erosion_floor, revenue_curve_type,
            logistic_k, logistic_midpoint,
        )

        total_uptake += (u_left + u_right) / 2.0 * dt

    # total_uptake is the average uptake over the year (0 to 1)
    revenue = peak_revenue * total_uptake
    return revenue


def compute_peak_revenue_for_row(row) -> float:
    """
    Computes peak annual revenue (EUR mm) from a CommercialRow.
    
    Formula from Spec Section 5.7:
        EligiblePatients = patient_population × F1 × F2 × F3 × F4 × F5 × F6
        TreatedPatients = EligiblePatients × access_rate × market_share
        AnnualTreatments = TreatedPatients × units_per_treatment × treatments_per_year × compliance_rate
        SegmentPeakRevenue = AnnualTreatments × gross_price × gross_to_net_rate
        (Convert to millions: / 1,000,000)
    
    Args:
        row: CommercialRow ORM object or dict with the required fields.
    
    Returns:
        Peak revenue in EUR millions.
    """
    # Support both dict and ORM object access
    def _get(field, default=1.0):
        if isinstance(row, dict):
            return row.get(field, default)
        return getattr(row, field, default)

    patient_pop = _get("patient_population")
    f1 = _get("epi_f1", 1.0)
    f2 = _get("epi_f2", 1.0)
    f3 = _get("epi_f3", 1.0)
    f4 = _get("epi_f4", 1.0)
    f5 = _get("epi_f5", 1.0)
    f6 = _get("epi_f6", 1.0)
    access = _get("access_rate")
    market_share = _get("market_share")
    units = _get("units_per_treatment", 1.0)
    treatments = _get("treatments_per_year", 1.0)
    compliance = _get("compliance_rate", 1.0)
    price = _get("gross_price_per_treatment")
    gtn = _get("gross_to_net_price_rate", 1.0)

    eligible = patient_pop * f1 * f2 * f3 * f4 * f5 * f6
    treated = eligible * access * market_share
    annual_treatments = treated * units * treatments * compliance
    revenue_eur = annual_treatments * price * gtn

    # Convert to EUR millions
    revenue_mm = revenue_eur / 1_000_000.0
    return revenue_mm


