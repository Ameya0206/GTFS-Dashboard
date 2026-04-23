"""
backend/models/report.py

Pydantic models representing the health report JSON schema defined in CLAUDE.md.

Design notes:
- All fields that can be absent from a real feed are Optional with None defaults.
- `severity` is an Enum to prevent typos and enforce the three-tier system.
- `health_score` is constrained to [0.0, 1.0] using Field validators.
- `cleaning_log` is a list of free-form strings so the parser layer can append
  human-readable descriptions of every transformation it applies.
- The models are used both for internal passing between layers and for JSON
  serialisation via FastAPI's response_model.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    BLOCKER = "BLOCKER"   # Feed cannot be used without fixing this
    WARNING = "WARNING"   # Data will be incomplete or degraded
    INFO = "INFO"         # Non-standard but workable


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class FeedSummary(BaseModel):
    """High-level metadata extracted from agency.txt and feed_info.txt."""

    agency_name: Optional[str] = None
    feed_version: Optional[str] = None
    files_present: List[str] = Field(default_factory=list)
    files_missing: List[str] = Field(default_factory=list)


class Issue(BaseModel):
    """
    A single data quality issue found during validation.

    Edge cases:
    - `field` may be None for file-level issues (e.g. missing file).
    - `count` may be None when the issue is boolean (present/absent).
    """

    severity: Severity
    file: str
    field: Optional[str] = None
    message: str
    count: Optional[int] = None


class UsableData(BaseModel):
    """
    Boolean flags indicating which logical data groups are usable.
    A group is considered usable only when its required files and fields
    pass validation and referential integrity checks.
    """

    routes: bool = False
    stops: bool = False
    trips: bool = False
    service_calendar: bool = False


class RouteDetail(BaseModel):
    """Per-route breakdown for consultant-grade analysis."""

    route_id: str
    route_short_name: Optional[str] = None
    route_long_name: Optional[str] = None
    trip_count: int = 0
    first_departure: Optional[str] = None          # "HH:MM" — earliest trip start
    last_departure: Optional[str] = None           # "HH:MM" — latest trip start
    avg_headway_minutes: Optional[float] = None    # avg gap between consecutive trips
    timed_stop_pct: Optional[float] = None         # % stop_times with explicit arrival time
    wheelchair_accessible_pct: Optional[float] = None  # % trips marked accessible
    flags: List[str] = Field(default_factory=list) # e.g. ["LOW_FREQUENCY", "ADA_GAP"]


class TransferHub(BaseModel):
    """A stop served by 3 or more routes — a potential network transfer point."""

    stop_id: str
    stop_name: Optional[str] = None
    route_count: int = 0
    routes: List[str] = Field(default_factory=list)  # route_short_names


class SafeInsights(BaseModel):
    """
    Counts and summaries derived ONLY from validated, usable data.
    Any insight that could not be safely derived is set to None rather
    than a guess or a partial count — this is a core design invariant.
    """

    # --- Basic counts ---
    route_count: Optional[int] = None
    stop_count: Optional[int] = None
    trip_count: Optional[int] = None
    agency_count: Optional[int] = None
    service_days: Optional[List[str]] = None        # e.g. ["monday", "tuesday", ...]

    # --- Feed validity ---
    feed_start_date: Optional[str] = None           # YYYYMMDD from feed_info.txt
    feed_end_date: Optional[str] = None             # YYYYMMDD from feed_info.txt
    feed_expiry_days: Optional[int] = None          # days until expiry (negative = expired)

    # --- Network health ---
    service_pattern_count: Optional[int] = None     # distinct service_ids in calendar.txt
    avg_stops_per_trip: Optional[float] = None      # mean stops across all trips
    transfer_hubs: Optional[List[TransferHub]] = None  # stops served by 3+ routes

    # --- Accessibility ---
    wheelchair_accessible_pct: Optional[float] = None   # % trips marked accessible
    non_accessible_trip_count: Optional[int] = None

    # --- Data quality for downstream systems ---
    timed_stop_pct: Optional[float] = None          # % stop_times with explicit arrival time

    # --- Per-route breakdown ---
    routes_detail: Optional[List[RouteDetail]] = None


# ---------------------------------------------------------------------------
# Top-level health report
# ---------------------------------------------------------------------------

class HealthReport(BaseModel):
    """
    The complete output of a single validation run.

    `health_score` ranges from 0.0 (completely broken) to 1.0 (fully valid).
    The score is computed by the validator layer; the model only enforces the
    valid range.

    `cleaning_log` captures every transformation applied to the raw data so
    nothing is silently mutated.  Each entry is a human-readable string.
    """

    feed_summary: FeedSummary = Field(default_factory=FeedSummary)
    health_score: float = Field(default=0.0, ge=0.0, le=1.0)
    issues: List[Issue] = Field(default_factory=list)
    usable_data: UsableData = Field(default_factory=UsableData)
    safe_insights: SafeInsights = Field(default_factory=SafeInsights)
    cleaning_log: List[str] = Field(default_factory=list)
