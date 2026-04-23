"""
tests/test_api.py

Integration tests for the POST /validate endpoint.

Two test classes:
  - TestValidateWithFixture : uses a bundled minimal GTFS zip in tests/fixtures/
    so the test suite runs fully offline and deterministically.
  - TestValidateWithRealFeed: downloads a small public GTFS feed from the
    Mobility Database and checks the response shape (skipped if network is
    unavailable, marked with pytest.mark.network).

Run all tests:
    pytest tests/test_api.py -v

Run only offline tests:
    pytest tests/test_api.py -v -m "not network"

Run only network tests:
    pytest tests/test_api.py -v -m network
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest
import requests
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

# Path to the bundled fixture zip (committed to the repo)
FIXTURE_ZIP = Path(__file__).parent / "fixtures" / "sample_gtfs.zip"

# A small public GTFS zip (~50–200 KB) used for the network test.
# This is the City of Laramie, WY feed from the Mobility Database — it is
# small, stable, and publicly accessible without authentication.
# Source: https://transitfeeds.com/p/city-of-laramie/1062
# Canonical mirror via MobilityData GitHub reference feeds:
NETWORK_GTFS_URL = (
    "https://github.com/MobilityData/gtfs-validator/raw/master/"
    "gtfs-validator/src/test/resources/gtfs-examples/good_feed.zip"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post_zip_bytes(zip_bytes: bytes) -> Any:
    """POST zip bytes to /validate as a multipart file upload."""
    return client.post(
        "/validate",
        files={"file": ("feed.zip", io.BytesIO(zip_bytes), "application/zip")},
    )


def _assert_health_report_shape(data: dict) -> None:
    """Assert that `data` has the expected top-level HealthReport structure."""
    assert "feed_summary" in data, "Missing 'feed_summary' key"
    assert "health_score" in data, "Missing 'health_score' key"
    assert "issues" in data, "Missing 'issues' key"
    assert "usable_data" in data, "Missing 'usable_data' key"
    assert "safe_insights" in data, "Missing 'safe_insights' key"
    assert "cleaning_log" in data, "Missing 'cleaning_log' key"

    # feed_summary shape
    fs = data["feed_summary"]
    assert "agency_name" in fs
    assert "feed_version" in fs
    assert "files_present" in fs
    assert "files_missing" in fs
    assert isinstance(fs["files_present"], list)
    assert isinstance(fs["files_missing"], list)

    # health_score range
    score = data["health_score"]
    assert isinstance(score, float), f"health_score must be float, got {type(score)}"
    assert 0.0 <= score <= 1.0, f"health_score out of range: {score}"

    # issues shape
    for issue in data["issues"]:
        assert "severity" in issue
        assert issue["severity"] in ("BLOCKER", "WARNING", "INFO")
        assert "file" in issue
        assert "message" in issue

    # usable_data shape
    ud = data["usable_data"]
    for flag in ("routes", "stops", "trips", "service_calendar"):
        assert flag in ud, f"Missing usable_data.{flag}"
        assert isinstance(ud[flag], bool), f"usable_data.{flag} must be bool"

    # safe_insights shape
    si = data["safe_insights"]
    for field in ("route_count", "stop_count", "trip_count", "agency_count", "service_days"):
        assert field in si, f"Missing safe_insights.{field}"
        # Values are either int/list or null — no type assertion needed

    # cleaning_log is a list of strings
    assert isinstance(data["cleaning_log"], list)


# ---------------------------------------------------------------------------
# Fixture-based tests (always run, no network required)
# ---------------------------------------------------------------------------

class TestValidateWithFixture:
    """
    Tests using the bundled sample_gtfs.zip fixture.

    The fixture is a minimal but fully valid GTFS feed:
      - agency.txt   : 1 agency (Bay Area Rapid Transit)
      - stops.txt    : 2 stops
      - routes.txt   : 1 route (Orange Line)
      - trips.txt    : 2 trips
      - stop_times.txt: 4 stop_time records
      - calendar.txt : 1 service (weekday Mon–Fri)
    """

    def _post_fixture(self) -> Any:
        with open(FIXTURE_ZIP, "rb") as f:
            return _post_zip_bytes(f.read())

    def test_returns_200(self):
        response = self._post_fixture()
        assert response.status_code == 200, response.text

    def test_response_shape(self):
        response = self._post_fixture()
        assert response.status_code == 200
        _assert_health_report_shape(response.json())

    def test_health_score_is_1_for_valid_feed(self):
        response = self._post_fixture()
        data = response.json()
        assert data["health_score"] == 1.0, (
            f"Expected score 1.0 for a clean feed, got {data['health_score']}. "
            f"Issues: {data['issues']}"
        )

    def test_no_issues_for_valid_feed(self):
        response = self._post_fixture()
        data = response.json()
        assert data["issues"] == [], f"Expected no issues, got: {data['issues']}"

    def test_all_usable_data_flags_true(self):
        response = self._post_fixture()
        ud = response.json()["usable_data"]
        assert ud["routes"] is True
        assert ud["stops"] is True
        assert ud["trips"] is True
        assert ud["service_calendar"] is True

    def test_safe_insights_populated(self):
        response = self._post_fixture()
        si = response.json()["safe_insights"]
        assert si["route_count"] == 1
        assert si["stop_count"] == 2
        assert si["trip_count"] == 2
        assert si["agency_count"] == 1
        assert isinstance(si["service_days"], list)
        assert "monday" in si["service_days"]
        assert "friday" in si["service_days"]
        assert "saturday" not in si["service_days"]

    def test_feed_summary_agency_name(self):
        response = self._post_fixture()
        fs = response.json()["feed_summary"]
        assert fs["agency_name"] == "Bay Area Rapid Transit"

    def test_files_present_populated(self):
        response = self._post_fixture()
        fs = response.json()["feed_summary"]
        for fname in ("agency.txt", "stops.txt", "routes.txt", "trips.txt",
                      "stop_times.txt", "calendar.txt"):
            assert fname in fs["files_present"], f"{fname} missing from files_present"

    def test_no_missing_required_files(self):
        response = self._post_fixture()
        fs = response.json()["feed_summary"]
        # All required files are present, so files_missing should only list
        # the calendar files that are absent (calendar_dates.txt is optional
        # when calendar.txt is present).
        # For a perfect feed, no *required* files should be missing.
        blockers = [
            i for i in response.json()["issues"]
            if i["severity"] == "BLOCKER"
        ]
        assert blockers == [], f"Unexpected blockers: {blockers}"

    def test_cleaning_log_is_list(self):
        response = self._post_fixture()
        assert isinstance(response.json()["cleaning_log"], list)

    # --- Error handling ---

    def test_not_a_zip_returns_400(self):
        response = client.post(
            "/validate",
            files={"file": ("bad.zip", io.BytesIO(b"not a zip"), "application/zip")},
        )
        assert response.status_code == 400
        assert "zip" in response.json()["detail"].lower()

    def test_no_input_returns_422(self):
        response = client.post("/validate")
        assert response.status_code == 422

    def test_url_and_file_both_provided_file_wins(self):
        """When both are supplied, the file upload takes precedence."""
        with open(FIXTURE_ZIP, "rb") as f:
            zip_bytes = f.read()
        # url points to something invalid — but file should win
        response = client.post(
            "/validate",
            data={"url": "http://this-should-be-ignored.example.com/feed.zip"},
            files={"file": ("feed.zip", io.BytesIO(zip_bytes), "application/zip")},
        )
        assert response.status_code == 200

    def test_feed_with_missing_required_file_has_blocker(self):
        """A zip that omits stops.txt should produce a BLOCKER issue."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("agency.txt",
                        "agency_id,agency_name,agency_url,agency_timezone\n"
                        "1,Test,https://example.com,UTC\n")
            zf.writestr("routes.txt", "route_id,route_type\nR1,3\n")
            zf.writestr("trips.txt", "route_id,service_id,trip_id\nR1,WD,T1\n")
            zf.writestr("stop_times.txt",
                        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                        "T1,08:00:00,08:01:00,S1,1\n")
            zf.writestr("calendar.txt",
                        "service_id,monday,tuesday,wednesday,thursday,friday,"
                        "saturday,sunday,start_date,end_date\n"
                        "WD,1,1,1,1,1,0,0,20240101,20241231\n")
        # stops.txt intentionally omitted

        response = _post_zip_bytes(buf.getvalue())
        assert response.status_code == 200
        data = response.json()
        blockers = [i for i in data["issues"] if i["severity"] == "BLOCKER"]
        blocker_files = {i["file"] for i in blockers}
        assert "stops.txt" in blocker_files
        assert data["health_score"] < 1.0
        assert data["usable_data"]["stops"] is False
        assert data["safe_insights"]["stop_count"] is None

    def test_feed_with_integrity_error_has_blocker(self):
        """A trip referencing a non-existent route_id should produce a BLOCKER."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("agency.txt",
                        "agency_id,agency_name,agency_url,agency_timezone\n"
                        "1,Test,https://example.com,UTC\n")
            zf.writestr("stops.txt",
                        "stop_id,stop_name,stop_lat,stop_lon\n"
                        "S1,Stop 1,37.0,-122.0\n")
            zf.writestr("routes.txt", "route_id,route_type\nR1,3\n")
            zf.writestr("trips.txt",
                        "route_id,service_id,trip_id\n"
                        "R1,WD,T1\n"
                        "R_GHOST,WD,T2\n")  # R_GHOST does not exist
            zf.writestr("stop_times.txt",
                        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                        "T1,08:00:00,08:01:00,S1,1\n"
                        "T2,09:00:00,09:01:00,S1,1\n")
            zf.writestr("calendar.txt",
                        "service_id,monday,tuesday,wednesday,thursday,friday,"
                        "saturday,sunday,start_date,end_date\n"
                        "WD,1,1,1,1,1,0,0,20240101,20241231\n")

        response = _post_zip_bytes(buf.getvalue())
        assert response.status_code == 200
        data = response.json()
        blockers = [i for i in data["issues"] if i["severity"] == "BLOCKER"]
        route_blockers = [i for i in blockers
                          if i["file"] == "trips.txt" and i["field"] == "route_id"]
        assert len(route_blockers) == 1
        assert route_blockers[0]["count"] == 1


# ---------------------------------------------------------------------------
# Network tests (skipped when network unavailable)
# ---------------------------------------------------------------------------

def _network_available() -> bool:
    """Return True if we can reach GitHub to download the test feed."""
    try:
        resp = requests.head("https://github.com", timeout=5)
        return resp.status_code < 500
    except Exception:
        return False


@pytest.mark.network
@pytest.mark.skipif(not _network_available(), reason="Network not available")
class TestValidateWithRealFeed:
    """
    Downloads a small real GTFS zip from a public GitHub URL and validates it.

    These tests check the response shape only — they do not assert a specific
    health score because real feeds may have data quality issues.
    """

    @pytest.fixture(scope="class")
    def real_feed_response(self):
        """Download the real feed once and cache the response for the class."""
        try:
            r = requests.get(NETWORK_GTFS_URL, timeout=30)
            r.raise_for_status()
        except Exception as exc:
            pytest.skip(f"Could not download real GTFS feed: {exc}")

        return _post_zip_bytes(r.content)

    def test_returns_200(self, real_feed_response):
        assert real_feed_response.status_code == 200, real_feed_response.text

    def test_response_shape(self, real_feed_response):
        _assert_health_report_shape(real_feed_response.json())

    def test_health_score_in_range(self, real_feed_response):
        score = real_feed_response.json()["health_score"]
        assert 0.0 <= score <= 1.0

    def test_files_present_list_non_empty(self, real_feed_response):
        fs = real_feed_response.json()["feed_summary"]
        assert len(fs["files_present"]) > 0

    def test_usable_data_flags_are_booleans(self, real_feed_response):
        ud = real_feed_response.json()["usable_data"]
        for key in ("routes", "stops", "trips", "service_calendar"):
            assert isinstance(ud[key], bool), f"usable_data.{key} is not a bool"

    def test_safe_insights_present(self, real_feed_response):
        si = real_feed_response.json()["safe_insights"]
        for key in ("route_count", "stop_count", "trip_count", "agency_count", "service_days"):
            assert key in si, f"safe_insights.{key} is missing"

    def test_cleaning_log_is_list(self, real_feed_response):
        assert isinstance(real_feed_response.json()["cleaning_log"], list)
