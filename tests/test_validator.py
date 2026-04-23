"""
tests/test_validator.py

Unit tests for all validator modules.

Tests use small synthetic pandas DataFrames — no real GTFS files are required.

Test structure:
  - TestFileValidator       — file_validator.py
  - TestFieldValidator      — field_validator.py
  - TestIntegrityValidator  — integrity_validator.py
  - TestCalendarValidator   — calendar_validator.py
  - TestValidatorOrchestrator — validator/__init__.py end-to-end
"""

from __future__ import annotations

import pytest
import pandas as pd

from backend.models.report import Severity
from backend.validator.file_validator import validate_files
from backend.validator.field_validator import validate_fields, validate_all_fields
from backend.validator.integrity_validator import validate_integrity
from backend.validator.calendar_validator import validate_calendar
from backend.parser.gtfs_parser import GTFSData
from backend.validator import validate


# ===========================================================================
# Helpers
# ===========================================================================

def _issues_by_severity(issues, severity):
    return [i for i in issues if i.severity == severity]


def _issue_fields(issues):
    return {i.field for i in issues}


def _issue_files(issues):
    return {i.file for i in issues}


# ===========================================================================
# TestFileValidator
# ===========================================================================

class TestFileValidator:

    def test_all_required_present_no_issues(self):
        files = [
            "agency.txt", "stops.txt", "routes.txt",
            "trips.txt", "stop_times.txt", "calendar.txt"
        ]
        issues, missing, optional = validate_files(files)
        assert issues == []
        assert missing == []

    def test_missing_single_required_file(self):
        files = ["stops.txt", "routes.txt", "trips.txt", "stop_times.txt", "calendar.txt"]
        issues, missing, optional = validate_files(files)
        assert len(issues) == 1
        assert issues[0].severity == Severity.BLOCKER
        assert "agency.txt" in issues[0].message
        assert "agency.txt" in missing

    def test_all_required_files_missing(self):
        issues, missing, optional = validate_files([])
        blockers = _issues_by_severity(issues, Severity.BLOCKER)
        assert len(blockers) == 5  # 5 non-calendar required files
        assert len(missing) == 5

    def test_optional_files_detected(self):
        files = [
            "agency.txt", "stops.txt", "routes.txt",
            "trips.txt", "stop_times.txt", "calendar.txt",
            "shapes.txt", "feed_info.txt",
        ]
        _, _, optional = validate_files(files)
        assert "shapes.txt" in optional
        assert "feed_info.txt" in optional

    def test_optional_files_absent_no_issues(self):
        files = [
            "agency.txt", "stops.txt", "routes.txt",
            "trips.txt", "stop_times.txt", "calendar.txt",
        ]
        issues, _, _ = validate_files(files)
        assert issues == []

    def test_calendar_only_via_calendar_dates(self):
        # calendar_dates.txt alone should not trigger a file-level BLOCKER here
        # (calendar_validator handles this)
        files = [
            "agency.txt", "stops.txt", "routes.txt",
            "trips.txt", "stop_times.txt", "calendar_dates.txt",
        ]
        issues, missing, _ = validate_files(files)
        # No required-file blockers; calendar absence handled elsewhere
        assert all(i.file != "calendar_dates.txt" for i in issues)

    def test_missing_multiple_required_files(self):
        files = ["agency.txt", "calendar.txt"]
        issues, missing, _ = validate_files(files)
        assert len(missing) == 4
        assert "stops.txt" in missing
        assert "routes.txt" in missing
        assert "trips.txt" in missing
        assert "stop_times.txt" in missing


# ===========================================================================
# TestFieldValidator
# ===========================================================================

class TestFieldValidator:

    # --- stops.txt ---

    def test_stops_all_required_fields_present_no_issues(self):
        df = pd.DataFrame({
            "stop_id": ["S1", "S2"],
            "stop_name": ["Stop 1", "Stop 2"],
            "stop_lat": ["37.7749", "37.7750"],
            "stop_lon": ["-122.4194", "-122.4195"],
        })
        issues = validate_fields("stops.txt", df)
        assert _issues_by_severity(issues, Severity.BLOCKER) == []

    def test_stops_missing_required_field(self):
        df = pd.DataFrame({
            "stop_id": ["S1"],
            "stop_name": ["Stop 1"],
            # stop_lat and stop_lon missing
        })
        issues = validate_fields("stops.txt", df)
        blockers = _issues_by_severity(issues, Severity.BLOCKER)
        assert len(blockers) == 2
        assert "stop_lat" in _issue_fields(blockers)
        assert "stop_lon" in _issue_fields(blockers)

    def test_stops_high_null_rate_warning(self):
        # 50% null for stop_name — above 10% threshold
        df = pd.DataFrame({
            "stop_id": ["S1", "S2"],
            "stop_name": ["Stop 1", None],
            "stop_lat": ["37.7749", "37.7750"],
            "stop_lon": ["-122.4194", "-122.4195"],
        })
        issues = validate_fields("stops.txt", df)
        warnings = _issues_by_severity(issues, Severity.WARNING)
        warning_fields = _issue_fields(warnings)
        assert "stop_name" in warning_fields

    def test_stops_null_rate_below_threshold_no_warning(self):
        # 1 null out of 20 rows = 5% — below threshold
        rows = [{"stop_id": f"S{i}", "stop_name": f"Stop {i}",
                 "stop_lat": "37.0", "stop_lon": "-122.0"} for i in range(20)]
        rows[0]["stop_name"] = None  # 5% null
        df = pd.DataFrame(rows)
        issues = validate_fields("stops.txt", df)
        warnings = _issues_by_severity(issues, Severity.WARNING)
        warning_fields = _issue_fields(warnings)
        assert "stop_name" not in warning_fields

    def test_stops_non_numeric_lat_lon_warning(self):
        df = pd.DataFrame({
            "stop_id": ["S1", "S2"],
            "stop_name": ["Stop 1", "Stop 2"],
            "stop_lat": ["37.7749", "not_a_number"],
            "stop_lon": ["-122.4194", "also_bad"],
        })
        issues = validate_fields("stops.txt", df)
        warnings = _issues_by_severity(issues, Severity.WARNING)
        warning_fields = _issue_fields(warnings)
        assert "stop_lat" in warning_fields
        assert "stop_lon" in warning_fields

    def test_stops_valid_numeric_lat_lon_no_warning(self):
        df = pd.DataFrame({
            "stop_id": ["S1"],
            "stop_name": ["Stop 1"],
            "stop_lat": ["-90.0"],
            "stop_lon": ["180.0"],
        })
        issues = validate_fields("stops.txt", df)
        warnings = _issues_by_severity(issues, Severity.WARNING)
        warning_fields = _issue_fields(warnings)
        assert "stop_lat" not in warning_fields
        assert "stop_lon" not in warning_fields

    # --- stop_times.txt ---

    def test_stop_times_valid_time_format(self):
        df = pd.DataFrame({
            "trip_id": ["T1", "T1"],
            "arrival_time": ["08:00:00", "25:30:00"],  # 25h valid for overnight
            "departure_time": ["08:01:00", "25:31:00"],
            "stop_id": ["S1", "S2"],
            "stop_sequence": ["1", "2"],
        })
        issues = validate_fields("stop_times.txt", df)
        warnings = _issues_by_severity(issues, Severity.WARNING)
        warning_fields = _issue_fields(warnings)
        assert "arrival_time" not in warning_fields
        assert "departure_time" not in warning_fields

    def test_stop_times_invalid_time_format_warning(self):
        df = pd.DataFrame({
            "trip_id": ["T1"],
            "arrival_time": ["8:00"],  # Missing seconds
            "departure_time": ["not_a_time"],
            "stop_id": ["S1"],
            "stop_sequence": ["1"],
        })
        issues = validate_fields("stop_times.txt", df)
        warnings = _issues_by_severity(issues, Severity.WARNING)
        warning_fields = _issue_fields(warnings)
        assert "arrival_time" in warning_fields
        assert "departure_time" in warning_fields

    def test_empty_dataframe_no_crash(self):
        df = pd.DataFrame(columns=["stop_id", "stop_name", "stop_lat", "stop_lon"])
        issues = validate_fields("stops.txt", df)
        # Should not crash; no value-level checks on empty frames
        assert isinstance(issues, list)

    # --- validate_all_fields ---

    def test_validate_all_fields_skips_none(self):
        frames = {
            "stops.txt": None,
            "routes.txt": pd.DataFrame({"route_id": ["R1"], "route_type": ["3"]}),
        }
        issues = validate_all_fields(frames)
        # stops.txt is None — no issues from it; routes.txt is fine
        file_set = _issue_files(issues)
        assert "stops.txt" not in file_set

    # --- routes.txt ---

    def test_routes_missing_route_type_blocker(self):
        df = pd.DataFrame({"route_id": ["R1", "R2"]})
        issues = validate_fields("routes.txt", df)
        blockers = _issues_by_severity(issues, Severity.BLOCKER)
        assert any(i.field == "route_type" for i in blockers)

    # --- trips.txt ---

    def test_trips_all_required_present(self):
        df = pd.DataFrame({
            "route_id": ["R1"],
            "service_id": ["WD"],
            "trip_id": ["T1"],
        })
        issues = validate_fields("trips.txt", df)
        blockers = _issues_by_severity(issues, Severity.BLOCKER)
        assert blockers == []


# ===========================================================================
# TestIntegrityValidator
# ===========================================================================

class TestIntegrityValidator:

    def _make_routes(self, ids):
        return pd.DataFrame({"route_id": ids, "route_type": ["3"] * len(ids)})

    def _make_trips(self, route_ids, service_ids=None, trip_ids=None):
        n = len(route_ids)
        return pd.DataFrame({
            "route_id": route_ids,
            "service_id": service_ids or [f"SVC{i}" for i in range(n)],
            "trip_id": trip_ids or [f"T{i}" for i in range(n)],
        })

    def _make_stops(self, ids):
        return pd.DataFrame({
            "stop_id": ids,
            "stop_name": [f"Stop {i}" for i in ids],
            "stop_lat": ["37.0"] * len(ids),
            "stop_lon": ["-122.0"] * len(ids),
        })

    def _make_stop_times(self, trip_ids, stop_ids):
        return pd.DataFrame({
            "trip_id": trip_ids,
            "stop_id": stop_ids,
            "arrival_time": ["08:00:00"] * len(trip_ids),
            "departure_time": ["08:01:00"] * len(trip_ids),
            "stop_sequence": list(range(1, len(trip_ids) + 1)),
        })

    def _make_calendar(self, service_ids):
        return pd.DataFrame({
            "service_id": service_ids,
            "monday": ["1"] * len(service_ids),
            "tuesday": ["1"] * len(service_ids),
            "wednesday": ["1"] * len(service_ids),
            "thursday": ["1"] * len(service_ids),
            "friday": ["1"] * len(service_ids),
            "saturday": ["0"] * len(service_ids),
            "sunday": ["0"] * len(service_ids),
            "start_date": ["20240101"] * len(service_ids),
            "end_date": ["20241231"] * len(service_ids),
        })

    def test_clean_feed_no_issues(self):
        routes = self._make_routes(["R1", "R2"])
        trips = self._make_trips(["R1", "R2"], service_ids=["WD", "WD"], trip_ids=["T1", "T2"])
        stops = self._make_stops(["S1", "S2"])
        stop_times = self._make_stop_times(["T1", "T2"], ["S1", "S2"])
        calendar = self._make_calendar(["WD"])

        issues = validate_integrity(trips, routes, stop_times, stops, calendar, None)
        assert issues == []

    def test_trips_reference_missing_route(self):
        routes = self._make_routes(["R1"])
        trips = self._make_trips(["R1", "R99"], service_ids=["WD", "WD"], trip_ids=["T1", "T2"])
        stops = self._make_stops(["S1"])
        stop_times = self._make_stop_times(["T1"], ["S1"])
        calendar = self._make_calendar(["WD"])

        issues = validate_integrity(trips, routes, stop_times, stops, calendar, None)
        blockers = _issues_by_severity(issues, Severity.BLOCKER)
        assert len(blockers) == 1
        assert blockers[0].file == "trips.txt"
        assert blockers[0].field == "route_id"
        assert blockers[0].count == 1

    def test_stop_times_reference_missing_trip(self):
        routes = self._make_routes(["R1"])
        trips = self._make_trips(["R1"], service_ids=["WD"], trip_ids=["T1"])
        stops = self._make_stops(["S1"])
        stop_times = self._make_stop_times(["T1", "T99"], ["S1", "S1"])
        calendar = self._make_calendar(["WD"])

        issues = validate_integrity(trips, routes, stop_times, stops, calendar, None)
        blockers = _issues_by_severity(issues, Severity.BLOCKER)
        trip_issue = [i for i in blockers if i.file == "stop_times.txt" and i.field == "trip_id"]
        assert len(trip_issue) == 1
        assert trip_issue[0].count == 1

    def test_stop_times_reference_missing_stop(self):
        routes = self._make_routes(["R1"])
        trips = self._make_trips(["R1"], service_ids=["WD"], trip_ids=["T1"])
        stops = self._make_stops(["S1"])
        stop_times = self._make_stop_times(["T1", "T1"], ["S1", "S99"])
        calendar = self._make_calendar(["WD"])

        issues = validate_integrity(trips, routes, stop_times, stops, calendar, None)
        blockers = _issues_by_severity(issues, Severity.BLOCKER)
        stop_issue = [i for i in blockers if i.file == "stop_times.txt" and i.field == "stop_id"]
        assert len(stop_issue) == 1
        assert stop_issue[0].count == 1

    def test_trips_reference_missing_service_id(self):
        routes = self._make_routes(["R1"])
        trips = self._make_trips(["R1", "R1"], service_ids=["WD", "GHOST"], trip_ids=["T1", "T2"])
        stops = self._make_stops(["S1"])
        stop_times = self._make_stop_times(["T1"], ["S1"])
        calendar = self._make_calendar(["WD"])

        issues = validate_integrity(trips, routes, stop_times, stops, calendar, None)
        blockers = _issues_by_severity(issues, Severity.BLOCKER)
        svc_issue = [i for i in blockers if i.file == "trips.txt" and i.field == "service_id"]
        assert len(svc_issue) == 1
        assert svc_issue[0].count == 1

    def test_service_id_in_calendar_dates_only(self):
        """service_id valid when it appears in calendar_dates even without calendar.txt"""
        routes = self._make_routes(["R1"])
        trips = self._make_trips(["R1"], service_ids=["SPECIAL"], trip_ids=["T1"])
        stops = self._make_stops(["S1"])
        stop_times = self._make_stop_times(["T1"], ["S1"])
        calendar_dates = pd.DataFrame({
            "service_id": ["SPECIAL"],
            "date": ["20240401"],
            "exception_type": ["1"],
        })

        issues = validate_integrity(trips, routes, stop_times, stops, None, calendar_dates)
        svc_issues = [i for i in issues if i.field == "service_id"]
        assert svc_issues == []

    def test_none_inputs_do_not_crash(self):
        """All None inputs should return empty issues, not raise."""
        issues = validate_integrity(None, None, None, None, None, None)
        assert issues == []

    def test_multiple_broken_refs_counted_correctly(self):
        routes = self._make_routes(["R1"])
        # 3 of 4 trips reference a non-existent route
        trips = pd.DataFrame({
            "route_id": ["R1", "R99", "R99", "R99"],
            "service_id": ["WD"] * 4,
            "trip_id": ["T1", "T2", "T3", "T4"],
        })
        calendar = self._make_calendar(["WD"])
        issues = validate_integrity(trips, routes, None, None, calendar, None)
        route_issue = [i for i in issues if i.field == "route_id"]
        assert len(route_issue) == 1
        assert route_issue[0].count == 3

    def test_both_calendar_sources_combined(self):
        """service_id valid if it appears in either calendar source."""
        routes = self._make_routes(["R1"])
        trips = pd.DataFrame({
            "route_id": ["R1", "R1"],
            "service_id": ["WD", "HOLIDAY"],
            "trip_id": ["T1", "T2"],
        })
        stops = self._make_stops(["S1"])
        stop_times = self._make_stop_times(["T1", "T2"], ["S1", "S1"])
        calendar = self._make_calendar(["WD"])
        calendar_dates = pd.DataFrame({
            "service_id": ["HOLIDAY"],
            "date": ["20240704"],
            "exception_type": ["1"],
        })

        issues = validate_integrity(trips, routes, stop_times, stops, calendar, calendar_dates)
        svc_issues = [i for i in issues if i.field == "service_id"]
        assert svc_issues == []


# ===========================================================================
# TestCalendarValidator
# ===========================================================================

class TestCalendarValidator:

    def _make_calendar(self, service_ids, start_dates=None, end_dates=None):
        n = len(service_ids)
        return pd.DataFrame({
            "service_id": service_ids,
            "monday": ["1"] * n,
            "tuesday": ["1"] * n,
            "wednesday": ["1"] * n,
            "thursday": ["1"] * n,
            "friday": ["1"] * n,
            "saturday": ["0"] * n,
            "sunday": ["0"] * n,
            "start_date": start_dates or (["20240101"] * n),
            "end_date": end_dates or (["20241231"] * n),
        })

    def test_calendar_txt_only_valid(self):
        cal = self._make_calendar(["WD"])
        issues, svc_ids, svc_days = validate_calendar(cal, None)
        blockers = _issues_by_severity(issues, Severity.BLOCKER)
        assert blockers == []
        assert "WD" in svc_ids

    def test_calendar_dates_only_valid(self):
        cal_dates = pd.DataFrame({
            "service_id": ["SPECIAL"],
            "date": ["20240401"],
            "exception_type": ["1"],
        })
        issues, svc_ids, svc_days = validate_calendar(None, cal_dates)
        blockers = _issues_by_severity(issues, Severity.BLOCKER)
        assert blockers == []
        assert "SPECIAL" in svc_ids

    def test_both_calendar_files_valid(self):
        cal = self._make_calendar(["WD"])
        cal_dates = pd.DataFrame({
            "service_id": ["HOLIDAY"],
            "date": ["20240704"],
            "exception_type": ["1"],
        })
        issues, svc_ids, _ = validate_calendar(cal, cal_dates)
        blockers = _issues_by_severity(issues, Severity.BLOCKER)
        assert blockers == []
        assert "WD" in svc_ids
        assert "HOLIDAY" in svc_ids

    def test_neither_calendar_file_is_blocker(self):
        issues, svc_ids, svc_days = validate_calendar(None, None)
        blockers = _issues_by_severity(issues, Severity.BLOCKER)
        assert len(blockers) == 1
        assert svc_ids == set()
        assert svc_days == []

    def test_invalid_weekday_flag_warning(self):
        cal = pd.DataFrame({
            "service_id": ["WD"],
            "monday": ["yes"],   # Invalid — should be "0" or "1"
            "tuesday": ["1"],
            "wednesday": ["1"],
            "thursday": ["1"],
            "friday": ["1"],
            "saturday": ["0"],
            "sunday": ["0"],
            "start_date": ["20240101"],
            "end_date": ["20241231"],
        })
        issues, _, _ = validate_calendar(cal, None)
        warnings = _issues_by_severity(issues, Severity.WARNING)
        assert any(i.field == "monday" for i in warnings)

    def test_start_date_after_end_date_warning(self):
        cal = self._make_calendar(
            ["WD"],
            start_dates=["20241231"],
            end_dates=["20240101"],   # start after end
        )
        issues, _, _ = validate_calendar(cal, None)
        warnings = _issues_by_severity(issues, Severity.WARNING)
        assert any(i.file == "calendar.txt" and i.field == "start_date" for i in warnings)

    def test_valid_start_end_dates_no_warning(self):
        cal = self._make_calendar(["WD"])
        issues, _, _ = validate_calendar(cal, None)
        warnings = _issues_by_severity(issues, Severity.WARNING)
        date_warnings = [i for i in warnings if i.field == "start_date"]
        assert date_warnings == []

    def test_active_service_days_extracted(self):
        cal = self._make_calendar(["WD"])  # M-F active, Sat-Sun not
        _, _, svc_days = validate_calendar(cal, None)
        assert "monday" in svc_days
        assert "friday" in svc_days
        assert "saturday" not in svc_days
        assert "sunday" not in svc_days

    def test_invalid_exception_type_warning(self):
        cal_dates = pd.DataFrame({
            "service_id": ["SPECIAL"],
            "date": ["20240401"],
            "exception_type": ["99"],   # invalid; must be "1" or "2"
        })
        issues, _, _ = validate_calendar(None, cal_dates)
        warnings = _issues_by_severity(issues, Severity.WARNING)
        assert any(i.field == "exception_type" for i in warnings)

    def test_empty_calendar_dataframe_treated_as_absent(self):
        empty_cal = pd.DataFrame(columns=["service_id", "monday", "tuesday",
                                          "wednesday", "thursday", "friday",
                                          "saturday", "sunday", "start_date", "end_date"])
        empty_cd = pd.DataFrame(columns=["service_id", "date", "exception_type"])
        issues, _, _ = validate_calendar(empty_cal, empty_cd)
        # Both are empty (0 rows) — should behave like neither present
        blockers = _issues_by_severity(issues, Severity.BLOCKER)
        assert len(blockers) == 1


# ===========================================================================
# TestValidatorOrchestrator (end-to-end)
# ===========================================================================

class TestValidatorOrchestrator:
    """
    Integration tests for the validate() function in validator/__init__.py.
    Uses GTFSData objects with synthetic DataFrames.
    """

    def _clean_gtfs_data(self) -> GTFSData:
        """Build a fully valid minimal GTFSData."""
        data = GTFSData()
        data.files_present = [
            "agency.txt", "stops.txt", "routes.txt",
            "trips.txt", "stop_times.txt", "calendar.txt",
        ]
        data.agency = pd.DataFrame({
            "agency_name": ["Test Agency"],
            "agency_url": ["https://example.com"],
            "agency_timezone": ["America/Los_Angeles"],
        })
        data.stops = pd.DataFrame({
            "stop_id": ["S1", "S2"],
            "stop_name": ["Stop 1", "Stop 2"],
            "stop_lat": ["37.7749", "37.7750"],
            "stop_lon": ["-122.4194", "-122.4195"],
        })
        data.routes = pd.DataFrame({
            "route_id": ["R1"],
            "route_type": ["3"],
        })
        data.trips = pd.DataFrame({
            "route_id": ["R1", "R1"],
            "service_id": ["WD", "WD"],
            "trip_id": ["T1", "T2"],
        })
        data.stop_times = pd.DataFrame({
            "trip_id": ["T1", "T1", "T2", "T2"],
            "arrival_time": ["08:00:00", "08:10:00", "09:00:00", "09:10:00"],
            "departure_time": ["08:01:00", "08:11:00", "09:01:00", "09:11:00"],
            "stop_id": ["S1", "S2", "S1", "S2"],
            "stop_sequence": ["1", "2", "1", "2"],
        })
        data.calendar = pd.DataFrame({
            "service_id": ["WD"],
            "monday": ["1"],
            "tuesday": ["1"],
            "wednesday": ["1"],
            "thursday": ["1"],
            "friday": ["1"],
            "saturday": ["0"],
            "sunday": ["0"],
            "start_date": ["20240101"],
            "end_date": ["20241231"],
        })
        return data

    def test_clean_feed_scores_1(self):
        data = self._clean_gtfs_data()
        report = validate(data)
        assert report.health_score == 1.0
        assert report.issues == []

    def test_clean_feed_usable_data_all_true(self):
        data = self._clean_gtfs_data()
        report = validate(data)
        assert report.usable_data.routes is True
        assert report.usable_data.stops is True
        assert report.usable_data.trips is True
        assert report.usable_data.service_calendar is True

    def test_clean_feed_safe_insights_populated(self):
        data = self._clean_gtfs_data()
        report = validate(data)
        assert report.safe_insights.route_count == 1
        assert report.safe_insights.stop_count == 2
        assert report.safe_insights.trip_count == 2
        assert report.safe_insights.agency_count == 1
        assert "monday" in report.safe_insights.service_days

    def test_agency_name_extracted(self):
        data = self._clean_gtfs_data()
        report = validate(data)
        assert report.feed_summary.agency_name == "Test Agency"

    def test_missing_required_file_blocker(self):
        data = self._clean_gtfs_data()
        data.stops = None
        data.files_present = [f for f in data.files_present if f != "stops.txt"]
        report = validate(data)
        blockers = _issues_by_severity(report.issues, Severity.BLOCKER)
        assert any(i.file == "stops.txt" for i in blockers)
        assert report.health_score < 1.0

    def test_missing_calendar_blocker(self):
        data = self._clean_gtfs_data()
        data.calendar = None
        data.files_present = [f for f in data.files_present if f != "calendar.txt"]
        report = validate(data)
        blockers = _issues_by_severity(report.issues, Severity.BLOCKER)
        assert any("calendar" in i.file.lower() for i in blockers)

    def test_integrity_failure_lowers_score(self):
        data = self._clean_gtfs_data()
        # Add a trip that references a non-existent route
        data.trips = pd.DataFrame({
            "route_id": ["R1", "R99"],  # R99 does not exist
            "service_id": ["WD", "WD"],
            "trip_id": ["T1", "T2"],
        })
        report = validate(data)
        assert report.health_score < 1.0
        blockers = _issues_by_severity(report.issues, Severity.BLOCKER)
        assert any(i.field == "route_id" and i.file == "trips.txt" for i in blockers)

    def test_usable_trips_false_when_integrity_broken(self):
        data = self._clean_gtfs_data()
        # All stop_times reference a non-existent trip
        data.stop_times = pd.DataFrame({
            "trip_id": ["GHOST"] * 4,
            "arrival_time": ["08:00:00"] * 4,
            "departure_time": ["08:01:00"] * 4,
            "stop_id": ["S1", "S2", "S1", "S2"],
            "stop_sequence": ["1", "2", "1", "2"],
        })
        report = validate(data)
        assert report.usable_data.trips is False
        assert report.safe_insights.trip_count is None

    def test_cleaning_log_propagated(self):
        data = self._clean_gtfs_data()
        data.cleaning_log = ["stops.txt: stripped whitespace from 4 columns."]
        report = validate(data)
        assert len(report.cleaning_log) == 1
        assert "whitespace" in report.cleaning_log[0]

    def test_health_score_zero_on_catastrophic_feed(self):
        # Feed with nothing present
        data = GTFSData()
        data.files_present = []
        report = validate(data)
        assert report.health_score < 0.5  # Should be heavily penalised
        assert report.usable_data.routes is False
        assert report.usable_data.stops is False
        assert report.usable_data.trips is False
        assert report.usable_data.service_calendar is False

    def test_feed_summary_files_missing_populated(self):
        data = self._clean_gtfs_data()
        data.stops = None
        data.files_present = [f for f in data.files_present if f != "stops.txt"]
        report = validate(data)
        assert "stops.txt" in report.feed_summary.files_missing

    def test_feed_summary_files_present_populated(self):
        data = self._clean_gtfs_data()
        report = validate(data)
        assert "agency.txt" in report.feed_summary.files_present
        assert "stops.txt" in report.feed_summary.files_present
