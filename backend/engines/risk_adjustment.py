"""
PharmaPulse — Risk Adjustment Module

Computes cumulative probability of success (POS) multipliers for
risk-adjusting R&D costs and commercial cashflows.

Rules from Spec Section 5.6:
    - Phases before current_phase: force SR = 1.0 (already succeeded)
    - R&D cost multiplier for phase i = product of SR for all phases before i
      (costs happen only if all PRIOR phases succeed)
    - Commercial multiplier = product of SR for ALL phases including Registration
      (revenue happens only if ALL phases succeed)

Phase order: Phase 1 → Phase 2 → Phase 2 B → Phase 3 → Registration
"""

from typing import Optional

# Canonical phase order (fixed)
PHASE_ORDER = ["Phase 1", "Phase 2", "Phase 2 B", "Phase 3", "Registration"]


def get_phase_index(phase_name: str) -> int:
    """
    Returns the index of a phase in the canonical phase order.
    Raises ValueError if phase not found.
    """
    try:
        return PHASE_ORDER.index(phase_name)
    except ValueError:
        raise ValueError(
            f"Unknown phase '{phase_name}'. Valid phases: {PHASE_ORDER}"
        )


def compute_cumulative_pos(
    phase_inputs: list,
    current_phase: str,
    sr_overrides: Optional[dict] = None,
) -> dict:
    """
    Computes cumulative probability of success multipliers for each phase
    and for commercial cashflows.

    Args:
        phase_inputs: List of dicts/objects with 'phase_name' and 'success_rate'.
                      Must cover all phases that exist for this asset.
        current_phase: The asset's current development phase (e.g., "Phase 3").
        sr_overrides: Optional dict of {phase_name: new_sr} from what-if levers.

    Returns:
        Dict with:
            - Per phase: {phase_name: {'sr': float, 'cost_multiplier': float}}
            - 'commercial_multiplier': float (product of ALL phase SRs)
            - 'cumulative_pos': float (same as commercial_multiplier)
    """
    current_idx = get_phase_index(current_phase)

    # Build SR map from inputs
    sr_map = {}
    for pi in phase_inputs:
        # Support both dict and ORM objects
        name = pi["phase_name"] if isinstance(pi, dict) else pi.phase_name
        sr = pi["success_rate"] if isinstance(pi, dict) else pi.success_rate
        sr_map[name] = sr

    # Apply overrides
    if sr_overrides:
        for phase_name, new_sr in sr_overrides.items():
            if new_sr is not None:
                sr_map[phase_name] = new_sr

    # Force SR = 1.0 for phases before current_phase (already succeeded)
    for i, phase_name in enumerate(PHASE_ORDER):
        if i < current_idx and phase_name in sr_map:
            sr_map[phase_name] = 1.0

    # Compute multipliers
    result = {}
    cumulative = 1.0

    for phase_name in PHASE_ORDER:
        if phase_name not in sr_map:
            continue

        sr = sr_map[phase_name]

        # Cost multiplier = product of SR for all phases BEFORE this one
        # (i.e., the cashflow in this phase occurs only if all prior phases succeeded)
        result[phase_name] = {
            "sr": sr,
            "cost_multiplier": cumulative,  # product of all SR before this phase
        }

        # Update cumulative to include this phase's SR
        cumulative *= sr

    # Commercial multiplier = product of ALL phases (after all phases succeed)
    result["commercial_multiplier"] = cumulative
    result["cumulative_pos"] = cumulative

    return result


def get_phase_cost_multiplier(pos_result: dict, phase_name: str) -> float:
    """
    Returns the cost multiplier for a specific phase from the POS result dict.
    """
    if phase_name in pos_result and isinstance(pos_result[phase_name], dict):
        return pos_result[phase_name]["cost_multiplier"]
    return 1.0


def get_commercial_multiplier(pos_result: dict) -> float:
    """
    Returns the commercial (revenue) multiplier from the POS result dict.
    """
    return pos_result.get("commercial_multiplier", 1.0)


