# PharmaPulse — Consolidated Fix Plan

## Context

Two technical reviews (NPV Engine + Simulation Families) identified 32 issues across the codebase. The user's key architectural decision: **eliminate all approximation engines** — the deterministic NPV engine runs fast enough to be called directly. All "what-if" analysis should clone inputs, modify them, and recalculate real NPV instead of using hardcoded `0.7/0.3` hacks.

This plan organizes fixes into 5 groups by theme, from foundational to incremental.

---

## GROUP 1: Foundation — Engine Correctness (P0)
*Fix the deterministic engine bugs before building on top of it.*

### Fix 1.1 — Handle `current_phase = None` and `"Approved"`
- **Problem:** `deterministic.py:155` crashes on `PHASE_ORDER.index(None)`. `risk_adjustment.py:57` crashes on `"Approved"`.
- **Action:** Add `"Approved"` to `PHASE_ORDER` in `risk_adjustment.py` with SR=1.0 semantics. In `deterministic.py`, guard `current_phase is None` — treat as Phase 1 (most conservative) or raise a clear error.
- **Files:** `risk_adjustment.py`, `deterministic.py`

### Fix 1.2 — Fix `_compute_pts()` in all family engines
- **Problem:** Families B, D, E each have their own `_compute_pts()` that multiplies ALL phase SRs without forcing completed phases to 1.0. Produces systematically wrong PTS.
- **Action:** Delete the per-file `_compute_pts()` functions. Create a single shared function in `risk_adjustment.py` that takes `phase_inputs` and `current_phase`, reusing the existing `compute_cumulative_pos()` logic. All families import from there.
- **Files:** `risk_adjustment.py` (add shared helper), `ta_reallocation.py`, `innovation_risk.py`, `bd_modeling.py`, `concentration.py` (all remove local `_compute_pts`, import shared one)

### Fix 1.3 — Fix double risk-adjustment in Family D scatter
- **Problem:** `innovation_risk.py:57` computes `risk_adjusted_npv = npv * pts`. But `npv` is already `snapshot.npv_deterministic` which is ALREADY risk-adjusted. Result: `NPV × PTRS²`.
- **Action:** Change to `risk_adjusted_npv = npv` (it already IS risk-adjusted). Or rename the field to clarify that `npv_deterministic` is the rNPV. Display raw PTS alongside for the scatter plot.
- **Files:** `innovation_risk.py`

### Fix 1.4 — Fix misleading discounting comment
- **Problem:** `discounting.py:43-46` comment says "no discounting needed" but code correctly applies it.
- **Action:** Fix comment to explain that negative exponent correctly inflates cashflows occurring before year-end of valuation year.
- **Files:** `discounting.py`

### Fix 1.5 — Fix `logistic_k or 5.5` falsy-zero
- **Problem:** `deterministic.py:250` uses `row.logistic_k or 5.5`. Python `or` treats `0.0` as falsy.
- **Action:** Change to `row.logistic_k if row.logistic_k is not None else 5.5`. Same for `logistic_midpoint`.
- **Files:** `deterministic.py`

---

## GROUP 2: Validation — Prevent Silent Errors (P0-P1)
*Add missing validations that cause silent wrong results.*

### Fix 2.1 — Validate scenario probabilities sum to 1.0
- **Problem:** No check that scenario probabilities per region sum to 1.0. Silent NPV error.
- **Action:** After grouping commercial rows by (region, scenario) in `deterministic.py`, validate that probabilities for each region sum to ~1.0 (within tolerance of 0.01). Raise ValueError if not.
- **Files:** `deterministic.py`

### Fix 2.2 — Warn on missing phases
- **Problem:** If a phase between `current_phase` and Registration is missing from `phase_inputs`, its SR is implicitly 1.0. Overstates POS silently.
- **Action:** In `risk_adjustment.py:compute_cumulative_pos()`, after building `sr_map`, check that all phases from `current_phase` to Registration exist. Log a warning if any are missing (don't error — some assets may legitimately skip Phase 2B).
- **Files:** `risk_adjustment.py`

### Fix 2.3 — Fix hardcoded `valuation_year = 2025`
- **Problem:** `portfolio_sim.py:384` and `474` hardcode `valuation_year = 2025` for hypothetical project and BD placeholder NPV calculations.
- **Action:** Accept `valuation_year` as a parameter. For added projects, use the portfolio's first project's snapshot valuation_year as default. For BD placeholders, same logic.
- **Files:** `portfolio_sim.py`

---

## GROUP 3: Architectural — Replace Approximations with Real NPV (P1)
*This is the big change. Replace all `0.7/0.3` hacks with actual NPV recalculation.*

### Fix 3.1 — Create `simulate_override_npv()` utility
- **Problem:** Portfolio sim override application (portfolio_sim.py:262-372) uses `0.7/0.3` approximations for ALL override types. Family A acceleration uses similar hacks.
- **Action:** Create a new function `simulate_override_npv(snapshot_id, overrides, db)` that:
  1. Clones the snapshot's input data to a temporary snapshot row in the DB (reuse `crud.clone_snapshot` logic but with a temp name)
  2. Applies overrides to the cloned inputs:
     - `phase_delay` → shift `phase_inputs.start_date` + `approval_date` + `commercial_rows.launch_date`
     - `peak_sales_change` → scale commercial row fields that affect peak revenue
     - `sr_override` → modify `phase_inputs.success_rate` for target phase
     - `launch_delay` → shift `commercial_rows.launch_date`
     - `time_to_peak_change` → modify `commercial_rows.time_to_peak`
     - `accelerate` → shift phase dates backward, increase R&D costs
     - `budget_realloc` → multiply R&D costs for target phase
  3. Calls `calculate_deterministic_npv(temp_snapshot_id, db)` to get exact NPV
  4. Reads the result, deletes the temporary snapshot (CASCADE cleans up children)
  5. Returns exact NPV
- **Strategy:** Write to DB then delete. Simple, reuses existing engine unchanged. The temporary snapshot lives only for the duration of the function call. Wrapped in try/finally to guarantee cleanup.
- **Files:** New function in `portfolio_sim.py`. Reuses `deterministic.py:calculate_deterministic_npv()`.

### Fix 3.2 — Rewire `apply_override()` to use real NPV
- **Problem:** `portfolio_sim.py:apply_override()` is the main approximation dispatcher.
- **Action:** Replace the body of `apply_override()` for each override type (except `project_kill`, `project_add`, `bd_add`) to call `simulate_override_npv()`. Keep `project_kill` as-is (just sets NPV=0). Keep `project_add`/`bd_add` as structural markers.
- **Files:** `portfolio_sim.py`

### Fix 3.3 — Rewire Family A acceleration to use real NPV
- **Problem:** `acceleration.py:274-280` uses `NPV × 0.7 × ((1+r)^Δt - 1)` estimate.
- **Action:** Replace the NPV gain estimate with: clone snapshot, shift phase dates by months_saved, recalculate deterministic NPV, delta = new_npv - old_npv. Keep the acceleration curve model (concave log) for computing months_saved — that's a strategic model, not an approximation.
- **Files:** `acceleration.py`, imports `simulate_override_npv` or calls deterministic engine directly

### Fix 3.4 — Rewire Family E BD valuation to use deterministic engine
- **Problem:** `bd_modeling.py:31-108` uses a bespoke mini-NPV model with different revenue curves, no mid-year convention, no cost breakdown.
- **Action:** Replace `value_bd_deal()` to create a temporary snapshot with proper commercial rows and R&D costs matching the BD deal parameters, then call `calculate_deterministic_npv()`. Return the exact result. This ensures BD deals and internal assets are valued on identical terms.
- **Files:** `bd_modeling.py`

### Fix 3.5 — Fix added project / BD placeholder NPV in portfolio sim
- **Problem:** `portfolio_sim.py:_calculate_added_project_npv()` and `_calculate_bd_placeholder_npv()` have their own mini-NPV engines with no mid-year convention, different logistic ramp, hardcoded valuation year.
- **Action:** Replace both functions to create temporary snapshots from their JSON data and call `calculate_deterministic_npv()`. Delete `_logistic_ramp()` helper (no longer needed).
- **Files:** `portfolio_sim.py`

---

## GROUP 4: Family Engine Fixes — Non-Approximation Issues (P2)

### Fix 4.1 — Family B: Use future-only R&D costs
- **Problem:** `ta_reallocation.py:67` sums ALL R&D costs including sunk years. Efficiency metric is wrong.
- **Action:** Filter R&D costs to only include years >= valuation_year (from snapshot). Aligns with deterministic engine's sunk cost filter.
- **Files:** `ta_reallocation.py`

### Fix 4.2 — Family B: Document linear NPV-cost limitation
- **Problem:** Budget shift assumes linear NPV-to-cost relationship.
- **Action:** Add a `limitations` field to the budget shift response explaining that the estimate assumes proportional cut across projects. Add a `projects_in_source_ta` list so the user can see which specific projects would be affected.
- **Files:** `ta_reallocation.py`

### Fix 4.3 — Family C: Add inactive project filter
- **Problem:** `temporal_balance.py:95` iterates all projects including killed ones.
- **Action:** Add `if not proj.is_active: continue` guard in revenue gap analysis and temporal heatmap.
- **Files:** `temporal_balance.py`

### Fix 4.4 — Family C: Fix heatmap cost sign
- **Problem:** `temporal_balance.py:223` does `revenue - abs(costs)`. Commercial costs in cashflow table are already negative, so `abs()` makes them positive and subtracts them — this is actually correct. But verify with actual data.
- **Action:** Verify sign convention by reading seed data cashflows. If correct, add clarifying comment. If wrong, fix.
- **Files:** `temporal_balance.py`

### Fix 4.5 — Family D: Fix quadrant labels
- **Problem:** "Cash Cow" used for NPV < 0 projects. BCG matrix misuse.
- **Action:** Rename quadrants: NPV≥0/low-risk → "Star", NPV≥0/high-risk → "High Risk / High Return", NPV<0/low-risk → "Low Return", NPV<0/high-risk → "Dog".
- **Files:** `innovation_risk.py`

### Fix 4.6 — Duration lever cascade to R&D costs
- **Problem:** `deterministic.py:157-191` — when what-if duration levers shift timeline, R&D cost years are NOT shifted.
- **Action:** After computing `total_shift_years` from `_build_phase_timeline()`, adjust each `cost.year` by the accumulated shift for that cost's phase. This ensures R&D costs for Phase 3 move forward when Phase 2 is delayed.
- **Files:** `deterministic.py`

### Fix 4.7 — OverrideCreate schema: add `acceleration_timeline_reduction`
- **Problem:** Field exists in model but missing from API schema.
- **Action:** Add `acceleration_timeline_reduction: Optional[float] = None` to `OverrideCreate` in `schemas.py`. Wire it through in `crud.py:add_override()`.
- **Files:** `schemas.py`, `crud.py`

---

## GROUP 5: Data Model Improvements (P3)

### Fix 5.1 — Fix project_add/bd_add anchor hack
- **Problem:** These overrides are linked to an arbitrary first project. CASCADE delete risk.
- **Action:** Make `portfolio_project_id` nullable on `PortfolioScenarioOverride`. For `project_add` and `bd_add` overrides, set `portfolio_project_id = NULL` and add a `reference_id` column (Integer, nullable) that stores the added_project or bd_placeholder ID. Update crud.py to stop linking to arbitrary first project. Update portfolio_sim.py to handle nullable portfolio_project_id.
- **Files:** `models.py`, `crud.py`, `portfolio_sim.py`
- **Migration:** Delete and recreate `pharmapulse.db` (SQLite, no production data — seed_data.py regenerates it).

### Fix 5.2 — Cost rates per segment (document limitation)
- **Problem:** `deterministic.py:263` uses `rows[0]` cost rates for all segments.
- **Action:** Document this as a known limitation in the code. A full fix would require per-segment cost computation, which changes the aggregation logic significantly. Low priority — most pharma models use uniform rates per region.
- **Files:** `deterministic.py` (add comment)

---

## Verification Plan

1. **Run existing tests:** `pytest tests/` — ensure nothing breaks
2. **Manual NPV comparison:** Pick one asset, calculate deterministic NPV before and after Group 1 fixes — numbers should match (Group 1 fixes edge cases, not the main path)
3. **Portfolio sim comparison:** Run portfolio sim with a `peak_sales_change` override before and after Group 3 — the AFTER result should differ (exact vs approximate) and the exact result should match a manual clone+recalc
4. **Family D scatter check:** Verify `risk_adjusted_npv` no longer double-counts after Fix 1.3
5. **PTS check:** Verify a Phase 3 asset shows PTS = SR(P3) × SR(Reg) (not SR(P1) × SR(P2) × ...) after Fix 1.2

---

## Execution Order

```
Group 1 (Foundation)     →  Fix 1.1, 1.2, 1.3, 1.4, 1.5
Group 2 (Validation)     →  Fix 2.1, 2.2, 2.3
Group 3 (Architecture)   →  Fix 3.1, 3.2, 3.3, 3.4, 3.5
Group 4 (Family fixes)   →  Fix 4.1–4.7
Group 5 (Data model)     →  Fix 5.1, 5.2
```

Total: **20 fixes** across **~12 files**.
Groups 1–2 are low-risk, localized changes.
Group 3 is the major architectural change (replacing approximations with real NPV).
Groups 4–5 are incremental improvements.
