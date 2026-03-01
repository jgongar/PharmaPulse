# PharmaPulse rNPV Engine — Deep Technical Review

**Reviewer:** Claude Opus 4.6
**Date:** 2026-02-28
**Scope:** Deterministic rNPV engine, revenue curves, risk adjustment, discounting, data model
**Files reviewed:**
- `backend/engines/deterministic.py` (531 lines)
- `backend/engines/revenue_curves.py` (245 lines)
- `backend/engines/risk_adjustment.py` (121 lines)
- `backend/engines/discounting.py` (62 lines)
- `backend/models.py` (733 lines)
- `backend/schemas.py` (555 lines)
- `backend/crud.py` (802 lines)

---

## 1. MATHEMATICAL RECONSTRUCTION

### The rNPV formula as actually implemented

The engine computes total NPV as two independent components:

```
NPV_total = NPV_R&D + NPV_commercial
```

**R&D Component** (deterministic.py:157–179):

```
NPV_R&D = Σ_t [ C_t × L_rd × M_cost(phase_t) × DF(t, t_0, WACC_rd) ]
```

Where:
- `C_t` = raw R&D cost in year t (from rd_costs table)
- `L_rd` = R&D cost what-if lever (default 1.0)
- `M_cost(phase_t)` = cumulative POS of all phases BEFORE phase_t (see Section 2)
- `DF(t, t_0, r)` = mid-year discount factor = 1 / (1 + r)^(t - t_0 - 0.5)
- `t_0` = valuation_year
- Costs where `t < valuation_year` are excluded (sunk cost filter)
- Costs for phases before `current_phase` are excluded (already sunk)

**Commercial Component** (deterministic.py:208–297):

```
NPV_commercial = Σ_region Σ_scenario [ P_scenario × Σ_t PV_t(region, scenario) ]
```

Where each year's present value is:

```
Revenue_t = Σ_segment [ PeakRevenue_seg × Uptake(t, curve_params) ] × L_rev

EBIT_t = Revenue_t × (1 - COGS% - Distribution% - OpCost%)

Tax_t = max(0, EBIT_t × TaxRate)

FCF_t = EBIT_t - Tax_t

PV_t = FCF_t × M_commercial × DF(t, t_0, WACC_region)
```

Where:
- `PeakRevenue_seg` = PatientPop × f1×f2×f3×f4×f5×f6 × AccessRate × MarketShare × Units × Treatments × Compliance × GrossPrice × GrossToNet / 1,000,000
- `Uptake(t)` = numerical integral of the uptake curve over calendar year t (trapezoidal, 12 steps)
- `L_rev` = revenue what-if lever (default 1.0)
- `M_commercial` = cumulative POS (product of ALL phase success rates)
- `P_scenario` = scenario probability weight
- Cost rates (COGS, Distribution, OpCost) are taken from `rows[0]` (first row in region-scenario group)

**Peak Sales Reporting:**

```
PeakSales_total = Σ_region Σ_scenario [ P_scenario × Σ_segment PeakRevenue_seg ]
```

---

## 2. PTRS APPLICATION

**Reference:** `risk_adjustment.py:36–102`, called from `deterministic.py:141–144, 168, 273`

### Logic

The PTRS (Probability of Technical and Regulatory Success) is implemented as a **per-phase cumulative product**, which is the correct textbook approach.

**Phase order** (fixed): Phase 1 → Phase 2 → Phase 2 B → Phase 3 → Registration

**Rules implemented:**
1. Phases before `current_phase` have their SR forced to 1.0 (already succeeded) — **CORRECT** (risk_adjustment.py:74–76)
2. R&D cost multiplier for phase i = product of SR for all phases BEFORE phase i — **CORRECT** (risk_adjustment.py:88–93)
3. Commercial multiplier = product of ALL phase SRs (including Registration) — **CORRECT** (risk_adjustment.py:98–99)

**Worked example:** Asset in Phase 2, SR = {P1: 0.80, P2: 0.65, P2B: 0.70, P3: 0.55, Reg: 0.90}

After forcing phases before Phase 2 to 1.0:
- Effective SR: {P1: 1.0, P2: 0.65, P2B: 0.70, P3: 0.55, Reg: 0.90}
- Cost multiplier for P2 costs = 1.0 (product of phases before P2)
- Cost multiplier for P2B costs = 1.0 × 0.65 = 0.65
- Cost multiplier for P3 costs = 1.0 × 0.65 × 0.70 = 0.455
- Cost multiplier for Registration costs = 1.0 × 0.65 × 0.70 × 0.55 = 0.2503
- Commercial multiplier = 1.0 × 0.65 × 0.70 × 0.55 × 0.90 = 0.2252

### Assessment

**CORRECT.** This is standard rNPV methodology:
- R&D costs are risk-adjusted by the probability that the program reaches each phase
- Commercial revenues are risk-adjusted by the full cumulative POS
- Past phases are correctly treated as certainty (SR=1.0)

### One concern

The cost multiplier is applied as: `risk_adj_cost = raw_cost * cost_multiplier` (deterministic.py:174). Since R&D costs are typically negative (expenses), this means the risk-adjusted cost is LESS negative. This is economically correct — risk adjustment reduces the expected outflow. However, the `rd_cost` column in the model has the docstring "negative = expense" but the seed data and engine behavior should be verified to ensure sign consistency. The FCF stored as `fcf_non_risk_adj` at deterministic.py:187 stores `raw_cost` directly — if this is negative, the NPV contribution is negative, which is correct.

---

## 3. DISCOUNTING CONVENTION

**Reference:** `discounting.py:16–49`

### Formula

```
PV = CF / (1 + WACC)^((year - valuation_year) - 0.5)
```

### Mid-year convention: IMPLEMENTED

The `-0.5` term implements mid-year convention, assuming cashflows occur at the midpoint of each calendar year rather than year-end. This is standard pharma valuation practice.

**Exponent values:**
| Year offset | Exponent | Meaning |
|---|---|---|
| year = valuation_year | -0.5 | CF is PREMIUM (inflated by half-year compound) |
| year = valuation_year + 1 | 0.5 | Standard first-year discount |
| year = valuation_year + 2 | 1.5 | Standard second-year discount |

### Issue: Negative exponent behavior (discounting.py:43–46)

```python
if exponent < 0:
    # Cashflow in or before valuation year — no discounting needed
    # (but still apply mid-year for partial year)
    pass
```

The comment says "no discounting needed" but the code does nothing — it falls through and STILL applies the discount factor with a negative exponent. A negative exponent means `discount_factor < 1`, so `CF / discount_factor` **inflates** the cashflow.

**This is actually mathematically correct** for mid-year convention: a cashflow occurring at mid-valuation-year (t - t_0 = 0, exponent = -0.5) should be slightly inflated to its end-of-year equivalent. But the misleading comment suggests the developer may not have intended this behavior.

**Verdict:** The math is correct. The comment is misleading and should be fixed, but the code produces the right numbers.

### Dual WACC

The engine correctly uses separate discount rates:
- `wacc_rd` for R&D cashflows (deterministic.py:177)
- `wacc_region` for commercial cashflows (deterministic.py:276)

This is industry-standard — R&D carries higher technical risk (lower WACC is typical for pre-revenue phase) while commercial cashflows use a regional market WACC.

---

## 4. REVENUE CURVES

**Reference:** `revenue_curves.py:18–194`

### Curve types implemented

**Two uptake curve types:**
1. **Logistic** (S-curve): `uptake(τ) = 1 / (1 + exp(-k × (τ - midpoint)))` — (revenue_curves.py:18–27)
2. **Linear**: `uptake(τ) = τ` (clamped to [0, 1]) — (revenue_curves.py:30–34)

Where `τ = (t - launch_date) / time_to_peak` is normalized ramp-up time.

### Revenue lifecycle phases

The `_uptake_at_time()` function (revenue_curves.py:37–116) implements 4 lifecycle phases:

```
| Phase        | Period                       | Uptake multiplier         |
|------------- |------------------------------|---------------------------|
| Pre-launch   | t < launch_date              | 0.0                       |
| Ramp-up      | launch → launch+time_to_peak | logistic(τ) or linear(τ)  |
| Plateau      | peak → min(peak+plateau, LOE)| 1.0                       |
| Post-LOE     | LOE → LOE+erosion_years      | cliff → linear to floor   |
| Floor        | beyond erosion period         | erosion_floor_pct         |
```

### LOE erosion model

**At LOE:** Immediate cliff to `loe_cliff_rate` fraction of peak (NOT a drop BY that amount).

Example: `loe_cliff_rate = 0.85` means revenue drops TO 85% of peak (revenue_curves.py:100–103).

**After cliff:** Linear decline from `loe_cliff_rate` to `erosion_floor_pct` over `years_to_erosion_floor` years (revenue_curves.py:110–116).

**At floor:** Revenue stays at `erosion_floor_pct × peak_revenue` indefinitely.

### LOE is NOT a step function

The implementation is a **cliff + linear ramp-down**, which is more realistic than a pure step function. The cliff is instantaneous (step at LOE year), but erosion is gradual. This is correct.

### Numerical integration

Annual revenue is computed by trapezoidal integration over 12 sub-intervals within each calendar year (revenue_curves.py:168–193). This handles fractional launch dates and LOE dates correctly — partial years get proportional revenue.

**Accuracy:** 12 steps is adequate for the logistic curve given typical parameters (k=5.5). The maximum error for a smooth logistic with 12 steps is approximately 0.1%.

### Peak revenue formula

`compute_peak_revenue_for_row()` (revenue_curves.py:197–242):

```
PeakRevenue = (Pop × f1 × f2 × f3 × f4 × f5 × f6 × access × share
               × units × treatments × compliance × price × GtN) / 1,000,000
```

**Correct.** Output is in EUR millions as documented.

### Issue: Logistic curve does not reach 1.0 at τ=1.0

With default parameters k=5.5, midpoint=0.5:
- `uptake(τ=0.0)` = 1/(1+exp(2.75)) ≈ 0.060 (not 0.0)
- `uptake(τ=1.0)` = 1/(1+exp(-2.75)) ≈ 0.940 (not 1.0)

This means the logistic ramp-up only reaches ~94% of peak at the end of the ramp-up period, then jumps to 100% at plateau. With k=5.5 there is a **~6% discontinuity** at the ramp-up/plateau transition. Higher k values (e.g., k=10) would reduce this to <1%.

**Impact:** Slight undervaluation during ramp-up years, then a small upward jump at plateau. For most assets this is negligible, but it is worth noting.

**Recommendation:** Consider normalizing the logistic curve so that `uptake(0)=0` and `uptake(1)=1`:

```
uptake_norm(τ) = (logistic(τ) - logistic(0)) / (logistic(1) - logistic(0))
```

---

## 5. COST MODEL

**Reference:** `deterministic.py:153–191`

### R&D cost phasing

R&D costs are stored as explicit (year, phase, amount) tuples in the `rd_costs` table. There is no automatic cost spreading — costs are entered per year by the user. This is the correct approach for a pharma rNPV model.

### Sunk cost handling

Two filters (deterministic.py:159–164):
1. `cost.year < valuation_year` → skip (sunk by time)
2. `cost_phase_idx < current_phase_idx` → skip (sunk by phase)

**CORRECT.** Only future costs for current and later phases are included.

### R&D cost risk adjustment — CORRECT

R&D costs are risk-adjusted using the **cost multiplier** (probability that the program reaches that phase):

```python
cost_multiplier = get_phase_cost_multiplier(pos_result, cost.phase_name)  # line 168
risk_adj_cost = raw_cost * cost_multiplier                                 # line 174
```

This is correct rNPV methodology. R&D costs are NOT "certain" — they are only incurred if the program reaches that phase. The probability of reaching phase i equals the product of success rates of all prior phases.

**Note:** Some practitioners treat near-term costs (current phase) as certain and only risk-adjust future phases. This implementation risk-adjusts ALL phases including the current one (the current phase has cost_multiplier = product of SR of prior phases = 1.0 since prior phases are forced to SR=1.0). So effectively, current phase costs ARE treated as certain. **This is correct.**

### Commercial cost model

Commercial costs are computed as percentages of revenue (deterministic.py:264–268):

```
COGS = revenue × cogs_rate
Distribution = revenue × distribution_rate
Operating = revenue × operating_cost_rate
Tax = max(0, EBIT × tax_rate)
```

**Issue:** Tax floor at zero (line 269) prevents negative tax (tax credit) in loss years. This is conservative but may understate value for assets with early commercial losses.

### Issue: Cost rates from `rows[0]` only

At deterministic.py:263, cost rates are taken from `rep_row = rows[0]` (the first row in the region-scenario group). If different segments within the same region-scenario have different cost rates, they are ignored. This could be a problem if segments have materially different cost structures.

**Severity:** Low-medium. Most pharma models use uniform cost rates per region, so this is a reasonable simplification. But the data model allows per-segment rates, creating an inconsistency.

---

## 6. EDGE CASES AND GAPS

### 6.1 Silent errors / division by zero

| Condition | Location | Behavior | Risk |
|---|---|---|---|
| `time_to_peak = 0` | revenue_curves.py:70 | τ is set to 1.0 via ternary | **SAFE** — handled |
| `years_to_erosion_floor = 0` | revenue_curves.py:107 | Returns `erosion_floor_pct` immediately | **SAFE** — handled |
| `WACC = -1.0` (100% negative) | discounting.py:48 | Division by zero in `(1 + wacc)^exp` | **BUG** — no validation. Schema caps WACC at 0.30 (schemas.py:217) but only for `wacc_rd`. `wacc_region` in CommercialRowSchema has `le=1.0` (line 151) which technically allows 1.0 = 100% WACC. |
| `WACC = 0` | discounting.py:48 | `(1+0)^exp = 1` → no discounting | **SAFE** — valid edge case |
| `peak_revenue = 0` | revenue_curves.py:156 | Returns 0.0 immediately | **SAFE** — handled |
| No commercial_rows exist | deterministic.py:208 | Loop doesn't execute, npv_commercial = 0 | **SAFE** |
| No rd_costs exist | deterministic.py:157 | Loop doesn't execute, npv_rd = 0 | **SAFE** |
| No phase_inputs exist | risk_adjustment.py:60–65 | sr_map is empty, cumulative stays 1.0 | **QUESTIONABLE** — commercial_multiplier = 1.0 (no risk adjustment) |
| `current_phase` not in PHASE_ORDER | risk_adjustment.py:57 | Raises ValueError | **SAFE** — explicit error |
| `current_phase` is None | deterministic.py:155 | `PHASE_ORDER.index(None)` → exception | **BUG** — Asset.current_phase is nullable (models.py:68), engine will crash |
| `horizon_years = 0` | deterministic.py:150 | `horizon_end = valuation_year + 0`, loop range is empty | **SAFE** — but nonsensical input |
| R&D cost phase_name not in PHASE_ORDER | deterministic.py:163 | `cost_phase_idx = -1`, always < current_phase_idx → cost is SKIPPED | **BUG** — costs with non-standard phase names are silently dropped |
| Scenario probabilities don't sum to 1.0 | deterministic.py:295 | Probabilities used as-is | **RISK** — no validation. If probabilities for a region sum to 0.8, NPV is understated by 20% |

### 6.2 Missing validations

1. **Scenario probability sum:** No check that `Σ scenario_probability = 1.0` for each region. This is the most dangerous missing validation — silent NPV error.

2. **Phase completeness:** No check that all phases from `current_phase` to Registration exist in `phase_inputs`. Missing phases have SR implicitly = 1.0 (they're not in sr_map, so `cumulative` passes through unchanged at risk_adjustment.py:83–84). This silently overstates the probability of success.

3. **Launch date vs. approval date consistency:** No check that `launch_date >= approval_date`. If launch is before approval, the model will generate revenue before the drug is approved.

4. **LOE vs. launch date:** No check that `loe_year > launch_date`. If LOE is before launch, the entire commercial period is in post-LOE erosion.

5. **Current phase None handling:** `Asset.current_phase` is nullable but the engine crashes if it's None.

### 6.3 Logical issues

**Duration shift cascade not propagated to R&D cost years** (deterministic.py:157–191): When what-if duration levers shift the timeline, commercial launch dates are adjusted (line 226–229), but R&D cost years are NOT shifted. If Phase 2 is delayed by 12 months, the R&D costs for Phase 3 should also shift by 12 months. Currently they don't — the engine uses the original `cost.year` values.

**Severity:** Medium. This means duration levers correctly delay revenue but incorrectly keep R&D costs in their original years.

---

## 7. VERDICT

### Scoring

| Component | Score | Assessment |
|---|---|---|
| rNPV formula structure | **CORRECT** | Standard textbook two-component rNPV |
| PTRS / cumulative POS | **CORRECT** | Per-phase cumulative product, prior phases forced to 1.0 |
| Mid-year discounting | **CORRECT** | Proper `-0.5` exponent offset |
| Dual WACC (R&D vs. commercial) | **CORRECT** | Industry standard |
| Revenue curve (logistic + linear) | **CORRECT with minor artifact** | ~6% discontinuity at ramp-up/plateau transition with default k=5.5 |
| LOE erosion (cliff + linear) | **CORRECT** | Realistic two-phase erosion model |
| Numerical integration | **CORRECT** | 12-step trapezoidal, adequate accuracy |
| Peak revenue formula | **CORRECT** | Proper patient-based revenue buildup |
| R&D cost risk adjustment | **CORRECT** | Costs risk-adjusted by probability of reaching each phase |
| Sunk cost handling | **CORRECT** | Both time-based and phase-based filters |
| Commercial cost model | **APPROXIMATE** | Cost rates from first row only (deterministic.py:263) |
| Scenario weighting | **CORRECT** | Probability-weighted NPV across scenarios |
| What-if duration lever → R&D costs | **WRONG** | Duration shifts don't cascade to R&D cost years (deterministic.py:157–191) |
| Null current_phase | **WRONG** | Crashes on nullable field (deterministic.py:155) |
| Scenario probability validation | **MISSING** | No check that probabilities sum to 1.0 |
| Phase completeness validation | **MISSING** | Missing phases silently treated as SR=1.0 |
| Negative exponent comment | **MISLEADING** | Comment says "no discounting" but code correctly applies it (discounting.py:43–46) |

### Summary

The core mathematical engine is **sound and well-implemented**. The rNPV methodology follows industry-standard practice. The two bugs found (duration lever not cascading to R&D costs, nullable current_phase crash) are edge cases that would only surface under specific what-if scenarios or with incomplete data entry. The missing validations (scenario probabilities, phase completeness) are the most operationally dangerous issues because they can produce silently incorrect results.

---

## DATA MODEL REVIEW

### 1. Schema completeness for rNPV inputs

**Does the schema capture all required inputs?**

| Required input | Stored in | Status |
|---|---|---|
| Valuation year | `snapshots.valuation_year` | Present, NOT NULL |
| Horizon | `snapshots.horizon_years` | Present, NOT NULL |
| WACC R&D | `snapshots.wacc_rd` | Present, NOT NULL |
| WACC commercial | `commercial_rows.wacc_region` | Present, NOT NULL, per-region |
| Approval date | `snapshots.approval_date` | Present, NOT NULL |
| Current phase | `assets.current_phase` | **NULLABLE** — engine crashes if NULL |
| Phase SR | `phase_inputs.success_rate` | Present, NOT NULL |
| Phase timeline | `phase_inputs.start_date` | Present, NOT NULL |
| Phase duration | NOT STORED | **MISSING** — duration is implicit (gap between consecutive start_dates). No explicit `duration_months` column. The what-if lever `lever_duration_months` modifies something that isn't explicitly stored. |
| R&D costs | `rd_costs.{year, phase_name, rd_cost}` | Present, all NOT NULL |
| Patient population | `commercial_rows.patient_population` | Present, NOT NULL |
| Epi filters (f1–f6) | `commercial_rows.epi_f1..f6` | Present, NOT NULL, default 1.0 |
| Pricing | `commercial_rows.gross_price_per_treatment` | Present, NOT NULL |
| Market access | `commercial_rows.{access_rate, market_share}` | Present, NOT NULL |
| Revenue curve params | `commercial_rows.{time_to_peak, plateau_years, ...}` | Present, NOT NULL |
| LOE params | `commercial_rows.{loe_year, loe_cliff_rate, ...}` | Present, all NOT NULL |
| Cost rates | `commercial_rows.{cogs_rate, distribution_rate, ...}` | Present, all NOT NULL |
| Scenario probability | `commercial_rows.scenario_probability` | Present, NOT NULL |
| Launch date | `commercial_rows.launch_date` | Present, NOT NULL |

**Issues found:**
- `assets.current_phase` is nullable (models.py:68) but the engine requires it (risk_adjustment.py:57 raises ValueError, deterministic.py:155 crashes on `PHASE_ORDER.index(None)`). **This should be NOT NULL for internal assets.**
- Phase duration is never explicitly stored — the engine infers it from start_date gaps. The `_build_phase_timeline()` function (deterministic.py:353–409) works with start_dates and applies duration shifts, but there's no stored `end_date` or `duration_months`. This makes the data model fragile — if phase_inputs only has a subset of phases, the engine can't compute inter-phase gaps.
- `logistic_k` and `logistic_midpoint` on CommercialRow are nullable (models.py:280–281) with defaults. The engine handles this with `row.logistic_k or 5.5` (deterministic.py:250), which correctly falls back. But `or` would also trigger on `0.0`, which is a valid (if unusual) parameter. Use `if x is None` instead.

### 2. Phase structure edge cases

| Edge case | Supported? | Notes |
|---|---|---|
| Single-phase asset (Registration only) | **YES** | If `current_phase = "Registration"` and only Registration phase input exists, all prior phases are forced to SR=1.0, commercial_multiplier = Registration SR |
| Asset already at Registration | **YES** | Works correctly — only Registration SR matters |
| Non-standard phase sequences | **NO** | PHASE_ORDER is hardcoded (risk_adjustment.py:20). No support for Phase 1/2 combined, or custom phases |
| Missing intermediate phases | **SILENT BUG** | If Phase 2 exists but Phase 2 B does not, Phase 2 B is implicitly SR=1.0 — overstates POS |
| Asset at "Approved" phase | **PARTIAL** | "Approved" is a valid phase in the schema validator (schemas.py:48) but NOT in PHASE_ORDER (risk_adjustment.py:20). The engine would crash at `get_phase_index("Approved")` |
| Phases with overlapping start_dates | **UNDEFINED** | No constraint prevents two phases from having the same start_date. `_build_phase_timeline` sorts by start_date (deterministic.py:382–384) so overlapping phases would have arbitrary ordering |

**Critical gap:** The "Approved" phase is accepted by the schema validator but not by the engine. An asset marked as "Approved" cannot have its NPV calculated.

### 3. Audit trail and reproducibility

**Can cashflows be reconstructed?**

The `cashflows` table stores (deterministic.py:412–528):
- Per (year, scope): revenue, costs, tax, fcf_non_risk_adj, risk_multiplier, fcf_risk_adj, fcf_pv
- Total rows per year
- cashflow_type distinguishes deterministic vs. whatif

**What IS stored:**
- All intermediate values (revenue, costs, tax, FCF, risk-adj FCF, PV)
- Risk multiplier per row
- Scenario-weighted aggregation (commercial cashflows are probability-weighted before storage at line 441–447)

**What is NOT stored:**
- Per-scenario breakdown (scenarios are aggregated before storage)
- WACC used for discounting (only the discount result is stored, not the rate)
- Peak revenue per segment (computed on the fly, not persisted)
- Which what-if levers were applied (stored on the snapshot, but not on the cashflow)
- The uptake curve value per year (only the resulting revenue is stored)

**Reproducibility concern:** If the user changes inputs (e.g., edits a commercial row) and recalculates, the old cashflows are **deleted** (deterministic.py:424–427) and replaced. There is no audit trail of previous calculations unless the user clones the snapshot first.

**Verdict:** The cashflow table provides reasonable audit data for a single calculation run, but it cannot reconstruct WHY a particular number was produced (no stored WACC, no per-scenario detail). For full audit trail, the user must rely on snapshot immutability — but snapshots are mutable (inputs can be edited and recalculated).

### 4. Portfolio override model

**Reference:** `models.py:528–564`, `schemas.py:323–342`, `crud.py:553–647`

**Override types supported:**

| Override type | override_value meaning | phase_name used? | Extra columns used? | Status |
|---|---|---|---|---|
| `phase_delay` | months to delay | YES | No | **WORKS** |
| `peak_sales_change` | multiplier (e.g. 1.2 = +20%) | No | No | **WORKS** |
| `sr_override` | new absolute SR | YES | No | **WORKS** |
| `launch_delay` | months to delay launch | No | No | **WORKS** |
| `time_to_peak_change` | delta in years | No | No | **WORKS** |
| `accelerate` | flag (1.0) | YES | `acceleration_budget_multiplier`, `acceleration_timeline_reduction` | **WORKS** — uses both extra columns |
| `budget_realloc` | reallocation amount | No | No | **WORKS** |
| `project_kill` | flag (1.0) | No | No | **WORKS** — auto-created by `deactivate_project()` (crud.py:484–521) |
| `project_add` | added_project.id | No | No | **WORKAROUND** — linked to first portfolio project as anchor (crud.py:599–608) |
| `project_add` anchor | — | — | — | **HACK** — override is attached to an arbitrary existing project because the schema requires `portfolio_project_id`. Hypothetical projects don't have a PortfolioProject row. |
| `bd_add` | bd_placeholder.id | No | No | **SAME HACK** — linked to first portfolio project (crud.py:636–643) |

**Assessment of the override model:**

**What works well:**
- The single-table design is clean and extensible
- `override_type` validation in the schema (schemas.py:333–342) prevents invalid types
- `accelerate` override properly uses the extra columns for budget and timeline effects
- `project_kill` is properly bidirectional with `is_active` flag

**What is problematic:**

1. **`project_add` and `bd_add` anchor hack** (crud.py:599–608, 636–643): These overrides are linked to `first_project` in the portfolio — an arbitrary anchor. If that project is deleted, the override CASCADE-deletes with it, silently removing the hypothetical project reference. If the portfolio has NO projects, the override is not created at all (`if first_project:` guard at line 604).

2. **`override_value` is Float, not nullable** (models.py:550): All overrides MUST have a numeric value. For `project_kill`, this is forced to `1.0`. For `project_add` and `bd_add`, the ID of the added entity is stored as a float. This works but is semantically wrong — using a float to store an integer foreign key is fragile (float precision issues with large IDs).

3. **`acceleration_timeline_reduction` not in OverrideCreate schema** (schemas.py:323–330): The `OverrideCreate` schema has `acceleration_budget_multiplier` but NOT `acceleration_timeline_reduction`. This means the acceleration timeline reduction cannot be set via the API. It exists in the model but not the schema.

4. **No compound override validation:** Nothing prevents creating contradictory overrides (e.g., `phase_delay` +12 months AND `accelerate` -6 months on the same phase). The simulation engine must handle these conflicts, but there's no documentation of precedence rules.

---

## APPENDIX: LINE-REFERENCED ISSUES

| # | Severity | File:Line | Description |
|---|---|---|---|
| 1 | **HIGH** | deterministic.py:155 | `current_phase=None` causes crash — `PHASE_ORDER.index(None)` |
| 2 | **HIGH** | risk_adjustment.py:57 | `get_phase_index("Approved")` crashes — "Approved" not in PHASE_ORDER |
| 3 | **MEDIUM** | deterministic.py:157–191 | Duration lever shifts not cascaded to R&D cost years |
| 4 | **MEDIUM** | deterministic.py:263 | Cost rates taken from `rows[0]` only — ignores per-segment rates |
| 5 | **MEDIUM** | No validation | Scenario probabilities per region not validated to sum to 1.0 |
| 6 | **MEDIUM** | risk_adjustment.py:83–84 | Missing phases silently treated as SR=1.0 |
| 7 | **MEDIUM** | crud.py:599–608 | `project_add` override anchored to arbitrary first project |
| 8 | **MEDIUM** | schemas.py:323–330 | `acceleration_timeline_reduction` missing from OverrideCreate |
| 9 | **LOW** | discounting.py:43–46 | Comment says "no discounting" but code correctly applies it |
| 10 | **LOW** | deterministic.py:250 | `row.logistic_k or 5.5` — `or` treats 0.0 as falsy |
| 11 | **LOW** | models.py:68 | `current_phase` nullable but engine requires it |
| 12 | **LOW** | revenue_curves.py:26 | Logistic uptake ~6% discontinuity at plateau transition with k=5.5 |

---

*End of review.*
