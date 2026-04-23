"""
tests/test_parser.py

Unit tests for backend/parser/loader.py and backend/parser/gtfs_parser.py.

Run with:  pytest tests/test_parser.py -v

Fixtures are minimal in-memory zips constructed by the tests themselves so
no external files are required for the basic suite.  Feed-level fixtures (real
GTFS zips) belong in tests/fixtures/ and are used for integration tests.
"""

from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backend.parser.loader import load_from_bytes, load_from_url
from backend.parser.gtfs_parser import parse_gtfs_files, GTFSData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_zip(files: dict[str, str]) -> bytes:
    """Create an in-memory zip from a dict of {filename: csv_string}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


MINIMAL_AGENCY_CSV = "agency_id,agency_name,agency_url,agency_timezone\n1,Test Agency,https://example.com,America/New_York\n"
MINIMAL_STOPS_CSV = "stop_id,stop_name,stop_lat,stop_lon\nS1,Main St,40.7128,-74.0060\n"


# ---------------------------------------------------------------------------
# loader.py tests
# ---------------------------------------------------------------------------

class TestLoadFromBytes:
    def test_valid_zip_returns_txt_files(self):
        data = _make_zip({"agency.txt": MINIMAL_AGENCY_CSV, "stops.txt": MINIMAL_STOPS_CSV})
        result = load_from_bytes(data)
        assert "agency.txt" in result
        assert "stops.txt" in result

    def test_non_txt_files_excluded(self):
        data = _make_zip({"agency.txt": MINIMAL_AGENCY_CSV, "README.md": "hello"})
        result = load_from_bytes(data)
        assert "agency.txt" in result
        assert "README.md" not in result

    def test_invalid_zip_raises_bad_zip_file(self):
        with pytest.raises(zipfile.BadZipFile):
            load_from_bytes(b"not a zip file")

    def test_empty_zip_returns_empty_dict(self):
        data = _make_zip({})
        result = load_from_bytes(data)
        assert result == {}


class TestLoadFromUrl:
    def test_successful_download(self):
        zip_bytes = _make_zip({"agency.txt": MINIMAL_AGENCY_CSV})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content = lambda chunk_size: iter([zip_bytes])

        with patch("backend.parser.loader.requests.get", return_value=mock_response):
            result = load_from_url("http://example.com/gtfs.zip")

        assert "agency.txt" in result

    def test_non_200_status_raises_value_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("backend.parser.loader.requests.get", return_value=mock_response):
            with pytest.raises(ValueError, match="HTTP 404"):
                load_from_url("http://example.com/gtfs.zip")

    def test_size_limit_exceeded_raises_value_error(self):
        # Simulate a response that's larger than the cap
        large_chunk = b"x" * 1024
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content = lambda chunk_size: iter([large_chunk] * 10)

        with patch("backend.parser.loader.requests.get", return_value=mock_response):
            with pytest.raises(ValueError, match="size limit"):
                load_from_url("http://example.com/gtfs.zip", max_bytes=5000)


# ---------------------------------------------------------------------------
# gtfs_parser.py tests
# ---------------------------------------------------------------------------

class TestParseGtfsFiles:
    def test_parses_present_files(self):
        raw = {
            "agency.txt": MINIMAL_AGENCY_CSV.encode(),
            "stops.txt": MINIMAL_STOPS_CSV.encode(),
        }
        result = parse_gtfs_files(raw)
        assert isinstance(result, GTFSData)
        assert result.agency is not None
        assert len(result.agency) == 1
        assert result.stops is not None
        assert len(result.stops) == 1

    def test_missing_file_returns_none(self):
        raw = {"agency.txt": MINIMAL_AGENCY_CSV.encode()}
        result = parse_gtfs_files(raw)
        assert result.stops is None
        assert result.trips is None

    def test_empty_file_returns_empty_dataframe(self):
        # Only header, no data rows
        raw = {"stops.txt": b"stop_id,stop_name,stop_lat,stop_lon\n"}
        result = parse_gtfs_files(raw)
        assert result.stops is not None
        assert isinstance(result.stops, pd.DataFrame)
        assert len(result.stops) == 0
        assert "stop_id" in result.stops.columns

    def test_zero_byte_file_treated_as_absent(self):
        raw = {"stops.txt": b""}
        result = parse_gtfs_files(raw)
        assert result.stops is None
        assert any("empty" in entry.lower() for entry in result.cleaning_log)

    def test_whitespace_stripped_from_string_columns(self):
        csv = "stop_id,stop_name,stop_lat,stop_lon\n S1 , Main St ,40.7128,-74.0060\n"
        raw = {"stops.txt": csv.encode()}
        result = parse_gtfs_files(raw)
        assert result.stops["stop_id"].iloc[0] == "S1"
        assert result.stops["stop_name"].iloc[0] == "Main St"

    def test_latin1_fallback(self):
        # agency_name contains a non-UTF-8 byte (latin-1 encoded é).
        # The raw bytes must be passed as bytes, not a Python str, because
        # parse_gtfs_files() and io.BytesIO() expect bytes objects.
        csv_bytes = b"agency_id,agency_name,agency_url,agency_timezone\n1,Caf\xe9 Transit,https://example.com,UTC\n"
        raw = {"agency.txt": csv_bytes}
        result = parse_gtfs_files(raw)
        assert result.agency is not None
        assert "é" in result.agency["agency_name"].iloc[0]
        assert any("latin" in entry.lower() for entry in result.cleaning_log)

    def test_unknown_files_recorded(self):
        raw = {
            "agency.txt": MINIMAL_AGENCY_CSV.encode(),
            "custom_data.txt": b"col1,col2\nval1,val2\n",
        }
        result = parse_gtfs_files(raw)
        assert "custom_data.txt" in result.unknown_files

    def test_files_present_list_populated(self):
        raw = {"agency.txt": MINIMAL_AGENCY_CSV.encode()}
        result = parse_gtfs_files(raw)
        assert "agency.txt" in result.files_present
