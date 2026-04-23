"""
backend/validator/field_validator.py

For each present GTFS file, checks:
  1. That all required fields (columns) are present          → BLOCKER if missing
  2. Null / empty value rates per required field             → WARNING if > 10 %
  3. Data type correctness for specific fields:
     - stop_lat, stop_lon  → numeric (float-parseable)
     - arrival_time, departure_time, start_time, end_time   → HH:MM:SS pattern

Design notes:
- "Null" is defined as pandas NaN *or* an empty string after the parser's
  whitespace strip.  Both are equivalent data absences for GTFS purposes.
- Type checks operate only on non-null values.  A field that is 100 % null
  already generates a WARNING for null rate; we do not additionally flag type
  errors on empty data.
- The null-rate threshold (NULL_RATE_THRESHOLD = 0.10) is a named constant so
  it can be adjusted without hunting through the code.
- Fields are defined per file; only the fields listed in REQUIRED_FIELDS are
  checked.  Extra columns in the feed are ignored (not an error).
- This module operates on pandas DataFrames, so it must only be called after
  the parser has run.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

import pandas as pd

from backend.models.report import Issue, Severity

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

NULL_RATE_THRESHOLD = 0.10   # Warn when more than 10 % of values are null/empty

# ---------------------------------------------------------------------------
# Required fields per GTFS file
# Sources: https://gtfs.org/schedule/reference/
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: Dict[str, List[str]] = {
    "agency.txt": [
        "agency_name",
        "agency_url",
        "agency_timezone",
    ],
    "stops.txt": [
        "stop_id",
        "stop_name",
        "stop_lat",
        "stop_lon",
    ],
    "routes.txt": [
        "route_id",
        "route_type",
    ],
    "trips.txt": [
        "route_id",
        "service_id",
        "trip_id",
    ],
    "stop_times.txt": [
        "trip_id",
        "arrival_time",
        "departure_time",
        "stop_id",
        "stop_sequence",
    ],
    "calendar.txt": [
        "service_id",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "start_date",
        "end_date",
    ],
    "calendar_dates.txt": [
        "service_id",
        "date",
        "exception_type",
    ],
    "shapes.txt": [
        "shape_id",
        "shape_pt_lat",
        "shape_pt_lon",
        "shape_pt_sequence",
    ],
    "feed_info.txt": [
        "feed_publisher_name",
        "feed_publisher_url",
        "feed_lang",
    ],
}

# ---------------------------------------------------------------------------
# Numeric fields — must be parseable as float
# ---------------------------------------------------------------------------

NUMERIC_FIELDS: Dict[str, List[str]] = {
    "stops.txt": ["stop_lat", "stop_lon"],
    "shapes.txt": ["shape_pt_lat", "shape_pt_lon"],
}

# ---------------------------------------------------------------------------
# Time fields — must match HH:MM:SS (HH can be >= 24 for overnight trips)
# ---------------------------------------------------------------------------

TIME_FIELDS: Dict[str, List[str]] = {
    "stop_times.txt": ["arrival_time", "departure_time"],
    "frequencies.txt": ["start_time", "end_time"],
}

_TIME_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_fields(
    filename: str,
    df: pd.DataFrame,
) -> List[Issue]:
    """
    Run all field-level checks for a single GTFS file.

    Parameters
    ----------
    filename:
        The GTFS filename string (e.g. "stops.txt").
    df:
        The parsed DataFrame for that file.  May be empty (0 rows).

    Returns
    -------
    List of Issue objects discovered during validation.
    """
    issues: List[Issue] = []

    required = REQUIRED_FIELDS.get(filename, [])

    # 1. Required field presence check
    missing_cols = _check_required_fields(filename, df, required)
    issues.extend(missing_cols)

    # Only proceed to value checks for fields that actually exist
    present_required = [f for f in required if f in df.columns]

    # 2. Null / empty rate per present required field
    if len(df) > 0:
        issues.extend(_check_null_rates(filename, df, present_required))

        # 3. Data type checks — numeric
        numeric_cols = NUMERIC_FIELDS.get(filename, [])
        for col in numeric_cols:
            if col in df.columns:
                issues.extend(_check_numeric_field(filename, df, col))

        # 4. Data type checks — time format
        time_cols = TIME_FIELDS.get(filename, [])
        for col in time_cols:
            if col in df.columns:
                issues.extend(_check_time_field(filename, df, col))

    return issues


def validate_all_fields(
    gtfs_frames: Dict[str, Optional[pd.DataFrame]],
) -> List[Issue]:
    """
    Run field validation across all present GTFS files.

    Parameters
    ----------
    gtfs_frames:
        Dict mapping filename → DataFrame (or None if file was absent).
        Absent files are skipped — file-level absence is reported by
        file_validator.py.

    Returns
    -------
    Aggregated list of Issue objects.
    """
    issues: List[Issue] = []
    for filename, df in gtfs_frames.items():
        if df is None:
            continue  # Absence handled by file_validator
        issues.extend(validate_fields(filename, df))
    return issues


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_required_fields(
    filename: str,
    df: pd.DataFrame,
    required: List[str],
) -> List[Issue]:
    """Return BLOCKER issues for each required field missing from df.columns."""
    issues: List[Issue] = []
    for field in required:
        if field not in df.columns:
            issues.append(
                Issue(
                    severity=Severity.BLOCKER,
                    file=filename,
                    field=field,
                    message=(
                        f"Required field '{field}' is missing from {filename}."
                    ),
                    count=None,
                )
            )
    return issues


def _check_null_rates(
    filename: str,
    df: pd.DataFrame,
    fields: List[str],
) -> List[Issue]:
    """
    Return WARNING issues for fields where the null/empty rate exceeds the
    NULL_RATE_THRESHOLD.

    Empty strings are treated as null for this check.
    """
    issues: List[Issue] = []
    total = len(df)
    if total == 0:
        return issues

    for field in fields:
        if field not in df.columns:
            continue  # Already reported as missing above
        col = df[field]
        # Count NaN and empty-string values
        null_count = col.isna().sum() + (col == "").sum()
        rate = null_count / total
        if rate > NULL_RATE_THRESHOLD:
            issues.append(
                Issue(
                    severity=Severity.WARNING,
                    file=filename,
                    field=field,
                    message=(
                        f"{filename}: field '{field}' has {null_count} null/empty "
                        f"values out of {total} rows "
                        f"({rate:.1%} — threshold is {NULL_RATE_THRESHOLD:.0%})."
                    ),
                    count=int(null_count),
                )
            )
    return issues


def _check_numeric_field(
    filename: str,
    df: pd.DataFrame,
    field: str,
) -> List[Issue]:
    """
    Return a WARNING if any non-null values in `field` cannot be parsed as float.
    """
    issues: List[Issue] = []
    col = df[field].dropna()
    col = col[col != ""]  # Exclude empties already caught by null check

    def _is_float(val: str) -> bool:
        try:
            float(val)
            return True
        except (ValueError, TypeError):
            return False

    bad = col[~col.apply(_is_float)]
    if len(bad) > 0:
        issues.append(
            Issue(
                severity=Severity.WARNING,
                file=filename,
                field=field,
                message=(
                    f"{filename}: field '{field}' has {len(bad)} value(s) that are "
                    f"not valid numbers (expected numeric lat/lon)."
                ),
                count=int(len(bad)),
            )
        )
    return issues


def _check_time_field(
    filename: str,
    df: pd.DataFrame,
    field: str,
) -> List[Issue]:
    """
    Return a WARNING if any non-null values in `field` do not match HH:MM:SS.

    GTFS allows hours >= 24 for overnight services, so we do not cap at 23.
    """
    issues: List[Issue] = []
    col = df[field].dropna()
    col = col[col != ""]

    bad = col[~col.apply(lambda v: bool(_TIME_RE.match(str(v))))]
    if len(bad) > 0:
        issues.append(
            Issue(
                severity=Severity.WARNING,
                file=filename,
                field=field,
                message=(
                    f"{filename}: field '{field}' has {len(bad)} value(s) that do "
                    f"not match the HH:MM:SS time format."
                ),
                count=int(len(bad)),
            )
        )
    return issues
