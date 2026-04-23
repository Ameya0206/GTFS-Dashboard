"""
backend/validator/file_validator.py

Checks which required and optional GTFS files are present or missing.

Design notes:
- "Required" files are those mandated by the GTFS spec; their absence is a
  BLOCKER because the feed cannot be meaningfully used without them.
- Calendar files (calendar.txt / calendar_dates.txt) are handled separately
  by calendar_validator.py; this module flags them for informational purposes
  only — the actual severity is determined over there.
- Optional files that are absent generate no issues at all — absence is normal.
- The function accepts the GTFSData container's `files_present` list (a list
  of plain filename strings like "stops.txt") so it does not depend on
  DataFrames, keeping it fast and decoupled from parsing details.
"""

from __future__ import annotations

from typing import List, Tuple

from backend.models.report import Issue, Severity

# ---------------------------------------------------------------------------
# File catalogues (mirrors gtfs_parser.py — kept in sync manually)
# ---------------------------------------------------------------------------

REQUIRED_FILES: List[str] = [
    "agency.txt",
    "stops.txt",
    "routes.txt",
    "trips.txt",
    "stop_times.txt",
]

# At least one of these must be present — checked in calendar_validator.py
CALENDAR_FILES: List[str] = [
    "calendar.txt",
    "calendar_dates.txt",
]

OPTIONAL_FILES: List[str] = [
    "shapes.txt",
    "fare_attributes.txt",
    "fare_rules.txt",
    "frequencies.txt",
    "transfers.txt",
    "feed_info.txt",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_files(files_present: List[str]) -> Tuple[List[Issue], List[str], List[str]]:
    """
    Check which required and optional GTFS files are present or missing.

    Parameters
    ----------
    files_present:
        List of filenames found in the GTFS zip (e.g. ["stops.txt", "trips.txt"]).

    Returns
    -------
    issues:
        List of Issue objects.  Missing required files → BLOCKER.
        Missing calendar files are not flagged here (calendar_validator handles it).
    files_missing:
        List of required files that were not found.
    optional_detected:
        List of optional files that are present in the zip.
    """
    present_set = set(files_present)
    issues: List[Issue] = []

    # --- Required file checks ---
    files_missing: List[str] = []
    for fname in REQUIRED_FILES:
        if fname not in present_set:
            files_missing.append(fname)
            issues.append(
                Issue(
                    severity=Severity.BLOCKER,
                    file=fname,
                    field=None,
                    message=f"Required file '{fname}' is missing from the GTFS feed.",
                    count=None,
                )
            )

    # --- Optional file detection (informational only) ---
    optional_detected: List[str] = [f for f in OPTIONAL_FILES if f in present_set]

    # Detect calendar files and emit an INFO note if present (calendar_validator
    # handles the BLOCKER case when neither is present)
    calendar_present = [f for f in CALENDAR_FILES if f in present_set]
    if calendar_present:
        # No issue needed — presence is fine, absence is checked elsewhere
        pass

    return issues, files_missing, optional_detected
