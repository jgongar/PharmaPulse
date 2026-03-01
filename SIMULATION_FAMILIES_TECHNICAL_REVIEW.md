# PharmaPulse Strategy Simulation Families — Deep Technical Review

**Reviewer:** Claude Opus 4.6
**Date:** 2026-02-28
**Scope:** Six simulation family engines + portfolio simulation orchestrator
**Files reviewed:**
- `backend/engines/acceleration.py` (431 lines) — Family A
- `backend/engines/ta_reallocation.py` (305 lines) — Family B
- `backend/engines/temporal_balance.py` (253 lines) — Family C
- `backend/engines/innovation_risk.py` (328 lines) — Family D
- `backend/engines/bd_modeling.py` (283 lines) — Family E
- `backend/engines/concentration.py` (364 lines) — Family F
- `backend/engines/portfolio_sim.py` (622 lines) — Orchestrator

---

## FAMILY A: Kill / Continue / Accelerate

### 1. What question it answers
**"Should we kill this project, continue it, or accelerate it — and what is the financial trade-off?"**

### 2. How it calculates the answer

**Kill Analysis** (acceleration.py:122–196):
```
NPV_lost = snapshot.npv_deterministic
Budget_freed = Σ |R&D cashflow costs| for this project
Portfolio_NPV_after = Portfolio_NPV_before - NPV_lost
```
The budget freed is extracted from stored cashflows (scope="R&D"), falling back to the rd_costs table if no cashflows exist.

**Acceleration Analysis** (acceleration.py:224–302):
```
Acceleration curve:  reduction = α × ln(budget_multiplier),  α = 0.5
Months saved = reduction × original_phase_duration
Additional cost = (budget_multiplier - 1) × phase_R&D_cost

NPV gain estimate:
  years_saved = months_saved / 12
  commercial_fraction = 0.7  (HARDCODED)
  NPV_gain = original_NPV × 0.7 × ((1 + WACC)^years_saved - 1)
  Net impact = NPV_gain - additional_cost
```

**Kill & Reinvest** (acceleration.py:327–431):
Composes kill analysis + acceleration analysis. Budget freed from kill is converted to a budget multiplier for the acceleration target:
```
budget_multiplier = 1 + (budget_freed / target_phase_cost)
```
Capped at 2.0x.

### 3. Approximations and shortcuts

| Approximation | Location | Impact |
|---|---|---|
| **`commercial_fraction = 0.7` hardcoded** | acceleration.py:278 | Assumes 70% of NPV comes from commercial revenue. For early-stage assets with large R&D spend, the actual fraction could be 50% or lower. For late-stage, could be 90%+. **This makes the NPV gain estimate unreliable for edge cases.** |
| **NPV gain uses simple compounding** | acceleration.py:279 | `NPV × 0.7 × ((1+r)^Δt - 1)` is a rough time-value-of-money adjustment. It does NOT recalculate the actual revenue curve shifting forward in time. Real acceleration changes the shape of cashflows, not just their timing. |
| **Phase cost fallback** | acceleration.py:262–265 | If phase has no R&D costs, divides total R&D cost equally across all phases. This is crude — Phase 3 typically costs 5–10x more than Phase 1. |
| **ACCELERATION_ALPHA = 0.5** | acceleration.py:33 | The logarithmic calibration constant is hardcoded. In practice, this varies by therapeutic area, modality, and regulatory pathway. |
| **MAX_BUDGET_MULTIPLIER = 2.0** | acceleration.py:34 | Hard cap. No justification provided. Some programs can absorb 3x budget. |
| **Phase duration floor of 6 months** | acceleration.py:65 | `max((end - start) * 12, 6)` — if computed duration < 6 months, forces 6. Reasonable but arbitrary. |

### 4. Consistency with portfolio simulation

**Will the kill analysis number match a full portfolio sim with project_kill override?**

Kill analysis: `Portfolio_NPV_after = Portfolio_NPV_before - project_NPV` (acceleration.py:178)
Portfolio sim: Sets project NPV to 0 and re-sums (portfolio_sim.py:107–108)

**These WILL match** if `Portfolio_NPV_before` equals the portfolio sim total and no other overrides interact. But the kill analysis reads `portfolio.total_npv` (which is the last simulation run's total), while the portfolio sim recalculates from scratch. If any snapshot NPVs have changed since the last sim run, the kill analysis uses stale numbers.

**Will the acceleration NPV gain match?**

**NO.** The acceleration analysis estimates NPV gain using the `0.7 × (compound^Δt - 1)` formula. The portfolio sim applies `accelerate` override using a different formula (portfolio_sim.py:339–353):
```python
commercial_benefit = (npv_before * 0.7) * (1 + wacc)^years_accel
rd_cost_increase = |npv_before * 0.3| * budget_multiplier
npv_after = commercial_benefit - rd_cost_increase
```
These are **different calculations**:
- Family A: `NPV_gain = NPV × 0.7 × ((1+r)^Δt - 1)` → additive gain
- Portfolio sim: `npv_after = NPV × 0.7 × (1+r)^Δt - |NPV × 0.3| × budget_mult` → reconstructed NPV

The portfolio sim formula double-counts the R&D impact (it applies budget_multiplier to 30% of NPV, not to the actual R&D cost). Both are approximations, but they produce different numbers.

### 5. Production readiness

- **Will break if:** An asset has no R&D costs AND no commercial cashflows → `original_npv = 0`, `NPV_gain = 0` regardless of acceleration. Silent zero, not an error.
- **Will break if:** `portfolio.total_npv` is None (portfolio never simulated) → `portfolio_npv_before = 0`, division by zero in delta_pct (acceleration.py:192 has a guard, but the percentage is meaningless).
- **Stale data risk:** Kill analysis reads `snapshot.npv_deterministic` and `portfolio.total_npv` from last calculation. If inputs changed but NPV wasn't recalculated, numbers are stale. No staleness check.

### 6. Verdict: APPROXIMATE

The kill analysis is **CORRECT** (simple subtraction). The acceleration analysis is **APPROXIMATE** — it provides directionally correct trade-off analysis but uses a rough NPV gain formula that diverges from both the deterministic engine and the portfolio sim. Adequate for strategic screening; not adequate for final investment decisions.

---

## FAMILY B: TA Budget Reallocation

### 1. What question it answers
**"Which therapeutic areas are most efficient, and what happens if we shift budget from one TA to another?"**

### 2. How it calculates the answer

**TA Summary** (ta_reallocation.py:30–114):
```
Per TA:
  Total NPV = Σ project NPVs in that TA
  Total R&D Cost = Σ |rd_cost| across all phases and years
  Efficiency = Total NPV / Total R&D Cost (NPV per EUR mm invested)
  Avg Phase Index = mean of phase order numbers (1–6 scale)
  Avg PTS = mean of product(all phase SRs) per project
```

**Budget Shift** (ta_reallocation.py:121–226):
```
NPV_lost = Source TA NPV × (shift_amount / source_total_cost)    # LINEAR ASSUMPTION
Marginal_efficiency = Target TA efficiency × 0.70                 # 30% HAIRCUT
NPV_gained = shift_amount × marginal_efficiency
Net_delta = NPV_gained - NPV_lost
```

**Optimal Mix** (ta_reallocation.py:233–304):
```
optimal_share(TA) = max(efficiency(TA), 0) / Σ max(efficiency(all TAs), 0)
optimal_budget(TA) = optimal_share × total_budget
delta = optimal_budget - current_budget
```

### 3. Approximations and shortcuts

| Approximation | Location | Impact |
|---|---|---|
| **Linear NPV-to-cost assumption** | ta_reallocation.py:154–155 | `NPV_lost = source_NPV × (shift / source_cost)`. Assumes NPV is linearly proportional to R&D spend. In reality, cutting 30% of a TA's budget may kill one project entirely while leaving others untouched. The relationship is step-wise, not linear. **This is the most material approximation in the entire codebase.** |
| **70% marginal efficiency haircut** | ta_reallocation.py:158 | `marginal_efficiency = target_efficiency × 0.70`. Hardcoded 30% diminishing returns. No theoretical basis. Could be 50% or 90% depending on the TA. |
| **R&D cost uses absolute values of all costs** | ta_reallocation.py:67 | `sum(abs(rc.rd_cost))` — includes ALL years, even sunk costs before valuation year. The deterministic engine filters these out. This inflates the denominator of the efficiency ratio. |
| **Efficiency = NPV / Total R&D cost** | ta_reallocation.py:81 | Uses TOTAL R&D cost (all years), not just future R&D. This means a late-stage project with mostly sunk costs looks artificially inefficient. |
| **Optimal mix proportional to efficiency** | ta_reallocation.py:252 | Allocates budget proportionally to NPV/cost ratios. This ignores minimum viable investment thresholds — you can't do 15% of a Phase 3 trial. |
| **PTS uses ALL phase SRs** | ta_reallocation.py:19–23 | `_compute_pts()` multiplies ALL phase success rates, including phases already completed (before current_phase). The deterministic engine forces completed phases to SR=1.0. This makes PTS here artificially LOW. |

### 4. Consistency with portfolio simulation

**No portfolio sim equivalent exists for budget shift.** The portfolio sim has `budget_realloc` override type but it operates per-project, not per-TA. A TA budget shift cannot be directly expressed as portfolio sim overrides without manual decomposition into per-project budget changes.

The TA summary NPVs will match portfolio sim totals only if all snapshots have been recently calculated.

### 5. Production readiness

- **Will break if:** A TA has zero R&D cost → `efficiency = 0`, optimal_share = 0. That TA gets recommended DECREASE even if it has high NPV (e.g., an approved product with no remaining R&D). Misleading.
- **Will break if:** All TAs have negative NPV → all efficiencies are negative, `max(efficiency, 0)` forces all to 0, total_efficiency = 0, division by zero in optimal_share (ta_reallocation.py:252 has a guard, returns 0).
- **PTS understatement:** Using raw SR products instead of cumulative POS (which forces completed phases to 1.0) produces PTS values that are systematically too low for late-stage assets.

### 6. Verdict: APPROXIMATE — NEEDS FIX

The TA summary and efficiency ranking provide useful directional insights. The budget shift analysis is **materially misleading** due to the linear NPV-to-cost assumption and the all-years R&D cost denominator. The PTS calculation is **wrong** (doesn't respect current_phase). Priority fix: PTS calculation and future-only R&D costs.

---

## FAMILY C: Temporal Balance

### 1. What question it answers
**"When do portfolio revenues peak, where are the patent cliff gaps, and which years have launch clusters?"**

### 2. How it calculates the answer

**Launch Timeline** (temporal_balance.py:22–77):
Uses `snapshot.approval_date` as estimated launch year (truncated to integer). Falls back to hardcoded phase-to-months-remaining mapping if no snapshot.

**Revenue Gap Analysis** (temporal_balance.py:84–191):
```
Per year:
  Total_revenue = Σ commercial cashflow revenue across all projects (excluding R&D and Total scopes)
  YoY_change = revenue(year) - revenue(year-1)
  YoY_pct = YoY_change / |revenue(year-1)| × 100

Gap = year where YoY_pct < -15%
Severity: CRITICAL if < -30%, HIGH if < -20%, MODERATE if < -15%
```

**Temporal Heatmap** (temporal_balance.py:198–252):
Year × project matrix of `revenue - |costs|` from the Total-scope cashflows.

### 3. Approximations and shortcuts

| Approximation | Location | Impact |
|---|---|---|
| **Launch year = int(approval_date)** | temporal_balance.py:49 | Truncates fractional year. If approval_date = 2031.75, launch year shows as 2031. In practice, launch follows approval by 3–12 months. The deterministic engine uses `commercial_rows.launch_date` which can differ from `approval_date`. |
| **Hardcoded phase-remaining months** | temporal_balance.py:32–38 | Fallback uses fixed estimates (Phase 1 = 60 months, Phase 3 = 30 months). These vary enormously by therapeutic area — oncology Phase 3 can be 24 months, cardiovascular can be 60+. |
| **Revenue uses stored cashflows** | temporal_balance.py:100–108 | Reads pre-calculated deterministic cashflows. These are scenario-probability-weighted aggregates. If a project has multiple scenarios with different LOE dates, the revenue gap analysis sees the blended result, not the worst case. |
| **Heatmap uses revenue - |costs|** | temporal_balance.py:223 | `net = cf.revenue - abs(cf.costs)` — but `cf.costs` from the cashflow table is already negative for commercial rows (deterministic.py:284), so `abs(cf.costs)` would double-negate it. Need to verify sign conventions. |

### 4. Consistency with portfolio simulation

**Family C is purely analytical** — it does not modify NPV or create overrides. It reads stored cashflows. The data it shows will be consistent with the last deterministic NPV calculation for each project, but NOT with the portfolio sim (which may apply overrides that shift cashflows).

**Key divergence:** If a portfolio sim applied a `phase_delay` or `launch_delay` override, Family C's revenue gap analysis won't see it — it reads the original deterministic cashflows, not the override-adjusted ones. The temporal picture shown by Family C is always the **base case**, never the scenario.

### 5. Production readiness

- **Will work correctly** on real data as long as deterministic NPV has been calculated for each project (cashflows exist).
- **Missing: inactive project filter.** Revenue gap analysis iterates `portfolio.projects` but doesn't check `proj.is_active` (temporal_balance.py:95). Killed projects still contribute revenue to the temporal picture. This is a bug.
- **Heatmap sign issue:** The `abs(cf.costs)` on line 223 may cause incorrect net values if commercial costs are already stored as negative numbers in the cashflow table.

### 6. Verdict: CORRECT (with caveats)

The core logic is sound — it correctly reads and aggregates cashflow data. The two issues (inactive project filter missing, potential cost sign bug) should be fixed. The hardcoded phase-remaining estimates are acceptable as fallbacks. This family is primarily a visualization/reporting tool and doesn't need simulation-grade precision.

---

## FAMILY D: Innovation vs Risk Charter

### 1. What question it answers
**"How does our portfolio score on innovation, risk-return efficiency, and strategic charter compliance?"**

### 2. How it calculates the answer

**Risk-Return Scatter** (innovation_risk.py:40–83):
```
Per project:
  PTS = Π(all phase success rates)          ← SAME bug as Family B
  Risk = 1 - PTS
  Risk-Adjusted NPV = NPV × PTS            ← NOT the same as rNPV from engine
  Quadrant: Star / Question Mark / Cash Cow / Dog based on NPV≥0 and risk≤0.5
```

Efficient frontier: Pareto dominance on (NPV, risk) plane — project A dominates B if A has higher NPV AND lower risk.

**Innovation Score** (innovation_risk.py:118–209):
```
Total Score (0–100) = sum of 4 factors:
  Phase diversity:   min(unique_phases / 4, 1) × 25
  TA diversity:      min(unique_TAs / 3, 1) × 25
  Novelty:           (1 - avg_PTS) × 25
  Pipeline depth:    min(early_stage_ratio / 0.4, 1) × 25
```

**Charter Compliance** (innovation_risk.py:228–327):
Checks 4 criteria against configurable thresholds:
1. Innovation score >= target (default 60)
2. Portfolio PTS >= target (default 40%) — NPV-weighted average PTS
3. Max single project weight <= target (default 30%)
4. Phase diversity >= target (default 3 unique phases)

### 3. Approximations and shortcuts

| Approximation | Location | Impact |
|---|---|---|
| **PTS uses ALL phase SRs (same bug as Family B)** | innovation_risk.py:29–33 | Does NOT force completed phases to SR=1.0. A Phase 3 asset with Phase 1 SR=0.80, Phase 2 SR=0.65 shows PTS = 0.80 × 0.65 × ... instead of 1.0 × 1.0 × .... **Systematically understates PTS for late-stage assets.** |
| **Risk-adjusted NPV ≠ rNPV from engine** | innovation_risk.py:57 | `risk_adjusted_npv = npv × pts`. But the `npv` is ALREADY risk-adjusted (it's `snapshot.npv_deterministic` which includes PTRS). So this DOUBLE-COUNTS risk adjustment. The scatter plot shows an NPV figure that is `rNPV × raw_PTS`, which is `NPV × PTRS²` effectively. **Materially incorrect.** |
| **Novelty = 1 - avg_PTS** | innovation_risk.py:161 | Uses PTS as a proxy for novelty (riskier = more novel). This is a major conceptual stretch — many risky programs are not novel (reformulations in rare diseases). The `innovation_class` field on Asset (first_in_class, best_in_class, etc.) is available but not used here. |
| **Phase diversity maxes at 4** | innovation_risk.py:153 | `min(phases/4, 1.0)` — perfect score with 4 unique phases. But PHASE_ORDER has 5 phases + "Approved". Portfolios with full phase coverage can't score higher than those with 4. |
| **TA diversity maxes at 3** | innovation_risk.py:156 | `min(TAs/3, 1.0)` — perfect score with 3 TAs. Many pharma companies have 5–8 TAs. Above 3, no benefit. |
| **Quadrant classification uses NPV=0 cutoff** | innovation_risk.py:87–94 | "Cash Cow" is defined as NPV < 0 AND risk ≤ 0.5. In BCG matrix terminology, a "Cash Cow" has low growth but positive cashflow. This label is misused — NPV < 0 should be "Dog" regardless of risk. |

### 4. Consistency with portfolio simulation

Family D is purely analytical — no overrides created. However:

- **PTS diverges from the deterministic engine's cumulative POS.** The engine correctly handles current_phase; Family D does not.
- **Risk-adjusted NPV double-counts** — a user comparing Family D's `risk_adjusted_npv` with the engine's `npv_deterministic` will see very different numbers and may be confused.

### 5. Production readiness

- **Double risk adjustment** (innovation_risk.py:57) will produce misleading scatter plots for ALL real data. This is the most impactful bug in the family engines.
- **Quadrant labels** will confuse finance teams who expect BCG matrix semantics.
- Works correctly with real data otherwise — no crashes, no division by zero issues.

### 6. Verdict: NEEDS FIX

Two critical issues: (1) double risk adjustment in scatter plot, (2) PTS calculation doesn't respect current_phase. The innovation score's use of PTS-as-novelty is a design choice, not a bug, but it should at least use the `innovation_class` field if available. The charter compliance framework is well-structured but inherits the PTS bug.

---

## FAMILY E: BD Cut & Reinvest

### 1. What question it answers
**"Should we acquire an external asset via BD deal, and if so, which internal project should we cut to fund it?"**

### 2. How it calculates the answer

**BD Deal Valuation** (bd_modeling.py:31–108):
```
Annual_revenue = peak_sales × market_share × margin × (1 - royalty)

Revenue per year uses a HARDCODED ramp/decline:
  Year 1–2:  ramp = year / 3
  Year 3..N-2: ramp = 1.0
  Year N-1..N: ramp = (N - year + 1) / 3

PV = Σ [ revenue × ramp / (1 + WACC)^year_from_now ]
Risk_adjusted_PV = PV × PTS
Deal NPV = Risk_adjusted_PV - (upfront + milestones)
ROI = (Risk_adjusted_PV / total_cost - 1) × 100
```

**BD Cut & Reinvest** (bd_modeling.py:115–199):
Side-by-side comparison: current project NPV vs BD deal NPV. Simple subtraction.

**BD Scan** (bd_modeling.py:206–282):
Flags portfolio projects based on: low NPV, low PTS, high cost/NPV ratio. Priority ranking by flag severity.

### 3. Approximations and shortcuts

| Approximation | Location | Impact |
|---|---|---|
| **Completely different revenue curve model** | bd_modeling.py:56–62 | Uses a linear 3-year ramp-up, flat plateau, and symmetric 3-year ramp-down. The deterministic engine uses logistic S-curve + LOE cliff + linear erosion. **A BD deal is valued with a fundamentally different model than internal assets.** This makes NPV comparisons between internal and BD assets unreliable. |
| **No mid-year convention** | bd_modeling.py:64 | `pv = revenue / ((1 + wacc) ** year_from_now)` — year-end discounting. The deterministic engine uses mid-year convention (−0.5 offset). This systematically understates BD deal PV by ~4% at WACC=8.5%. |
| **No cost structure (COGS, OpEx, tax)** | bd_modeling.py:48 | `annual_revenue = peak_sales × share × margin × (1 − royalty)`. The "margin" parameter collapses all costs into one number. The deterministic engine uses separate COGS, distribution, operating cost, and tax rates. |
| **PTS as single number** | bd_modeling.py:74 | BD deals use a single flat PTS multiplier. Internal assets use per-phase cumulative POS. Not wrong for BD (where you're buying at a specific stage), but makes comparisons harder. |
| **Milestones not risk-adjusted** | bd_modeling.py:75–76 | `total_cost = upfront + milestones`. Milestone payments are typically contingent on clinical success and should be risk-adjusted. This overstates deal cost. |
| **PTS bug in BD scan** | bd_modeling.py:20–24 | Same `_compute_pts()` bug — doesn't respect current_phase. BD replacement candidates have understated PTS, making them look worse than they are. |

### 4. Consistency with portfolio simulation

**BD placeholder NPV in portfolio sim** (portfolio_sim.py:468–562) uses a DIFFERENT valuation model than `value_bd_deal()`:
- Portfolio sim uses logistic ramp + post-LOE erosion (matching the deterministic engine more closely)
- Portfolio sim applies revenue_share_pct and royalty separately
- Portfolio sim uses separate COGS and OpEx rates
- Portfolio sim has hardcoded `valuation_year = 2025` (portfolio_sim.py:474)

**So a BD deal valued by Family E will NOT match the same deal when added as a BD placeholder in the portfolio sim.** The revenue curve shape, cost model, and discounting convention all differ.

### 5. Production readiness

- **Hardcoded valuation_year = 2025** in portfolio_sim.py:384 and 474 — will be wrong in any other year. Should use the snapshot's valuation_year.
- **Missing distribution_rate** in both BD valuation models — internal assets deduct distribution costs, BD deals don't. Systematic bias.
- **BD scan works correctly** on real data — flag logic is straightforward and robust.

### 6. Verdict: NEEDS FIX

The BD valuation engine uses a fundamentally different model than the deterministic engine, making cross-comparisons unreliable. A BD deal that looks NPV-positive in Family E might look NPV-negative when properly modeled in the portfolio sim, or vice versa. The two models should converge. The hardcoded `valuation_year = 2025` is a ticking time bomb.

---

## FAMILY F: Concentration Risk

### 1. What question it answers
**"How concentrated is our portfolio, and what happens if our biggest projects fail?"**

### 2. How it calculates the answer

**HHI** (concentration.py:27–115):
```
HHI = Σ (share_i × 100)²
where share_i = |NPV_i| / Σ |NPV_i|
```
Computed across three dimensions: project, therapeutic area, and development phase.

Note: uses **absolute value** of NPV for shares (concentration.py:41).

**Top-N Dependency** (concentration.py:130–200):
```
Top-N share = Σ(top N project NPVs) / |total portfolio NPV| × 100
Risk: HIGH if > 60%, MODERATE if > 40%, LOW otherwise
```

**Diversification Score** (concentration.py:207–276):
```
Total (0–100) = sum of 4 factors:
  Project count:  min(N/10, 1) × 25
  TA spread:      max(0, 1 - HHI_TA/10000) × 25
  Phase balance:  max(0, 1 - HHI_phase/10000) × 25
  NPV balance:    max(0, 1 - HHI_project/10000) × 25
```

**Stress Test** (concentration.py:283–363):
```
For n = 1, 2, ..., N:
  NPV_lost = Σ(top-n project NPVs)
  Remaining_NPV = total - NPV_lost
  Loss_pct = NPV_lost / |total| × 100
  Severity: CRITICAL > 50%, HIGH > 30%, MODERATE > 15%, LOW otherwise
```

### 3. Approximations and shortcuts

| Approximation | Location | Impact |
|---|---|---|
| **HHI uses |NPV| (absolute values)** | concentration.py:41 | A project with NPV = −50 EUR mm contributes the same concentration as one with NPV = +50. This is defensible (both represent material portfolio exposure) but unusual. Standard HHI in finance uses positive market shares. A negative-NPV project inflating the denominator dilutes the apparent concentration. |
| **Top-N uses raw NPV (not absolute)** | concentration.py:147 | `projects.sort(key=x["npv"], reverse=True)`. Top projects are those with highest positive NPV. This is correct — concentration risk is about dependency on value creators, not value destroyers. BUT it uses raw NPV / |total| for share, and if total is near zero (positive and negative cancel), shares explode. |
| **Stress test is additive** | concentration.py:312–313 | `remaining_npv = total - lost`. Assumes project failures are independent and don't affect other projects. In pharma, competing internal projects may share clinical infrastructure — one failure could accelerate others. |
| **No correlation modeling** | — | Projects in the same TA or same mechanism of action are correlated. A clinical hold on a class of drugs could kill multiple projects simultaneously. HHI captures TA concentration but the stress test doesn't use it. |

### 4. Consistency with portfolio simulation

Family F is purely analytical — no overrides. Its NPV values come from `snapshot.npv_deterministic`, matching the base case. Stress test numbers will match `project_kill` overrides in the portfolio sim (both subtract NPV from total).

**One divergence:** Family F's stress test uses `snapshot.npv_deterministic`, while portfolio sim uses `portfolio.total_npv` as the baseline. If added projects or BD placeholders contribute to portfolio NPV, the stress test understates the total and overstates loss percentages.

### 5. Production readiness

- **Works correctly** on real data. No crashes, well-guarded against edge cases.
- **HHI = 10000 for single-project portfolios** — technically correct (maximum concentration) but the score/grade system handles this well.
- **Diversification score can reach 100 only with 10+ projects** (`min(N/10, 1)` factor). Small portfolios (3–5 assets, typical for small pharma) are penalized regardless of how well-diversified they are within that count.

### 6. Verdict: CORRECT

This is the most solid family engine. Calculations are standard (HHI is textbook), no approximation replaces a real calculation, and the stress test provides genuine strategic insight. The absolute-value HHI is a minor quirk but defensible. Ready for production.

---

## PORTFOLIO SIMULATION ORCHESTRATOR

### Key findings from `portfolio_sim.py`

The orchestrator is the bridge between family analyses and actual portfolio NPV. Critical issues:

**1. Override application is ALL approximation** (portfolio_sim.py:262–372)

Every override type except `project_kill` uses a rough approximation instead of recalculating:

| Override | Formula used | What it SHOULD do |
|---|---|---|
| `peak_sales_change` | `NPV × 0.7 × multiplier + NPV × 0.3` | Recalculate deterministic NPV with new peak sales |
| `sr_override` | `NPV × (new_SR / old_SR)` | Recalculate cumulative POS and re-run NPV |
| `phase_delay` | `NPV / (1+WACC)^delay` | Shift all cashflows forward and re-discount |
| `launch_delay` | `NPV / (1+avg_WACC)^delay` | Shift commercial cashflows and re-discount |
| `time_to_peak_change` | `NPV × (1 - 0.05 × Δyears)` | Recalculate revenue curve with new time_to_peak |
| `accelerate` | Complex formula with 0.7/0.3 split | Recalculate with shifted timeline and increased costs |
| `budget_realloc` | `commercial_portion - rd_portion × multiplier` | Recalculate with new R&D costs |

The `0.7 commercial / 0.3 R&D` split appears in **four** different override formulas (lines 291, 350, 358, 360). This is a single hardcoded constant that drives the entire portfolio simulation scenario analysis.

**2. Hardcoded `valuation_year = 2025`** (portfolio_sim.py:384, 474)

Both `_calculate_added_project_npv()` and `_calculate_bd_placeholder_npv()` use hardcoded 2025. This will produce incorrect discounting in any other year.

**3. Added project and BD placeholder NPV models diverge from deterministic engine**

The portfolio sim has its own mini-NPV calculators for hypothetical projects and BD placeholders. These use:
- Year-end discounting (no mid-year convention)
- A different logistic ramp function (`_logistic_ramp` at line 569 uses `k * (t - midpoint) / time_to_peak` vs the engine's `k * (τ - midpoint)`)
- No trapezoidal integration (point samples at integer years)
- Different LOE erosion formula: `1.0 - cliff_rate × (years/erosion_years)` vs engine's `cliff_level + (floor - cliff_level) × fraction`

**4. Override stacking**

Multiple overrides on the same project are applied sequentially (portfolio_sim.py:92–104). Each override modifies `npv_simulated` and the next override operates on the already-modified value. Order matters, but no ordering is guaranteed beyond database insertion order.

---

## CROSS-FAMILY SUMMARY

### Trust assessment

| Family | Engine | Trust Level | Reason |
|---|---|---|---|
| **F** | Concentration Risk | **CAN BE TRUSTED** | Standard HHI, straightforward arithmetic, no approximation substituting for calculation |
| **C** | Temporal Balance | **CAN BE TRUSTED** (with fixes) | Reads actual cashflow data, correct aggregation. Fix: add inactive project filter, verify cost sign |
| **A** | Kill / Continue / Accelerate | **DIRECTIONALLY USEFUL** | Kill analysis is exact. Acceleration uses rough formula — ok for screening, not for decisions |
| **D** | Innovation vs Risk Charter | **NEEDS FIX BEFORE USE** | Double risk-adjustment in scatter plot, PTS bug. Innovation score design is subjective but functional |
| **B** | TA Budget Reallocation | **NEEDS FIX BEFORE USE** | Linear NPV-cost assumption is materially misleading. PTS bug. R&D cost includes sunk costs |
| **E** | BD Cut & Reinvest | **NEEDS FIX BEFORE USE** | Different valuation model than deterministic engine makes comparisons unreliable |

### Which need the approximation replaced with a real simulation call?

1. **Portfolio sim override application** (portfolio_sim.py:262–372): The `0.7/0.3 split` approximations should be replaced with actual deterministic NPV recalculation. Each override should create a temporary modified snapshot, run `calculate_deterministic_npv()`, and use the actual result. This is the single highest-impact improvement.

2. **Family E BD valuation** (bd_modeling.py:31–108): Should use the same revenue curve + cost model as the deterministic engine rather than a bespoke simplified model.

3. **Family B budget shift** (ta_reallocation.py:154–159): The linear NPV-to-cost assumption should at minimum document its limitations. Ideally, it should identify which specific projects in the source TA would be cut and sum their actual NPVs.

### Priority order for fixing

| Priority | Item | Effort | Impact |
|---|---|---|---|
| **P0** | Fix `_compute_pts()` everywhere — must respect `current_phase` (Families B, D, E + portfolio sim) | LOW | Affects every PTS display across the system |
| **P0** | Fix double risk adjustment in Family D scatter (innovation_risk.py:57) | LOW | `risk_adjusted_npv` is currently `rNPV × raw_PTS ≈ NPV × PTRS²` |
| **P1** | Replace hardcoded `valuation_year = 2025` with dynamic value (portfolio_sim.py:384, 474) | LOW | Will break after 2025 |
| **P1** | Add inactive project filter in Family C (temporal_balance.py:95) | LOW | Killed projects currently show in temporal analysis |
| **P2** | Replace `0.7/0.3` override approximations with actual NPV recalculation (portfolio_sim.py:262–372) | MEDIUM-HIGH | Most impactful accuracy improvement but requires architectural change |
| **P2** | Align BD valuation model with deterministic engine (bd_modeling.py + portfolio_sim.py) | MEDIUM | Eliminates cross-model comparison errors |
| **P3** | Fix Family B R&D cost to use future-only costs | LOW | Improves efficiency metric accuracy |
| **P3** | Fix Family B linear NPV-cost assumption or add disclaimers | MEDIUM | Reduces misleading budget shift recommendations |

---

## APPENDIX: LINE-REFERENCED ISSUES (ALL FAMILIES)

| # | Sev | File:Line | Description |
|---|---|---|---|
| 1 | **CRITICAL** | innovation_risk.py:57 | `risk_adjusted_npv = npv * pts` double-counts risk (NPV is already risk-adjusted) |
| 2 | **HIGH** | innovation_risk.py:29–33 | `_compute_pts()` doesn't force completed phases to SR=1.0 |
| 3 | **HIGH** | ta_reallocation.py:19–23 | Same `_compute_pts()` bug |
| 4 | **HIGH** | bd_modeling.py:20–24 | Same `_compute_pts()` bug |
| 5 | **HIGH** | portfolio_sim.py:384, 474 | Hardcoded `valuation_year = 2025` |
| 6 | **HIGH** | portfolio_sim.py:291, 350, 358, 360 | `0.7/0.3` commercial/R&D split hardcoded across 4 override types |
| 7 | **HIGH** | bd_modeling.py:56–62 | Revenue curve model differs from deterministic engine |
| 8 | **MEDIUM** | ta_reallocation.py:154–155 | Linear NPV-to-cost assumption in budget shift |
| 9 | **MEDIUM** | ta_reallocation.py:158 | Marginal efficiency 70% haircut hardcoded |
| 10 | **MEDIUM** | ta_reallocation.py:67 | R&D cost includes sunk costs (all years, not future-only) |
| 11 | **MEDIUM** | acceleration.py:278 | `commercial_fraction = 0.7` hardcoded |
| 12 | **MEDIUM** | temporal_balance.py:95 | Missing `is_active` filter — killed projects appear in temporal analysis |
| 13 | **MEDIUM** | temporal_balance.py:223 | Potential cost sign issue with `abs(cf.costs)` |
| 14 | **MEDIUM** | portfolio_sim.py:569–581 | `_logistic_ramp()` uses different parameterization than revenue_curves.py |
| 15 | **MEDIUM** | portfolio_sim.py:410–411, 457 | No mid-year convention in added project / BD NPV calculators |
| 16 | **LOW** | acceleration.py:33–35 | Acceleration constants (α, max_multiplier, max_reduction) hardcoded |
| 17 | **LOW** | acceleration.py:262–265 | Phase cost fallback divides evenly across phases |
| 18 | **LOW** | innovation_risk.py:87–94 | "Cash Cow" quadrant label misused for NPV < 0 |
| 19 | **LOW** | concentration.py:41 | HHI uses |NPV| — defensible but non-standard |
| 20 | **LOW** | innovation_risk.py:153, 156 | Phase/TA diversity caps at 4/3 — arbitrary limits |

---

*End of review.*
