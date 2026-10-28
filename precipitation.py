"""Small prototype for classifying recent KNMI hourly precipitation."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class Observation:
    station: int
    timestamp: datetime
    precipitation_mm: float


@dataclass(frozen=True)
class Assessment:
    station: int | None
    window_start: datetime | None
    window_end: datetime | None
    precipitation_mm: float | None
    threshold_mm: float
    status: str

    def as_json(self) -> dict[str, object]:
        result = asdict(self)
        for key in ("window_start", "window_end"):
            value = result[key]
            result[key] = value.isoformat() if value is not None else None
        return result


def load_observations(path: Path) -> list[Observation]:
    """Read the comment-prefixed CSV format returned by KNMI."""
    with path.open(encoding="utf-8") as source:
        lines = list(source)
    header_line = next(
        (
            line.lstrip()[1:].strip()
            for line in lines
            if line.lstrip().startswith("#") and "STN,YYYYMMDD,HH" in line
        ),
        None,
    )
    if header_line is None:
        raise ValueError("KNMI CSV header not found")

    fieldnames = next(csv.reader([header_line], skipinitialspace=True))
    rows = (line for line in lines if line.strip() and not line.lstrip().startswith("#"))
    reader = csv.DictReader(rows, fieldnames=fieldnames, skipinitialspace=True)
    observations = []
    for row in reader:
        station = int(row["STN"].strip())
        date = datetime.strptime(row["YYYYMMDD"].strip(), "%Y%m%d")
        hour = int(row["HH"].strip())
        # KNMI hour 24 is the final hour of the indicated day.
        timestamp = date + timedelta(hours=hour)
        raw_amount = int(row["RH"].strip())
        amount_mm = 0.0 if raw_amount == -1 else raw_amount / 10
        observations.append(Observation(station, timestamp, amount_mm))
    return observations


def assess(
    observations: Sequence[Observation],
    window_hours: int = 3,
    threshold_mm: float = 10.0,
) -> Assessment:
    if window_hours < 1:
        raise ValueError("window_hours must be at least 1")
    if threshold_mm < 0:
        raise ValueError("threshold_mm cannot be negative")

    recent = sorted(observations, key=lambda observation: observation.timestamp)[-window_hours:]
    if not recent:
        return Assessment(None, None, None, None, threshold_mm, "INSUFFICIENT_DATA")
    if len(recent) < window_hours:
        return Assessment(
            recent[-1].station,
            recent[0].timestamp,
            recent[-1].timestamp,
            None,
            threshold_mm,
            "INSUFFICIENT_DATA",
        )

    total_mm = sum(observation.precipitation_mm for observation in recent)
    status = "ATTENTION" if total_mm >= threshold_mm else "NORMAL"
    return Assessment(
        recent[-1].station,
        recent[0].timestamp,
        recent[-1].timestamp,
        round(total_mm, 1),
        threshold_mm,
        status,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="KNMI hourly CSV file")
    parser.add_argument("--window-hours", type=int, default=3)
    parser.add_argument("--threshold-mm", type=float, default=10.0)
    args = parser.parse_args(argv)

    try:
        result = assess(load_observations(args.input), args.window_hours, args.threshold_mm)
    except (OSError, KeyError, ValueError) as error:
        print(f"Unable to assess precipitation: {error}", file=sys.stderr)
        return 2

    print(json.dumps(result.as_json(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
