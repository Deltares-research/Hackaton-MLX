"""Forecast rainfall over a selected time window from sub-hourly observations."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NotRequired, Sequence, TypedDict

import numpy as np
from statsmodels.tsa.arima.model import ARIMA


class IntervalForecast(TypedDict):
    start_utc: str
    end_utc: str
    precipitation_mm: float


class EvaluationResult(TypedDict):
    observed_total_mm: float
    observed_rain: bool
    forecast_absolute_error_mm: float
    forecast_rain_correct: bool
    persistence_rain_correct: bool


class ForecastResult(TypedDict):
    window_start_utc: str
    window_end_utc: str
    as_of_utc: str
    latest_observation_utc: str
    latest_observation_mm: float
    training_observations: int
    interval_minutes: int
    arima_order: list[int]
    forecast_total_mm: float
    rain_threshold_mm: float
    forecast_predicts_rain: bool
    persistence_predicts_rain: bool
    interval_forecasts: list[IntervalForecast]
    evaluation: NotRequired[EvaluationResult]


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO timestamp with an explicit UTC offset."""
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"invalid ISO 8601 timestamp: {value!r}") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"timestamp must include a UTC offset: {value!r}")
    return timestamp.astimezone(timezone.utc)


def load_observations(path: Path) -> list[tuple[datetime, float]]:
    """Read end-of-interval UTC timestamps and precipitation totals in mm."""
    observations: list[tuple[datetime, float]] = []
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        required = {"timestamp_utc", "precipitation_mm"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("CSV must have timestamp_utc and precipitation_mm columns")
        for line, row in enumerate(reader, start=2):
            try:
                timestamp = parse_timestamp(row["timestamp_utc"])
                amount = float(row["precipitation_mm"])
            except (TypeError, ValueError) as error:
                raise ValueError(f"invalid observation on CSV line {line}: {error}") from error
            if not math.isfinite(amount) or amount < 0:
                raise ValueError(f"precipitation must be finite and non-negative on CSV line {line}")
            observations.append((timestamp, amount))
    observations.sort(key=lambda observation: observation[0])
    if any(a[0] == b[0] for a, b in zip(observations, observations[1:])):
        raise ValueError("duplicate timestamps in CSV")
    return observations


def forecast_window(
    observations: Sequence[tuple[datetime, float]],
    start: datetime,
    end: datetime,
    as_of: datetime,
    interval_minutes: int = 5,
    history_hours: int = 168,
    rain_threshold_mm: float = 0.1,
) -> ForecastResult:
    if interval_minutes <= 0 or history_hours <= 0:
        raise ValueError("interval-minutes and history-hours must be positive")
    if not math.isfinite(rain_threshold_mm) or rain_threshold_mm <= 0:
        raise ValueError("rain-threshold-mm must be finite and positive")
    if end <= start:
        raise ValueError("window end must be after window start")
    if as_of > start:
        raise ValueError("as-of cannot be later than the window start")
    interval = timedelta(minutes=interval_minutes)
    history_start = as_of - timedelta(hours=history_hours)
    history = [(timestamp, amount) for timestamp, amount in observations
               if history_start < timestamp <= as_of]
    if len(history) < 48:
        raise ValueError("at least 48 consecutive observations are required before as-of")
    for previous, current in zip(history, history[1:]):
        if current[0] - previous[0] != interval:
            raise ValueError(f"missing or irregular observations between {previous[0].isoformat()} and {current[0].isoformat()}")

    last_timestamp, last_amount = history[-1]
    start_offset, start_remainder = divmod(start - last_timestamp, interval)
    end_offset, end_remainder = divmod(end - last_timestamp, interval)
    if start_offset < 0 or start_remainder or end_remainder:
        raise ValueError("window boundaries must align with observation intervals")
    if end_offset > 10000:
        raise ValueError("forecast horizon exceeds 10,000 intervals; check timestamps")

    values = np.asarray([amount for _, amount in history], dtype=float)
    model = ARIMA(np.log1p(values), order=(1, 1, 1))
    fitted = model.fit()
    if not fitted.mle_retvals.get("converged", False):
        raise ValueError("ARIMA fit did not converge; inspect the observations or try another history window")
    transformed_forecasts = np.asarray(fitted.forecast(steps=end_offset), dtype=float)
    with np.errstate(over="ignore", invalid="ignore"):
        predicted = np.expm1(transformed_forecasts[start_offset:end_offset])
    if not np.all(np.isfinite(predicted)):
        raise ValueError("ARIMA produced non-finite forecasts")
    predicted = np.maximum(predicted, 0)
    total = float(np.sum(predicted))
    if not math.isfinite(total):
        raise ValueError("ARIMA produced a non-finite total")
    intervals: list[IntervalForecast] = [
        {
            "start_utc": (start + index * interval).isoformat(),
            "end_utc": (start + (index + 1) * interval).isoformat(),
            "precipitation_mm": float(amount),
        }
        for index, amount in enumerate(predicted)
    ]
    return {
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "as_of_utc": as_of.isoformat(),
        "latest_observation_utc": last_timestamp.isoformat(),
        "latest_observation_mm": last_amount,
        "training_observations": len(history),
        "interval_minutes": interval_minutes,
        "arima_order": [1, 1, 1],
        "forecast_total_mm": total,
        "rain_threshold_mm": rain_threshold_mm,
        "forecast_predicts_rain": total >= rain_threshold_mm,
        "persistence_predicts_rain": last_amount > 0,
        "interval_forecasts": intervals,
    }


def evaluate_window(
    observations: Sequence[tuple[datetime, float]],
    start: datetime,
    end: datetime,
    interval_minutes: int,
    result: ForecastResult,
) -> EvaluationResult:
    """Compare a historical forecast with complete observations in its window."""
    interval = timedelta(minutes=interval_minutes)
    window = [(timestamp, amount) for timestamp, amount in observations if start < timestamp <= end]
    expected_count = (end - start) // interval
    if (
        len(window) != expected_count
        or any(timestamp != start + (index + 1) * interval
               for index, (timestamp, _) in enumerate(window))
    ):
        raise ValueError("evaluation requires every observation in the forecast window")
    total = sum(amount for _, amount in window)
    observed_rain = total >= result["rain_threshold_mm"]
    return {
        "observed_total_mm": total,
        "observed_rain": observed_rain,
        "forecast_absolute_error_mm": abs(result["forecast_total_mm"] - total),
        "forecast_rain_correct": result["forecast_predicts_rain"] == observed_rain,
        "persistence_rain_correct": result["persistence_predicts_rain"] == observed_rain,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Normalized sub-hourly rainfall CSV")
    parser.add_argument("--start", required=True, help="Window start, ISO 8601 with UTC offset")
    parser.add_argument("--end", required=True, help="Window end, ISO 8601 with UTC offset")
    parser.add_argument("--as-of", help="Forecast issue time, ISO 8601 with UTC offset; defaults to now or start, whichever is earlier")
    parser.add_argument("--interval-minutes", type=int, default=5)
    parser.add_argument("--history-hours", type=int, default=168)
    parser.add_argument("--rain-threshold-mm", type=float, default=0.1)
    parser.add_argument("--evaluate", action="store_true", help="Compare with observations in a completed historical window")
    args = parser.parse_args(argv)
    try:
        start = parse_timestamp(args.start)
        end = parse_timestamp(args.end)
        now = datetime.now(timezone.utc)
        as_of = parse_timestamp(args.as_of) if args.as_of else min(now, start)
        if as_of > now:
            raise ValueError("as-of cannot be in the future")
        if args.evaluate and end > now:
            raise ValueError("evaluation requires a completed historical window")
        observations = load_observations(args.input)
        result = forecast_window(
            observations, start, end, as_of,
            args.interval_minutes, args.history_hours, args.rain_threshold_mm,
        )
        if args.evaluate:
            result["evaluation"] = evaluate_window(observations, start, end, args.interval_minutes, result)
    except (OSError, ValueError, np.linalg.LinAlgError) as error:
        print(f"Unable to forecast precipitation: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
