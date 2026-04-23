"""
backend/validator/__init__.py

Public entry point for the validator layer.

`validate(gtfs_data)` accepts a GTFSData container (from the parser layer)
and returns a fully populated HealthReport.

Orchestration order:
  1. file_validator    — which files are present / missing
  2. field_validator   — required fields, null rates, type checks
  3. calendar_validator — calendar presence and content
  4. integrity_validator — referential integrity across files

Health score calculation
------------------------
The score is computed as a weighted fraction of checks passed:

  score = 1.0 - (blocker_weight * blocker_frac + warning_weight * warning_frac)

Where:
  - blocker_frac = blockers / (blockers + warnings + 1)  (normalised)
  - warning_frac = warnings / (blockers + warnings + 1)
  - blocker_weight = 0.8, warning_weight = 0.2

This approach ensures:
  - A feed with zero issues scores 1.0
  - Each additional BLOCKER has a larger impact than a WARNING
  - The score never goes below 0.0 (clamped)

Usable data flags
-----------------
A data group is considered "usable" only when:
  - Its required files are present
  - No BLOCKER issues touch those files
  - (trips additionally requires usable routes AND usable service_calendar)
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from backend.models.report import (
    FeedSummary,
    HealthReport,
    Issue,
    Severity,
    UsableData,
)
from backend.parser.gtfs_parser import GTFSData
from backend.insights.safe_insights import derive_safe_insights
from backend.validator.calendar_validator import validate_calendar
from backend.validator.field_validator import validate_all_fields
from backend.validator.file_validator import validate_files
from backend.validator.integrity_validator import validate_integrity


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate(gtfs_data: GTFSData) -> HealthReport:
    """
    Run all validator modules against a parsed GTFSData container.

    Parameters
    ----------
    gtfs_data:
        Output of `parser.gtfs_parser.parse_gtfs_files()`.

    Returns
    -------
    HealthReport
        Fully populated health report with issues, score, usable flags,
        and safe insights.
    """
    all_issues: List[Issue] = []

    # ------------------------------------------------------------------
    # 1. File-level validation
    # ------------------------------------------------------------------
    file_issues, files_missing, optional_detected = validate_files(
        gtfs_data.files_present
    )
    all_issues.extend(file_issues)

    # ------------------------------------------------------------------
    # 2. Field-level validation (only files that are present)
    # ------------------------------------------------------------------
    gtfs_frames: Dict[str, Optional[pd.DataFrame]] = {
        "agency.txt": gtfs_data.agency,
        "stops.txt": gtfs_data.stops,
        "routes.txt": gtfs_data.routes,
        "trips.txt": gtfs_data.trips,
        "stop_times.txt": gtfs_data.stop_times,
        "calendar.txt": gtfs_data.calendar,
        "calendar_dates.txt": gtfs_data.calendar_dates,
        "shapes.txt": gtfs_data.shapes,
        "feed_info.txt": gtfs_data.feed_info,
    }
    field_issues = validate_all_fields(gtfs_frames)
    all_issues.extend(field_issues)

    # ------------------------------------------------------------------
    # 3. Calendar validation
    # ------------------------------------------------------------------
    calendar_issues, service_ids, service_days = validate_calendar(
        gtfs_data.calendar,
        gtfs_data.calendar_dates,
    )
    all_issues.extend(calendar_issues)

    # ------------------------------------------------------------------
    # 4. Referential integrity
    # ------------------------------------------------------------------
    integrity_issues = validate_integrity(
        trips=gtfs_data.trips,
        routes=gtfs_data.routes,
        stop_times=gtfs_data.stop_times,
        stops=gtfs_data.stops,
        calendar=gtfs_data.calendar,
        calendar_dates=gtfs_data.calendar_dates,
    )
    all_issues.extend(integrity_issues)

    # ------------------------------------------------------------------
    # Build feed summary
    # ------------------------------------------------------------------
    agency_name = _extract_agency_name(gtfs_data.agency)
    feed_version = _extract_feed_version(gtfs_data.feed_info)

    all_required_files = [
        "agency.txt",
        "stops.txt",
        "routes.txt",
        "trips.txt",
        "stop_times.txt",
        "calendar.txt",
        "calendar_dates.txt",
    ]
    files_missing_full = [f for f in all_required_files if f not in gtfs_data.files_present]

    feed_summary = FeedSummary(
        agency_name=agency_name,
        feed_version=feed_version,
        files_present=gtfs_data.files_present,
        files_missing=files_missing_full,
    )

    # ------------------------------------------------------------------
    # Usable data flags
    # ------------------------------------------------------------------
    blocker_files = {
        issue.file
        for issue in all_issues
        if issue.severity == Severity.BLOCKER
    }

    usable_routes = (
        "routes.txt" not in blocker_files
        and gtfs_data.routes is not None
        and len(gtfs_data.routes) > 0
    )
    usable_stops = (
        "stops.txt" not in blocker_files
        and gtfs_data.stops is not None
        and len(gtfs_data.stops) > 0
    )
    usable_calendar = (
        "calendar.txt / calendar_dates.txt" not in blocker_files
        and (
            (gtfs_data.calendar is not None and len(gtfs_data.calendar) > 0)
            or (gtfs_data.calendar_dates is not None and len(gtfs_data.calendar_dates) > 0)
        )
    )
    # Trips depend on routes + calendar + their own file being clean
    usable_trips = (
        usable_routes
        and usable_calendar
        and "trips.txt" not in blocker_files
        and "stop_times.txt" not in blocker_files
        and gtfs_data.trips is not None
        and len(gtfs_data.trips) > 0
    )

    usable_data = UsableData(
        routes=usable_routes,
        stops=usable_stops,
        trips=usable_trips,
        service_calendar=usable_calendar,
    )

    # ------------------------------------------------------------------
    # Safe insights (only from usable data)
    # ------------------------------------------------------------------
    safe_insights, skipped_insights = derive_safe_insights(gtfs_data, usable_data)
    if skipped_insights:
        logger.debug("Skipped insights: %s", skipped_insights)

    # ------------------------------------------------------------------
    # Health score
    # ------------------------------------------------------------------
    health_score = _compute_health_score(all_issues)

    # ------------------------------------------------------------------
    # Assemble report
    # ------------------------------------------------------------------
    return HealthReport(
        feed_summary=feed_summary,
        health_score=health_score,
        issues=all_issues,
        usable_data=usable_data,
        safe_insights=safe_insights,
        cleaning_log=list(gtfs_data.cleaning_log),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_health_score(issues: List[Issue]) -> float:
    """
    Compute a [0.0, 1.0] health score from the issue list.

    BLOCKER issues have 4× the weight of WARNINGs.  INFOs do not affect the
    score.  The denominator is normalised by the total number of checks we
    expect to pass (approximated as issues + 1 so a perfect feed scores 1.0).
    """
    blockers = sum(1 for i in issues if i.severity == Severity.BLOCKER)
    warnings = sum(1 for i in issues if i.severity == Severity.WARNING)

    if blockers == 0 and warnings == 0:
        return 1.0

    # Weight-adjusted penalty
    total_weighted = blockers * 4 + warnings * 1
    # Normalise: we don't know the "max possible" checks, so we use a
    # heuristic denominator that grows with the number of issues found.
    # A single BLOCKER → score ~0.2; many blockers approach 0.0.
    denominator = total_weighted + 5  # +5 baseline so one warning ≠ 0.83
    penalty = total_weighted / denominator
    score = max(0.0, min(1.0, 1.0 - penalty))
    return round(score, 4)


def _extract_agency_name(agency_df: Optional[pd.DataFrame]) -> Optional[str]:
    """Return the first agency_name value from agency.txt, or None."""
    if agency_df is None or len(agency_df) == 0:
        return None
    if "agency_name" not in agency_df.columns:
        return None
    val = agency_df["agency_name"].iloc[0]
    return str(val) if pd.notna(val) and val != "" else None


def _extract_feed_version(feed_info_df: Optional[pd.DataFrame]) -> Optional[str]:
    """Return the feed_version from feed_info.txt, or None."""
    if feed_info_df is None or len(feed_info_df) == 0:
        return None
    if "feed_version" not in feed_info_df.columns:
        return None
    val = feed_info_df["feed_version"].iloc[0]
    return str(val) if pd.notna(val) and val != "" else None
