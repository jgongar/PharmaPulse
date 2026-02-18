"""Deterministic rNPV (risk-adjusted NPV) calculation engine."""

from sqlalchemy.orm import Session

from .. import crud, models
from .discounting import mid_year_discount_factor
from .risk_adjustment import cumulative_pos, total_pos
from .revenue_curves import get_revenue


def run_deterministic_npv(db: Session, snapshot: models.Snapshot) -> dict:
    """Run full deterministic rNPV for a snapshot. Saves cashflows to DB."""

    phase_dicts = [
        {
            "phase_name": pi.phase_name,
            "probability_of_success": pi.probability_of_success,
            "duration_years": pi.duration_years,
            "start_year": pi.start_year,
        }
        for pi in snapshot.phase_inputs
    ]
    rd_dict = {rc.year: rc.cost_usd_m for rc in snapshot.rd_costs}

    # Determine year range
    all_years = set()
    for pi in snapshot.phase_inputs:
        all_years.add(pi.start_year)
        all_years.add(pi.start_year + int(pi.duration_years))
    for rc in snapshot.rd_costs:
        all_years.add(rc.year)

    # Commercial years: launch to patent_expiry + 3 (allow some erosion tail)
    commercial_end = snapshot.patent_expiry_year + 3
    for y in range(snapshot.launch_year, commercial_end + 1):
        all_years.add(y)

    if not all_years:
        all_years = {2025}

    min_year = min(all_years)
    max_year = max(all_years)
    base_year = min_year

    cashflow_rows = []
    running_npv = 0.0

    for year in range(min_year, max_year + 1):
        # R&D cost (negative cashflow)
        rd_cost = rd_dict.get(year, 0.0)

        # Commercial revenue
        gross_rev = get_revenue(
            year, snapshot.launch_year, snapshot.patent_expiry_year,
            snapshot.peak_sales_usd_m, snapshot.time_to_peak_years,
            snapshot.generic_erosion_pct, snapshot.uptake_curve,
        )
        cogs = gross_rev * snapshot.cogs_pct
        sga = gross_rev * snapshot.sga_pct
        op_profit = gross_rev - cogs - sga
        tax = max(op_profit * snapshot.tax_rate, 0)
        commercial_cf = op_profit - tax

        net_cf = commercial_cf - rd_cost

        # Cumulative POS
        cum_pos = cumulative_pos(phase_dicts, year)

        # Risk-adjusted
        risk_adj_cf = net_cf * cum_pos

        # Discount
        df = mid_year_discount_factor(year, base_year, snapshot.discount_rate)
        pv = risk_adj_cf * df
        running_npv += pv

        cashflow_rows.append({
            "year": year,
            "rd_cost_usd_m": round(rd_cost, 4),
            "commercial_cf_usd_m": round(commercial_cf, 4),
            "net_cashflow_usd_m": round(net_cf, 4),
            "cumulative_pos": round(cum_pos, 6),
            "risk_adjusted_cf_usd_m": round(risk_adj_cf, 4),
            "discount_factor": round(df, 6),
            "pv_usd_m": round(pv, 4),
            "cumulative_npv_usd_m": round(running_npv, 4),
        })

    # Save cashflows to DB
    crud.save_cashflows(db, snapshot.id, cashflow_rows)

    # Also update commercial rows
    _save_commercial_rows(db, snapshot)

    tot_pos = total_pos(phase_dicts)

    from ..schemas import CashflowRowOut
    # Reload cashflows from DB for response
    reloaded = crud.get_snapshot(db, snapshot.id)
    cf_out = [CashflowRowOut.model_validate(cf) for cf in reloaded.cashflows]

    return {
        "snapshot_id": snapshot.id,
        "enpv_usd_m": round(running_npv, 2),
        "risk_adjusted_npv_usd_m": round(running_npv, 2),
        "unadjusted_npv_usd_m": round(running_npv / tot_pos if tot_pos > 0 else 0, 2),
        "cumulative_pos": round(tot_pos, 6),
        "peak_sales_usd_m": snapshot.peak_sales_usd_m,
        "launch_year": snapshot.launch_year,
        "cashflows": cf_out,
    }


def _save_commercial_rows(db: Session, snapshot: models.Snapshot):
    """Generate and save commercial rows."""
    db.query(models.CommercialRow).filter(
        models.CommercialRow.snapshot_id == snapshot.id
    ).delete()

    commercial_end = snapshot.patent_expiry_year + 3
    for year in range(snapshot.launch_year, commercial_end + 1):
        gross_rev = get_revenue(
            year, snapshot.launch_year, snapshot.patent_expiry_year,
            snapshot.peak_sales_usd_m, snapshot.time_to_peak_years,
            snapshot.generic_erosion_pct, snapshot.uptake_curve,
        )
        if gross_rev <= 0:
            continue
        cogs = gross_rev * snapshot.cogs_pct
        sga = gross_rev * snapshot.sga_pct
        op_profit = gross_rev - cogs - sga
        tax = max(op_profit * snapshot.tax_rate, 0)
        net_cf = op_profit - tax

        db.add(models.CommercialRow(
            snapshot_id=snapshot.id,
            year=year,
            gross_sales_usd_m=round(gross_rev, 4),
            net_sales_usd_m=round(gross_rev, 4),
            cogs_usd_m=round(cogs, 4),
            sga_usd_m=round(sga, 4),
            operating_profit_usd_m=round(op_profit, 4),
            tax_usd_m=round(tax, 4),
            net_cashflow_usd_m=round(net_cf, 4),
        ))
    db.commit()
