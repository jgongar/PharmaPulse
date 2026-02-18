"""What-If lever application: creates a modified copy of snapshot parameters."""

import json
from .. import models


def apply_whatif_levers(snapshot: models.Snapshot, levers: models.WhatIfLevers | None = None) -> dict:
    """Return a dict of snapshot-like parameters with what-if levers applied.

    Does NOT modify the snapshot in the database.
    """
    if levers is None:
        levers = snapshot.whatif_levers

    params = {
        "peak_sales_usd_m": snapshot.peak_sales_usd_m,
        "launch_year": snapshot.launch_year,
        "patent_expiry_year": snapshot.patent_expiry_year,
        "time_to_peak_years": snapshot.time_to_peak_years,
        "generic_erosion_pct": snapshot.generic_erosion_pct,
        "cogs_pct": snapshot.cogs_pct,
        "sga_pct": snapshot.sga_pct,
        "tax_rate": snapshot.tax_rate,
        "discount_rate": snapshot.discount_rate,
        "uptake_curve": snapshot.uptake_curve,
    }

    phase_dicts = [
        {
            "phase_name": pi.phase_name,
            "probability_of_success": pi.probability_of_success,
            "duration_years": pi.duration_years,
            "start_year": pi.start_year,
        }
        for pi in snapshot.phase_inputs
    ]

    if levers:
        params["peak_sales_usd_m"] *= levers.peak_sales_multiplier
        params["launch_year"] += levers.launch_delay_years
        params["patent_expiry_year"] += levers.launch_delay_years

        if levers.discount_rate_override is not None:
            params["discount_rate"] = levers.discount_rate_override
        if levers.cogs_pct_override is not None:
            params["cogs_pct"] = levers.cogs_pct_override
        if levers.sga_pct_override is not None:
            params["sga_pct"] = levers.sga_pct_override

        if levers.pos_override:
            overrides = levers.pos_override
            if isinstance(overrides, str):
                overrides = json.loads(overrides)
            for pd in phase_dicts:
                if pd["phase_name"] in overrides:
                    pd["probability_of_success"] = overrides[pd["phase_name"]]

    params["phase_inputs"] = phase_dicts
    return params
