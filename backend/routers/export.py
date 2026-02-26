"""
Export Router — /api/export

Provides endpoints for exporting data in various formats (Excel, CSV).

Endpoints:
    GET /api/export/cashflows/{snapshot_id}  — Export cashflows as Excel
"""

import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Cashflow, Snapshot

router = APIRouter(prefix="/api/export", tags=["Export"])


@router.get("/cashflows/{snapshot_id}")
def export_cashflows_excel(snapshot_id: int, db: Session = Depends(get_db)):
    """
    Export all cashflows for a snapshot as an Excel (.xlsx) file.
    Uses openpyxl via pandas to generate the workbook.
    """
    import pandas as pd
    
    snapshot = db.query(Snapshot).filter(Snapshot.id == snapshot_id).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    
    cashflows = (
        db.query(Cashflow)
        .filter(Cashflow.snapshot_id == snapshot_id)
        .order_by(Cashflow.cashflow_type, Cashflow.scope, Cashflow.year)
        .all()
    )
    
    if not cashflows:
        raise HTTPException(
            status_code=404,
            detail="No cashflows found. Run NPV calculation first.",
        )
    
    # Build DataFrame
    data = []
    for cf in cashflows:
        data.append({
            "Type": cf.cashflow_type,
            "Scope": cf.scope,
            "Year": cf.year,
            "Revenue (€mm)": round(cf.revenue, 2),
            "Costs (€mm)": round(cf.costs, 2),
            "Tax (€mm)": round(cf.tax, 2),
            "FCF Non-RA (€mm)": round(cf.fcf_non_risk_adj, 2),
            "Risk Multiplier": round(cf.risk_multiplier, 4),
            "FCF Risk-Adj (€mm)": round(cf.fcf_risk_adj, 2),
            "FCF PV (€mm)": round(cf.fcf_pv, 2),
        })
    
    df = pd.DataFrame(data)
    
    # Write to Excel buffer
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Cashflows", index=False)
    buffer.seek(0)
    
    filename = f"cashflows_snapshot_{snapshot_id}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


