"""Risk adjustment: cumulative probability of success."""


def cumulative_pos(phase_inputs: list[dict], year: int) -> float:
    """Calculate cumulative POS for a given year.

    Multiplies the POS of all phases whose start_year <= year.
    Phases not yet started don't reduce the cumulative POS.
    """
    cum = 1.0
    for pi in sorted(phase_inputs, key=lambda x: x["start_year"]):
        if year >= pi["start_year"]:
            cum *= pi["probability_of_success"]
    return cum


def total_pos(phase_inputs: list[dict]) -> float:
    """Overall cumulative POS across all phases."""
    cum = 1.0
    for pi in phase_inputs:
        cum *= pi["probability_of_success"]
    return cum
