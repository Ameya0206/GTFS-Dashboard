"""
backend/validator/integrity_validator.py

Checks referential integrity across GTFS files.

Relationships checked (per CLAUDE.md spec):
  1. trips.txt   → routes.txt    : every route_id in trips must exist in routes
  2. stop_times.txt → trips.txt  : every trip_id in stop_times must exist in trips
  3. stop_times.txt → stops.txt  : every stop_id in stop_times must exist in stops
  4. trips.txt   → calendar      : every service_id in trips must exist in
                                   calendar.txt OR calendar_dates.txt (or both)

Design notes:
- All checks yield BLOCKER severity — broken foreign keys make the feed
  structurally invalid for the affected records.
- The count reported is the number of *records* with a broken reference, not
  the number of distinct bad IDs.  This gives operators a better sense of
  the blast radius.
- Checks are skipped gracefully when a referenced file is None (absent) — the
  absence itself is already flagged as a BLOCKER by file_validator.py.
- Checks are also skipped when the primary file is None or empty.
- Calendar check is an OR across calendar.txt and calendar_dates.txt: a
  service_id is valid if it appears in either (or both).
"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd

from backend.models.report import Issue, Severity


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_integrity(
    trips: Optional[pd.DataFrame],
    routes: Optional[pd.DataFrame],
    stop_times: Optional[pd.DataFrame],
    stops: Optional[pd.DataFrame],
    calendar: Optional[pd.DataFrame],
    calendar_dates: Optional[pd.DataFrame],
) -> List[Issue]:
    """
    Run all referential integrity checks.

    Parameters
    ----------
    trips, routes, stop_times, stops, calendar, calendar_dates:
        Parsed DataFrames (or None if the file was absent).

    Returns
    -------
    List of BLOCKER Issue objects for every broken reference found.
    """
    issues: List[Issue] = []

    issues.extend(_check_trips_routes(trips, routes))
    issues.extend(_check_stop_times_trips(stop_times, trips))
    issues.extend(_check_stop_times_stops(stop_times, stops))
    issues.extend(_check_trips_calendar(trips, calendar, calendar_dates))

    return issues


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_trips_routes(
    trips: Optional[pd.DataFrame],
    routes: Optional[pd.DataFrame],
) -> List[Issue]:
    """
    Every route_id in trips.txt must exist in routes.txt.
    """
    if _is_empty(trips, "route_id") or _is_empty(routes, "route_id"):
        return []

    valid_ids = set(routes["route_id"].dropna().unique())
    bad_mask = ~trips["route_id"].isin(valid_ids)
    bad_count = int(bad_mask.sum())

    if bad_count == 0:
        return []

    return [
        Issue(
            severity=Severity.BLOCKER,
            file="trips.txt",
            field="route_id",
            message=(
                f"{bad_count} trip record(s) reference route_id values not found "
                f"in routes.txt."
            ),
            count=bad_count,
        )
    ]


def _check_stop_times_trips(
    stop_times: Optional[pd.DataFrame],
    trips: Optional[pd.DataFrame],
) -> List[Issue]:
    """
    Every trip_id in stop_times.txt must exist in trips.txt.
    """
    if _is_empty(stop_times, "trip_id") or _is_empty(trips, "trip_id"):
        return []

    valid_ids = set(trips["trip_id"].dropna().unique())
    bad_mask = ~stop_times["trip_id"].isin(valid_ids)
    bad_count = int(bad_mask.sum())

    if bad_count == 0:
        return []

    return [
        Issue(
            severity=Severity.BLOCKER,
            file="stop_times.txt",
            field="trip_id",
            message=(
                f"{bad_count} stop_time record(s) reference trip_id values not "
                f"found in trips.txt."
            ),
            count=bad_count,
        )
    ]


def _check_stop_times_stops(
    stop_times: Optional[pd.DataFrame],
    stops: Optional[pd.DataFrame],
) -> List[Issue]:
    """
    Every stop_id in stop_times.txt must exist in stops.txt.
    """
    if _is_empty(stop_times, "stop_id") or _is_empty(stops, "stop_id"):
        return []

    valid_ids = set(stops["stop_id"].dropna().unique())
    bad_mask = ~stop_times["stop_id"].isin(valid_ids)
    bad_count = int(bad_mask.sum())

    if bad_count == 0:
        return []

    return [
        Issue(
            severity=Severity.BLOCKER,
            file="stop_times.txt",
            field="stop_id",
            message=(
                f"{bad_count} stop_time record(s) reference stop_id values not "
                f"found in stops.txt."
            ),
            count=bad_count,
        )
    ]


def _check_trips_calendar(
    trips: Optional[pd.DataFrame],
    calendar: Optional[pd.DataFrame],
    calendar_dates: Optional[pd.DataFrame],
) -> List[Issue]:
    """
    Every service_id in trips.txt must exist in calendar.txt OR calendar_dates.txt.

    The check is skipped (not flagged here) when both calendar files are absent,
    because calendar_validator.py already issues a BLOCKER for that condition.
    """
    if _is_empty(trips, "service_id"):
        return []

    # Build the set of valid service_ids from whichever calendar sources exist
    valid_ids: set = set()
    has_any_calendar = False

    if calendar is not None and "service_id" in calendar.columns:
        valid_ids.update(calendar["service_id"].dropna().unique())
        has_any_calendar = True

    if calendar_dates is not None and "service_id" in calendar_dates.columns:
        valid_ids.update(calendar_dates["service_id"].dropna().unique())
        has_any_calendar = True

    if not has_any_calendar:
        # calendar_validator.py will flag the missing calendar — skip here
        return []

    bad_mask = ~trips["service_id"].isin(valid_ids)
    bad_count = int(bad_mask.sum())

    if bad_count == 0:
        return []

    return [
        Issue(
            severity=Severity.BLOCKER,
            file="trips.txt",
            field="service_id",
            message=(
                f"{bad_count} trip record(s) reference service_id values not "
                f"found in calendar.txt or calendar_dates.txt."
            ),
            count=bad_count,
        )
    ]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _is_empty(df: Optional[pd.DataFrame], required_col: str) -> bool:
    """
    Return True if the DataFrame is None, has 0 rows, or is missing the
    required column.  Used to skip checks gracefully when data is absent.
    """
    if df is None:
        return True
    if len(df) == 0:
        return True
    if required_col not in df.columns:
        return True
    return False
