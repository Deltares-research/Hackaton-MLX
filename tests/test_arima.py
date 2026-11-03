import csv
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from arima.__main__ import (
    ForecastResult, evaluate_window, forecast_window, load_observations, parse_timestamp,
)


UTC = timezone.utc


def observations(end, count=100):
    return [
        (end - timedelta(minutes=5 * (count - 1 - index)), 0.1 if index % 3 == 0 else 0.0)
        for index in range(count)
    ]


def test_window_in_cet_uses_only_available_data_and_forecasts_through_lead_time(monkeypatch):
    latest = parse_timestamp("2026-11-03T13:00:00Z")
    start = parse_timestamp("2026-11-03T14:30:00+01:00")
    end = parse_timestamp("2026-11-03T16:30:00+01:00")
    data = observations(latest) + [(latest + timedelta(minutes=5), 99.0)]
    seen = {}

    def fake_arima(values, order):
        seen["values"] = values
        seen["order"] = order

        def forecast(steps):
            seen["steps"] = steps
            return np.log1p(np.arange(1, steps + 1) / 10)

        return SimpleNamespace(
            fit=lambda: SimpleNamespace(mle_retvals={"converged": True}, forecast=forecast)
        )

    monkeypatch.setattr("arima.__main__.ARIMA", fake_arima)
    result = forecast_window(data, start, end, latest)

    assert len(seen["values"]) == 100
    assert max(seen["values"]) < 1  # The later 99 mm observation was not used.
    assert seen["order"] == (1, 1, 1)
    assert seen["steps"] == 30
    assert result["window_start_utc"] == "2026-11-03T13:30:00+00:00"
    assert result["window_end_utc"] == "2026-11-03T15:30:00+00:00"
    intervals = result["interval_forecasts"]
    assert len(intervals) == 24
    assert intervals[0]["start_utc"] == result["window_start_utc"]
    assert intervals[-1]["end_utc"] == result["window_end_utc"]
    assert intervals[0]["precipitation_mm"] == pytest.approx(0.7)
    assert result["forecast_total_mm"] == pytest.approx(sum(np.arange(7, 31) / 10))
    assert result["persistence_predicts_rain"] is True


@pytest.mark.parametrize("value", ["2026-11-03T14:30:00", "not-a-date"])
def test_timestamp_requires_valid_offset(value):
    with pytest.raises(ValueError):
        parse_timestamp(value)


def test_rejects_gaps_and_misaligned_windows():
    latest = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    data = observations(latest)
    with pytest.raises(ValueError, match="missing or irregular"):
        forecast_window(data[:50] + data[51:], latest, latest + timedelta(hours=2), latest)
    with pytest.raises(ValueError, match="align"):
        forecast_window(data, latest + timedelta(minutes=1), latest + timedelta(hours=2), latest)
    with pytest.raises(ValueError, match="as-of"):
        forecast_window(data, latest, latest + timedelta(hours=2), latest + timedelta(minutes=5))


@pytest.mark.parametrize("value", ["-1", "nan", "", "inf"])
def test_rejects_missing_or_invalid_precipitation(tmp_path, value):
    path = tmp_path / "rain.csv"
    path.write_text(f"timestamp_utc,precipitation_mm\n2024-01-01T12:00:00Z,{value}\n")
    with pytest.raises(ValueError):
        load_observations(path)


def test_rejects_duplicate_timestamps_in_different_offsets(tmp_path):
    path = tmp_path / "rain.csv"
    path.write_text(
        "timestamp_utc,precipitation_mm\n"
        "2024-01-01T12:00:00Z,0\n2024-01-01T13:00:00+01:00,0\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_observations(path)


def test_evaluates_only_a_complete_window():
    start = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    end = start + timedelta(minutes=15)
    actual = [
        (start, 100.0),
        (start + timedelta(minutes=5), 0.1),
        (start + timedelta(minutes=10), 0.2),
        (end, 0.0),
    ]
    forecast: ForecastResult = {
        "window_start_utc": start.isoformat(), "window_end_utc": end.isoformat(),
        "as_of_utc": start.isoformat(), "latest_observation_utc": start.isoformat(),
        "latest_observation_mm": 0.0, "training_observations": 100,
        "interval_minutes": 5, "arima_order": [1, 1, 1], "interval_forecasts": [],
        "rain_threshold_mm": 0.1, "forecast_total_mm": 0.4,
        "forecast_predicts_rain": True, "persistence_predicts_rain": False,
    }
    evaluation = evaluate_window(actual, start, end, 5, forecast)
    assert evaluation["observed_total_mm"] == pytest.approx(0.3)
    assert evaluation["forecast_absolute_error_mm"] == pytest.approx(0.1)
    assert evaluation["forecast_rain_correct"] is True
    assert evaluation["persistence_rain_correct"] is False
    with pytest.raises(ValueError, match="every observation"):
        evaluate_window(actual[:-1], start, end, 5, forecast)


def test_cli_runs_real_model_with_historical_data(tmp_path):
    latest = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    path = tmp_path / "rain.csv"
    values = np.random.default_rng(42).exponential(0.1, 330)
    with path.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["timestamp_utc", "precipitation_mm"])
        for (timestamp, _), value in zip(
            observations(latest + timedelta(minutes=150), len(values)), values
        ):
            writer.writerow([timestamp.isoformat(), value])
    process = subprocess.run(
        [
            sys.executable, "-m", "arima", "--input", str(path),
            "--start", "2024-01-01T13:30:00+01:00",
            "--end", "2024-01-01T15:30:00+01:00",
            "--as-of", latest.isoformat(), "--evaluate",
        ],
        capture_output=True, text=True, check=True,
    )
    result = json.loads(process.stdout)
    assert result["training_observations"] == 300
    assert len(result["interval_forecasts"]) == 24
    assert result["forecast_total_mm"] >= 0
    assert result["window_start_utc"] == "2024-01-01T12:30:00+00:00"
    assert result["evaluation"]["observed_total_mm"] == pytest.approx(sum(values[306:330]))
