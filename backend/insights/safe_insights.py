"""
backend/insights/safe_insights.py

Derives consultant-grade insights ONLY from data that has passed validation.

Insights produced:
  Basic counts       — routes, stops, trips, agencies, service days
  Feed validity      — start/end date, days until expiry
  Network health     — service patterns, avg stops/trip, transfer hubs
  Accessibility      — wheelchair accessible %, non-accessible trip count
  Data quality       — timed stop % (affects trip planners / Google Maps)
  Per-route detail   — headways, service span, timed stops, accessibility, flags

Design invariants:
  - Any insight that cannot be safely derived is set to None, never guessed.
  - This module never reads from files flagged as not usable.
  - Headways are computed per-direction per-route and averaged; overnight gaps
    (> 120 min) are excluded so end-of-service doesn't inflate the average.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from backend.models.report import (
    RouteDetail,
    SafeInsights,
    TransferHub,
    UsableData,
)
from backend.parser.gtfs_parser import GTFSData

logger = logging.getLogger(__name__)

_WEEKDAY_COLUMNS = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]

# Flags applied to RouteDetail
_FLAG_LOW_FREQUENCY = "LOW_FREQUENCY"           # < 10 trips
_FLAG_ADA_GAP = "ADA_GAP"                       # any non-accessible trips
_FLAG_POOR_TIMING_DATA = "POOR_TIMING_DATA"     # timed_stop_pct < 25%
_FLAG_INFREQUENT_SERVICE = "INFREQUENT_SERVICE" # avg headway > 60 min
_FLAG_SINGLE_DIRECTION = "SINGLE_DIRECTION"     # trips in only one direction

# Transfer hub threshold
_TRANSFER_MIN_ROUTES = 3


def derive_safe_insights(
    gtfs_data: GTFSData,
    usable_data: UsableData,
) -> Tuple[SafeInsights, List[str]]:
    """
    Derive safe insights from validated data only.

    Returns
    -------
    safe_insights : SafeInsights
    skipped       : list of human-readable skip reasons
    """
    skipped: List[str] = []

    # ------------------------------------------------------------------
    # Basic counts
    # ------------------------------------------------------------------
    route_count = _safe_count(gtfs_data.routes, "route_id", usable_data.routes,
                               "route_count", skipped)
    stop_count  = _safe_count(gtfs_data.stops,  "stop_id",  usable_data.stops,
                               "stop_count",  skipped)
    trip_count  = _safe_count(gtfs_data.trips,  "trip_id",  usable_data.trips,
                               "trip_count",  skipped)

    agency_count: Optional[int] = None
    if gtfs_data.agency is not None and len(gtfs_data.agency) > 0:
        agency_count = len(gtfs_data.agency)
    else:
        skipped.append("agency_count: skipped — agency.txt absent or empty.")

    service_days = _derive_service_days(gtfs_data.calendar, usable_data.service_calendar, skipped)

    # ------------------------------------------------------------------
    # Feed validity window (from feed_info.txt — optional file)
    # ------------------------------------------------------------------
    feed_start_date: Optional[str] = None
    feed_end_date:   Optional[str] = None
    feed_expiry_days: Optional[int] = None

    fi = gtfs_data.feed_info
    if fi is not None and len(fi) > 0:
        feed_start_date = _col_val(fi, "feed_start_date")
        feed_end_date   = _col_val(fi, "feed_end_date")
        if feed_end_date:
            try:
                expiry = datetime.strptime(feed_end_date, "%Y%m%d")
                feed_expiry_days = (expiry - datetime.today()).days
            except ValueError:
                skipped.append("feed_expiry_days: could not parse feed_end_date.")
    else:
        skipped.append("feed validity: feed_info.txt absent — start/end dates unavailable.")

    # ------------------------------------------------------------------
    # Service pattern count (distinct service_ids in calendar.txt)
    # ------------------------------------------------------------------
    service_pattern_count: Optional[int] = None
    if usable_data.service_calendar and gtfs_data.calendar is not None and len(gtfs_data.calendar) > 0:
        if "service_id" in gtfs_data.calendar.columns:
            service_pattern_count = gtfs_data.calendar["service_id"].nunique()
    else:
        skipped.append("service_pattern_count: skipped — calendar.txt not usable.")

    # ------------------------------------------------------------------
    # Avg stops per trip
    # ------------------------------------------------------------------
    avg_stops_per_trip: Optional[float] = None
    if usable_data.trips and gtfs_data.stop_times is not None and len(gtfs_data.stop_times) > 0:
        st = gtfs_data.stop_times
        if "trip_id" in st.columns and "stop_sequence" in st.columns:
            counts = st.groupby("trip_id")["stop_sequence"].count()
            avg_stops_per_trip = round(float(counts.mean()), 1)
    else:
        skipped.append("avg_stops_per_trip: skipped — trips or stop_times not usable.")

    # ------------------------------------------------------------------
    # Accessibility
    # ------------------------------------------------------------------
    wheelchair_accessible_pct: Optional[float] = None
    non_accessible_trip_count: Optional[int] = None

    if usable_data.trips and gtfs_data.trips is not None and len(gtfs_data.trips) > 0:
        trips_df = gtfs_data.trips
        if "wheelchair_accessible" in trips_df.columns:
            total = len(trips_df)
            accessible = (trips_df["wheelchair_accessible"].astype(str).str.strip() == "1").sum()
            non_accessible_trip_count = int((trips_df["wheelchair_accessible"].astype(str).str.strip() == "0").sum())
            wheelchair_accessible_pct = round(accessible / total * 100, 1) if total > 0 else None
        else:
            skipped.append("wheelchair_accessible_pct: skipped — field absent in trips.txt.")
    else:
        skipped.append("wheelchair_accessible_pct: skipped — trips not usable.")

    # ------------------------------------------------------------------
    # Timed stop % (overall)
    # ------------------------------------------------------------------
    timed_stop_pct: Optional[float] = None
    if usable_data.trips and gtfs_data.stop_times is not None and len(gtfs_data.stop_times) > 0:
        st = gtfs_data.stop_times
        if "arrival_time" in st.columns:
            total = len(st)
            timed = (st["arrival_time"].notna() & (st["arrival_time"].str.strip() != "")).sum()
            timed_stop_pct = round(timed / total * 100, 1) if total > 0 else None
    else:
        skipped.append("timed_stop_pct: skipped — stop_times not usable.")

    # ------------------------------------------------------------------
    # Transfer hubs (stops served by 3+ routes)
    # ------------------------------------------------------------------
    transfer_hubs: Optional[List[TransferHub]] = None
    if (usable_data.trips and usable_data.stops
            and gtfs_data.stop_times is not None
            and gtfs_data.trips is not None
            and gtfs_data.stops is not None):
        transfer_hubs = _derive_transfer_hubs(
            gtfs_data.stop_times, gtfs_data.trips, gtfs_data.routes, gtfs_data.stops
        )
    else:
        skipped.append("transfer_hubs: skipped — stop_times, trips, or stops not usable.")

    # ------------------------------------------------------------------
    # Per-route detail
    # ------------------------------------------------------------------
    routes_detail: Optional[List[RouteDetail]] = None
    if (usable_data.routes and usable_data.trips
            and gtfs_data.routes is not None
            and gtfs_data.trips is not None
            and gtfs_data.stop_times is not None):
        routes_detail = _derive_routes_detail(
            gtfs_data.routes, gtfs_data.trips, gtfs_data.stop_times
        )
    else:
        skipped.append("routes_detail: skipped — routes, trips, or stop_times not usable.")

    return (
        SafeInsights(
            route_count=route_count,
            stop_count=stop_count,
            trip_count=trip_count,
            agency_count=agency_count,
            service_days=service_days,
            feed_start_date=feed_start_date,
            feed_end_date=feed_end_date,
            feed_expiry_days=feed_expiry_days,
            service_pattern_count=service_pattern_count,
            avg_stops_per_trip=avg_stops_per_trip,
            transfer_hubs=transfer_hubs,
            wheelchair_accessible_pct=wheelchair_accessible_pct,
            non_accessible_trip_count=non_accessible_trip_count,
            timed_stop_pct=timed_stop_pct,
            routes_detail=routes_detail,
        ),
        skipped,
    )


# ---------------------------------------------------------------------------
# Per-route detail computation
# ---------------------------------------------------------------------------

def _derive_routes_detail(
    routes_df: pd.DataFrame,
    trips_df: pd.DataFrame,
    stop_times_df: pd.DataFrame,
) -> List[RouteDetail]:
    """Build a RouteDetail entry for every route."""

    # Pre-compute first stop per trip for headway/span calculation
    st = stop_times_df.copy()
    st["_seq"] = pd.to_numeric(st.get("stop_sequence", pd.Series(dtype=str)), errors="coerce")
    first_stops = (
        st.dropna(subset=["_seq"])
        .sort_values("_seq")
        .groupby("trip_id")
        .first()
        .reset_index()[["trip_id", "departure_time"]]
    )

    # Merge trips with first-stop departure times
    trips_with_dep = trips_df.merge(first_stops, on="trip_id", how="left")

    # Pre-compute timed stop % per route
    st_with_route = st.merge(
        trips_df[["trip_id", "route_id"]], on="trip_id", how="left"
    )

    results: List[RouteDetail] = []

    for _, route_row in routes_df.iterrows():
        rid = str(route_row.get("route_id", ""))
        short_name = _str_or_none(route_row.get("route_short_name"))
        long_name  = _str_or_none(route_row.get("route_long_name"))

        route_trips = trips_with_dep[trips_with_dep["route_id"] == rid]
        trip_count = len(route_trips)

        # Service span
        first_dep, last_dep = _service_span(route_trips)

        # Headway
        avg_headway = _avg_headway(route_trips)

        # Timed stop coverage
        route_st = st_with_route[st_with_route["route_id"] == rid]
        timed_pct: Optional[float] = None
        if len(route_st) > 0 and "arrival_time" in route_st.columns:
            timed = (
                route_st["arrival_time"].notna()
                & (route_st["arrival_time"].str.strip() != "")
            ).sum()
            timed_pct = round(timed / len(route_st) * 100, 1)

        # Wheelchair accessibility
        wc_pct: Optional[float] = None
        if trip_count > 0 and "wheelchair_accessible" in route_trips.columns:
            accessible = (route_trips["wheelchair_accessible"].astype(str).str.strip() == "1").sum()
            wc_pct = round(accessible / trip_count * 100, 1)

        # Direction coverage
        directions: set = set()
        if "direction_id" in route_trips.columns:
            directions = set(route_trips["direction_id"].dropna().astype(str).unique())

        # Flags
        flags: List[str] = []
        if trip_count < 10:
            flags.append(_FLAG_LOW_FREQUENCY)
        if wc_pct is not None and wc_pct < 100.0:
            flags.append(_FLAG_ADA_GAP)
        if timed_pct is not None and timed_pct < 25.0:
            flags.append(_FLAG_POOR_TIMING_DATA)
        if avg_headway is not None and avg_headway > 60.0:
            flags.append(_FLAG_INFREQUENT_SERVICE)
        if len(directions) < 2 and trip_count > 1:
            flags.append(_FLAG_SINGLE_DIRECTION)

        results.append(RouteDetail(
            route_id=rid,
            route_short_name=short_name,
            route_long_name=long_name,
            trip_count=trip_count,
            first_departure=first_dep,
            last_departure=last_dep,
            avg_headway_minutes=avg_headway,
            timed_stop_pct=timed_pct,
            wheelchair_accessible_pct=wc_pct,
            flags=flags,
        ))

    results.sort(key=lambda r: r.trip_count, reverse=True)
    return results


def _service_span(route_trips: pd.DataFrame) -> Tuple[Optional[str], Optional[str]]:
    """Return (first_departure, last_departure) as 'HH:MM' strings."""
    if "departure_time" not in route_trips.columns or len(route_trips) == 0:
        return None, None

    minutes = route_trips["departure_time"].apply(_time_to_minutes).dropna()
    if len(minutes) == 0:
        return None, None

    return _minutes_to_hhmm(int(minutes.min())), _minutes_to_hhmm(int(minutes.max()))


def _avg_headway(route_trips: pd.DataFrame) -> Optional[float]:
    """
    Compute average headway (minutes) across directions.
    Excludes gaps > 120 min (overnight / end-of-service).
    Returns None if fewer than 2 timed trips exist.
    """
    if "departure_time" not in route_trips.columns or len(route_trips) < 2:
        return None

    direction_col = "direction_id" if "direction_id" in route_trips.columns else None
    groups = (
        route_trips.groupby(direction_col) if direction_col
        else [(None, route_trips)]
    )

    all_headways: List[float] = []
    for _, grp in groups:
        mins = grp["departure_time"].apply(_time_to_minutes).dropna().sort_values().values
        if len(mins) < 2:
            continue
        diffs = [
            mins[i + 1] - mins[i]
            for i in range(len(mins) - 1)
            if 0 < mins[i + 1] - mins[i] <= 120
        ]
        all_headways.extend(diffs)

    if not all_headways:
        return None

    return round(sum(all_headways) / len(all_headways), 1)


# ---------------------------------------------------------------------------
# Transfer hub computation
# ---------------------------------------------------------------------------

def _derive_transfer_hubs(
    stop_times_df: pd.DataFrame,
    trips_df: pd.DataFrame,
    routes_df: Optional[pd.DataFrame],
    stops_df: pd.DataFrame,
) -> List[TransferHub]:
    """Return stops served by >= _TRANSFER_MIN_ROUTES distinct routes, sorted by route count desc."""
    st = stop_times_df.merge(trips_df[["trip_id", "route_id"]], on="trip_id", how="left")

    if routes_df is not None and "route_short_name" in routes_df.columns:
        st = st.merge(routes_df[["route_id", "route_short_name"]], on="route_id", how="left")
        name_col = "route_short_name"
    else:
        name_col = "route_id"

    hub_routes: Dict[str, List[str]] = {}
    for stop_id, grp in st.groupby("stop_id"):
        unique_routes = sorted(grp[name_col].dropna().unique().tolist())
        if len(unique_routes) >= _TRANSFER_MIN_ROUTES:
            hub_routes[str(stop_id)] = unique_routes

    stop_names: Dict[str, str] = {}
    if "stop_id" in stops_df.columns and "stop_name" in stops_df.columns:
        stop_names = dict(zip(stops_df["stop_id"].astype(str), stops_df["stop_name"].astype(str)))

    hubs = [
        TransferHub(
            stop_id=sid,
            stop_name=stop_names.get(sid),
            route_count=len(rts),
            routes=rts,
        )
        for sid, rts in hub_routes.items()
    ]
    hubs.sort(key=lambda h: h.route_count, reverse=True)
    return hubs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_count(
    df: Optional[pd.DataFrame],
    id_col: str,
    usable: bool,
    label: str,
    skipped: List[str],
) -> Optional[int]:
    if not usable:
        skipped.append(f"{label}: skipped — data not usable.")
        return None
    if df is None or len(df) == 0 or id_col not in df.columns:
        skipped.append(f"{label}: skipped — DataFrame absent or missing '{id_col}'.")
        return None
    return len(df)


def _derive_service_days(
    calendar: Optional[pd.DataFrame],
    usable: bool,
    skipped: List[str],
) -> Optional[List[str]]:
    if not usable:
        skipped.append("service_days: skipped — service calendar not usable.")
        return None
    if calendar is None or len(calendar) == 0:
        skipped.append("service_days: skipped — calendar.txt absent (only calendar_dates.txt present).")
        return None
    active = [
        day for day in _WEEKDAY_COLUMNS
        if day in calendar.columns
        and "1" in calendar[day].dropna().astype(str).values
    ]
    return active if active else None


def _col_val(df: pd.DataFrame, col: str) -> Optional[str]:
    if col not in df.columns:
        return None
    val = df[col].iloc[0]
    return str(val).strip() if pd.notna(val) and str(val).strip() != "" else None


def _time_to_minutes(t: object) -> Optional[float]:
    """Convert 'HH:MM:SS' (including >24h) to total minutes. Returns None on failure."""
    try:
        parts = str(t).strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return None


def _minutes_to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _str_or_none(val: object) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("nan", "none") else None
