from datetime import datetime

import pytest

from precipitation import Observation, assess, load_observations


def observation(hour: int, amount_mm: float, station: int = 260) -> Observation:
    return Observation(station, datetime(2024, 1, 1, hour), amount_mm)


def test_reports_attention_at_threshold():
    result = assess([observation(1, 2), observation(2, 3), observation(3, 5)])

    assert result.status == "ATTENTION"
    assert result.precipitation_mm == 10.0


def test_reports_normal_below_threshold():
    result = assess(
        [observation(1, 2), observation(2, 3), observation(3, 4.9)])

    assert result.status == "NORMAL"
    assert result.precipitation_mm == 9.9


def test_uses_only_the_most_recent_window():
    result = assess(
        [observation(1, 100), observation(2, 1),
         observation(3, 2), observation(4, 3)]
    )

    assert result.precipitation_mm == 6
    assert result.window_start == datetime(2024, 1, 1, 2)


def test_returns_insufficient_data_for_short_window():
    result = assess([observation(1, 10), observation(2, 10)])

    assert result.status == "INSUFFICIENT_DATA"
    assert result.precipitation_mm is None


def test_returns_insufficient_data_for_empty_input():
    result = assess([])

    assert result.status == "INSUFFICIENT_DATA"
    assert result.station is None


def test_sorts_observations_by_timestamp():
    result = assess([observation(3, 3), observation(1, 1), observation(2, 2)])

    assert result.precipitation_mm == 6
    assert result.window_start == datetime(2024, 1, 1, 1)


def test_rejects_non_positive_window():
    with pytest.raises(ValueError, match="window_hours"):
        assess([], window_hours=0)


def test_loads_knmi_excerpt_and_converts_units():
    from pathlib import Path

    observations = load_observations(
        Path(__file__).parents[1] / "data/knmi_hourly_de_bilt.csv")

    assert observations[0].station == 260
    assert observations[0].precipitation_mm == 0
    assert observations[-1].precipitation_mm == 0
    assert assess(observations).status == "NORMAL"


def test_bundled_observations_have_non_negative_precipitation():
    from pathlib import Path

    observations = load_observations(
        Path(__file__).parents[1] / "data/knmi_hourly_de_bilt.csv")

    for observation in observations:
        assert observation.precipitation_mm >= 0, (
            f"Negative precipitation at station {observation.station} "
            f"on {observation.timestamp.isoformat()}: {observation.precipitation_mm} mm"
        )
