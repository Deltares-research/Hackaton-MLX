# Will We Get Wet? 🌧️🚣

We are canoeing in Utrecht this afternoon. Build something that helps us decide whether we are going to regret that decision.

## Overview

The canoes are booked, but the weather is looking questionable. Do we grab a paddle, pack a raincoat, or find a cafe instead? This hackathon starts with a small prototype that processes KNMI precipitation observations from nearby De Bilt.

The starter looks at rain that has already fallen, not a forecast of this afternoon. Its status is a demonstration of recent rainfall conditions, not a prediction of whether we will get wet.

### Current behaviour

Given a local CSV of KNMI hourly precipitation observations for one station, the prototype:

1. Reads the station number, observation date/hour, and hourly precipitation (`RH`).
2. Converts `RH` from tenths of a millimetre to millimetres, treating KNMI's trace value (`-1`) as zero.
3. Considers the most recent three hourly observations. If their total is **at least 10.0 mm**, reports `ATTENTION`; otherwise reports `NORMAL`.
4. Reports `INSUFFICIENT_DATA` if there are fewer than three observations.
5. Emits a JSON result with station, window, total precipitation, threshold, and status.

This threshold is a simple exercise rule, not a weather warning or a canoeing safety criterion.

## Run it

With Python 3.12 or later:

```bash
python precipitation.py --input data/knmi_hourly_de_bilt.csv
```

Example output:

```json
{
  "station": 260,
  "window_start": "2024-01-03T22:00:00",
  "window_end": "2024-01-04T00:00:00",
  "precipitation_mm": 2.0,
  "threshold_mm": 10.0,
  "status": "NORMAL"
}
```

Override the threshold or window length with `--threshold-mm` and `--window-hours`. Run the tests with:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

## Data

The data files and example outputs in this repository are provided for the hackathon exercise only. They are not authoritative records or ground truth and should not be used for scientific or operational decisions.

`data/knmi_hourly_de_bilt.csv` is an exercise dataset adapted from KNMI hourly precipitation observations for station 260 (De Bilt), 1–3 January 2024. The `RH` field is in 0.1 mm; `-1` means less than 0.05 mm. The file retains KNMI's original source and measurement notes for context.

Source: [KNMI hourly observations](https://www.daggegevens.knmi.nl/klimatologie/uurgegevens), requested with station `260`, variable `RH`, dates `20240101`–`20240103`. The source notes that hourly time series may be inhomogeneous and are not suitable for climate-trend analysis. Consult the KNMI source for current data terms and metadata before redistributing or using data beyond this hackathon.

## Hackathon environment

Open the repository in a VS Code Dev Container to use the configured Python environment. GitHub Actions runs the test suite on pushes and pull requests.

All hackathon tasks are listed in [BACKLOG.md](BACKLOG.md). The existing code and tests are a deliberately small baseline, not a weather forecast or safety advisory. For a real trip, consult current official forecasts, warnings, and local water conditions.

## License

The project code and documentation are licensed under the [MIT License](LICENSE), copyright 2026 Deltares. KNMI-derived data remains subject to its source terms; the MIT License does not replace those terms.
