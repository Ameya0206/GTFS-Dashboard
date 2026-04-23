"""
backend/validator/calendar_validator.py

Validates calendar coverage in the GTFS feed.

Three valid states (per GTFS spec):
  1. calendar.txt only         — normal, fully supported
  2. calendar_dates.txt only   — valid; used for exception-only schedules
  3. Both files present        — valid; calendar_dates may override calendar

One invalid state:
  4. Neither file present      — BLOCKER; trips cannot be assigned to service days

Additional checks performed when the files are present:
  - calendar.txt: verifies that the weekday columns contain only "0" or "1"
    and that start_date <= end_date (WARNING if violated).
  - calendar_dates.txt: verifies that exception_type is "1" or "2" (WARNING).

Design notes:
- Date ordering check (start_date <= end_date) is a WARNING, not a BLOCKER,
  because the feed may still be partially usable.
- Malformed weekday flags are WARNING because a subset of services may still
  be valid.
- The function returns a tuple (issues, service_ids, service_days) so the
  orchestrator can pass service day information to the insights layer without
  re-scanning the DataFrames.
"""

from __future__ import annotations

from typing import List, Optional, Set, Tuple

import pandas as pd

from backend.models.report import Issue, Severity

# Weekday column names in calendar.txt
WEEKDAY_COLUMNS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

VALID_WEEKDAY_VALUES = {"0", "1"}
VALID_EXCEPTION_TYPES = {"1", "2"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_calendar(
    calendar: Optional[pd.DataFrame],
    calendar_dates: Optional[pd.DataFrame],
) -> Tuple[List[Issue], Set[str], List[str]]:
    """
    Validate calendar presence and content.

    Parameters
    ----------
    calendar:
        Parsed calendar.txt DataFrame, or None if absent.
    calendar_dates:
        Parsed calendar_dates.txt DataFrame, or None if absent.

    Returns
    -------
    issues:
        List of Issue objects found during validation.
    service_ids:
        Set of all service_id values defined across both calendar sources.
        Used by the integrity validator and insights layer.
    service_days:
        List of weekday names that are active in at least one service row
        (derived from calendar.txt only; empty if only calendar_dates.txt is
        present, because that file does not encode weekday patterns directly).
    """
    issues: List[Issue] = []
    service_ids: Set[str] = set()
    service_days: List[str] = []

    calendar_present = calendar is not None and len(calendar) > 0
    calendar_dates_present = calendar_dates is not None and len(calendar_dates) > 0

    # --- BLOCKER: neither calendar file present ---
    if not calendar_present and not calendar_dates_present:
        issues.append(
            Issue(
                severity=Severity.BLOCKER,
                file="calendar.txt / calendar_dates.txt",
                field=None,
                message=(
                    "Neither calendar.txt nor calendar_dates.txt is present. "
                    "Service schedules cannot be determined."
                ),
                count=None,
            )
        )
        return issues, service_ids, service_days

    # --- calendar.txt checks ---
    if calendar_present:
        cal_issues, cal_service_ids, cal_service_days = _validate_calendar_txt(calendar)
        issues.extend(cal_issues)
        service_ids.update(cal_service_ids)
        service_days = cal_service_days

    # --- calendar_dates.txt checks ---
    if calendar_dates_present:
        cd_issues, cd_service_ids = _validate_calendar_dates_txt(calendar_dates)
        issues.extend(cd_issues)
        service_ids.update(cd_service_ids)

    return issues, service_ids, service_days


# ---------------------------------------------------------------------------
# Per-file validators
# ---------------------------------------------------------------------------

def _validate_calendar_txt(
    calendar: pd.DataFrame,
) -> Tuple[List[Issue], Set[str], List[str]]:
    """
    Validate calendar.txt content.

    Checks:
    - Weekday flag columns contain only "0" or "1"
    - start_date <= end_date (lexicographic comparison; YYYYMMDD format sorts
      correctly as strings)

    Returns (issues, service_ids, active_service_days).
    """
    issues: List[Issue] = []
    service_ids: Set[str] = set()
    active_days: List[str] = []

    # Collect service_ids
    if "service_id" in calendar.columns:
        service_ids = set(calendar["service_id"].dropna().unique())

    total = len(calendar)

    # Weekday flag validation
    for day in WEEKDAY_COLUMNS:
        if day not in calendar.columns:
            # Missing weekday columns reported by field_validator — skip here
            continue

        col = calendar[day].dropna().astype(str)
        bad = col[~col.isin(VALID_WEEKDAY_VALUES)]
        if len(bad) > 0:
            issues.append(
                Issue(
                    severity=Severity.WARNING,
                    file="calendar.txt",
                    field=day,
                    message=(
                        f"calendar.txt: field '{day}' has {len(bad)} value(s) "
                        f"that are not '0' or '1'."
                    ),
                    count=int(len(bad)),
                )
            )

        # Track which days are active in at least one service row
        if "1" in col.values:
            active_days.append(day)

    # Date ordering check: start_date <= end_date
    if "start_date" in calendar.columns and "end_date" in calendar.columns:
        valid_rows = calendar[
            calendar["start_date"].notna() & calendar["end_date"].notna()
        ]
        if len(valid_rows) > 0:
            bad_dates = valid_rows[
                valid_rows["start_date"].astype(str) > valid_rows["end_date"].astype(str)
            ]
            if len(bad_dates) > 0:
                issues.append(
                    Issue(
                        severity=Severity.WARNING,
                        file="calendar.txt",
                        field="start_date",
                        message=(
                            f"calendar.txt: {len(bad_dates)} service row(s) have "
                            f"start_date after end_date."
                        ),
                        count=int(len(bad_dates)),
                    )
                )

    return issues, service_ids, active_days


def _validate_calendar_dates_txt(
    calendar_dates: pd.DataFrame,
) -> Tuple[List[Issue], Set[str]]:
    """
    Validate calendar_dates.txt content.

    Checks:
    - exception_type is "1" (added) or "2" (removed)

    Returns (issues, service_ids).
    """
    issues: List[Issue] = []
    service_ids: Set[str] = set()

    if "service_id" in calendar_dates.columns:
        service_ids = set(calendar_dates["service_id"].dropna().unique())

    if "exception_type" in calendar_dates.columns:
        col = calendar_dates["exception_type"].dropna().astype(str)
        bad = col[~col.isin(VALID_EXCEPTION_TYPES)]
        if len(bad) > 0:
            issues.append(
                Issue(
                    severity=Severity.WARNING,
                    file="calendar_dates.txt",
                    field="exception_type",
                    message=(
                        f"calendar_dates.txt: {len(bad)} row(s) have exception_type "
                        f"values other than '1' (added) or '2' (removed)."
                    ),
                    count=int(len(bad)),
                )
            )

    return issues, service_ids
