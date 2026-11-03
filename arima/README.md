# ARIMA rainfall experiment

This prototype fits an ARIMA(1,1,1) model to recent rainfall at one location,
then predicts the accumulated rainfall during a requested window. For the
canoeing trip on 3 November 2026, 14:30–16:30 Utrecht time (CET) is
13:30–15:30 UTC. Unlike the hourly exercise in the main README, the input
needs observations with boundaries that align with both half hours. The default
is a five-minute series. This is a statistical experiment, not an official
forecast or a safety advisory.

## Data for the gathering team

Produce a UTF-8 CSV with the exact columns below. Each row is the rainfall
**accumulated during the preceding five minutes** at one consistent location
(e.g. De Bilt station 260, or a single radar pixel near the trip), in
millimetres. `timestamp_utc` marks the **end** of the interval, includes a
UTC offset, and must be unique. For example:

```csv
timestamp_utc,precipitation_mm
2026-11-03T10:00:00Z,0.0
2026-11-03T10:05:00Z,0.1
2026-11-03T10:10:00Z,0.0
```

These are illustrative rows, not real observations. Obtain a contiguous
history as close to the forecast issue time as possible: the default fit uses
the preceding seven days, with at least 48 intervals required. The model
rejects gaps, duplicates, negative values and missing/non-finite amounts;
**do not fill missing measurements with zero**. Document the source, location,
units, time conventions, coverage, and any conversions. The data team must
verify that their chosen KNMI product actually supplies five-minute amounts:
convert rates to interval totals and cumulative readings to increments as
appropriate. If using radar, extract a consistent Utrecht-area pixel and
account for the product's timestamps and units. Do not mix station observations
with radar in one series. KNMI terms apply to its data.

The loader expects this normalized CSV, not the raw KNMI API or the hourly
KNMI CSV in this repository. No downloader or raw radar-to-CSV conversion is
included. If the team has another regular resolution, use `--interval-minutes`
and ensure both window boundaries align with that resolution.

## Run

Install the project's dependencies (Python 3.12+):

```bash
python -m pip install -e ".[dev]"
python -m arima --input data/rain_5min.csv \
  --start 2026-11-03T14:30:00+01:00 \
  --end 2026-11-03T16:30:00+01:00
```

The command emits JSON containing each interval forecast, their sum, the
latest observation and issue time in UTC, and a simple persistence prediction
("rain now means rain in the window"). `forecast_predicts_rain` uses an
exercise threshold of 0.1 mm over the whole window; change it with
`--rain-threshold-mm`. This is not a calibrated probability.

By default the issue time is the earlier of the current time and window start.
Only observations ending at or before that time enter the fit; forecasts
first cover the lead time to the window, then the requested window itself.
Inspect `latest_observation_utc`: stale input means a longer, less reliable
forecast. For a reproducible historical replay, pass `--as-of` with an
offset-aware timestamp at or before the window start. This is a retrospective
simulation, not a forecast made at that time.

The fit uses `log1p(mm)` and converts predictions back with `expm1`, clipping
negative amounts to zero. This does not yield a calibrated probability or
necessarily an unbiased expected total. ARIMA cannot see approaching rain
clouds, and optimization can fail, particularly with constant dry data; the
program reports failure rather than silently presenting a forecast.

To evaluate one completed historical window, add `--evaluate` and provide
complete observations through its end. The output includes observed total,
the forecast's absolute error, and whether the model and persistence correctly
predicted rain. Future observations are used only for evaluation, never for the
fit. Replay multiple held-out windows with explicit `--as-of` times and
summarize the results before trusting the method: a single window proves
little. The default persistence rule extends "rain now means rain next hour"
to the entire requested window. No historical results or live forecast are
provided by this repository yet.
