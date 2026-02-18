"""Tests for NPV calculation engines."""

import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.engines.discounting import mid_year_discount_factor
from backend.engines.risk_adjustment import cumulative_pos, total_pos
from backend.engines.revenue_curves import (
    linear_uptake, logistic_uptake, apply_loe_erosion, get_revenue,
)
from backend.engines.deterministic import run_deterministic_npv


class TestDiscounting:
    def test_mid_year_factor_year_zero(self):
        """Year 0 with mid-year convention should discount by 0.5 years."""
        df = mid_year_discount_factor(2025, 2025, 0.10)
        expected = 1.0 / (1.10 ** 0.5)
        assert abs(df - expected) < 1e-6

    def test_mid_year_factor_year_one(self):
        df = mid_year_discount_factor(2026, 2025, 0.10)
        expected = 1.0 / (1.10 ** 1.5)
        assert abs(df - expected) < 1e-6

    def test_mid_year_factor_zero_rate(self):
        df = mid_year_discount_factor(2030, 2025, 0.0)
        assert abs(df - 1.0) < 1e-6

    def test_mid_year_factor_negative_year(self):
        """Years before base should clamp to t=0."""
        df = mid_year_discount_factor(2020, 2025, 0.10)
        assert abs(df - 1.0) < 1e-6


class TestRiskAdjustment:
    def test_cumulative_pos_before_any_phase(self):
        phases = [
            {"phase_name": "P1", "probability_of_success": 0.6, "start_year": 2025},
            {"phase_name": "P2", "probability_of_success": 0.4, "start_year": 2027},
        ]
        assert cumulative_pos(phases, 2024) == 1.0

    def test_cumulative_pos_after_first_phase(self):
        phases = [
            {"phase_name": "P1", "probability_of_success": 0.6, "start_year": 2025},
            {"phase_name": "P2", "probability_of_success": 0.4, "start_year": 2027},
        ]
        assert abs(cumulative_pos(phases, 2025) - 0.6) < 1e-6

    def test_cumulative_pos_after_all_phases(self):
        phases = [
            {"phase_name": "P1", "probability_of_success": 0.6, "start_year": 2025},
            {"phase_name": "P2", "probability_of_success": 0.4, "start_year": 2027},
        ]
        assert abs(cumulative_pos(phases, 2028) - 0.24) < 1e-6

    def test_total_pos(self):
        phases = [
            {"phase_name": "P1", "probability_of_success": 0.5},
            {"phase_name": "P2", "probability_of_success": 0.5},
        ]
        assert abs(total_pos(phases) - 0.25) < 1e-6


class TestRevenueCurves:
    def test_linear_before_launch(self):
        assert linear_uptake(-1, 5, 1000) == 0.0

    def test_linear_at_launch(self):
        assert linear_uptake(0, 5, 1000) == 0.0

    def test_linear_mid_ramp(self):
        assert abs(linear_uptake(3, 5, 1000) - 600.0) < 1e-6

    def test_linear_at_peak(self):
        assert abs(linear_uptake(5, 5, 1000) - 1000.0) < 1e-6

    def test_linear_past_peak(self):
        assert abs(linear_uptake(10, 5, 1000) - 1000.0) < 1e-6

    def test_logistic_before_launch(self):
        assert logistic_uptake(-1, 5, 1000) == 0.0

    def test_logistic_at_peak(self):
        """Logistic should be close to peak at time_to_peak."""
        val = logistic_uptake(5, 5, 1000)
        assert val > 900  # Should be > 95% of peak

    def test_loe_erosion_before_expiry(self):
        assert apply_loe_erosion(1000, -1, 0.80) == 1000

    def test_loe_erosion_at_expiry(self):
        assert abs(apply_loe_erosion(1000, 0, 0.80) - 200) < 1e-6

    def test_loe_erosion_after_expiry(self):
        result = apply_loe_erosion(1000, 1, 0.80)
        assert result < 200  # Further erosion
        assert result > 0

    def test_get_revenue_before_launch(self):
        assert get_revenue(2025, 2030, 2042, 1000, 5, 0.80) == 0.0

    def test_get_revenue_at_launch(self):
        rev = get_revenue(2030, 2030, 2042, 1000, 5, 0.80)
        assert rev == 0.0  # year 0, linear starts at 0

    def test_get_revenue_mid_ramp(self):
        rev = get_revenue(2033, 2030, 2042, 1000, 5, 0.80, "linear")
        assert abs(rev - 600.0) < 1e-6

    def test_get_revenue_post_expiry(self):
        rev = get_revenue(2043, 2030, 2042, 1000, 5, 0.80, "linear")
        assert rev < 1000 * 0.25  # Significant erosion


class TestDeterministicNPV:
    def test_npv_produces_result(self, db_session, sample_snapshot):
        result = run_deterministic_npv(db_session, sample_snapshot)
        assert "enpv_usd_m" in result
        assert "cumulative_pos" in result
        assert "cashflows" in result
        assert len(result["cashflows"]) > 0

    def test_npv_has_correct_pos(self, db_session, sample_snapshot):
        result = run_deterministic_npv(db_session, sample_snapshot)
        # P2(0.4) * P3(0.55) * Filing(0.9) * Approval(0.95)
        expected_pos = 0.40 * 0.55 * 0.90 * 0.95
        assert abs(result["cumulative_pos"] - expected_pos) < 1e-4

    def test_npv_positive_for_good_asset(self, db_session, sample_snapshot):
        """A $1B peak sales asset should have positive NPV."""
        result = run_deterministic_npv(db_session, sample_snapshot)
        assert result["enpv_usd_m"] > 0

    def test_npv_saves_cashflows(self, db_session, sample_snapshot):
        from backend import models
        run_deterministic_npv(db_session, sample_snapshot)
        cfs = db_session.query(models.CashflowRow).filter(
            models.CashflowRow.snapshot_id == sample_snapshot.id
        ).all()
        assert len(cfs) > 0

    def test_unadjusted_greater_than_adjusted(self, db_session, sample_snapshot):
        result = run_deterministic_npv(db_session, sample_snapshot)
        # Unadjusted (divides by POS) should be larger
        assert result["unadjusted_npv_usd_m"] > result["risk_adjusted_npv_usd_m"]
