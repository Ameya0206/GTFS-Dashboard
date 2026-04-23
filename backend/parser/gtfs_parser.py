"""
backend/parser/gtfs_parser.py

Converts the raw bytes produced by loader.py into pandas DataFrames, one per
GTFS file.  The public interface is `parse_gtfs_files()` which takes the dict
from the loader and returns a `GTFSData` named container.

Design decisions and edge cases:
- Missing files: returned as None in GTFSData, not raised.  Callers (validators)
  decide whether absence is a BLOCKER.
- Encoding: tries UTF-8 first, falls back to latin-1.  UTF-8-BOM (common in
  feeds exported from Windows tools) is handled transparently by specifying
  encoding="utf-8-sig" as the primary attempt.
- Empty files (zero rows after header): returned as an empty DataFrame whose
  columns match the header row, so downstream code can always call .columns.
- Malformed rows (wrong number of fields): pandas' `on_bad_lines="warn"` skips
  them and logs a warning.  We additionally capture a count of skipped rows via
  a custom approach and record it in the cleaning_log.
- BOM characters in column names: stripped by utf-8-sig and also via a manual
  strip as a belt-and-suspenders measure.
- Whitespace in values: stripped from all string columns to avoid silent
  mismatches during referential integrity checks.
- The parser never modifies values beyond stripping whitespace — no type coercion
  happens here.  Field-level type validation is the validator's responsibility.
"""

from __future__ import annotations

import io
import logging
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GTFS file catalogue
# ---------------------------------------------------------------------------

# Required files per the GTFS spec (calendar situation handled separately)
REQUIRED_FILES = [
    "agency.txt",
    "stops.txt",
    "routes.txt",
    "trips.txt",
    "stop_times.txt",
]

# Calendar: at least one of these must be present
CALENDAR_FILES = [
    "calendar.txt",
    "calendar_dates.txt",
]

# Optional files that are commonly present
OPTIONAL_FILES = [
    "shapes.txt",
    "fare_attributes.txt",
    "fare_rules.txt",
    "frequencies.txt",
    "transfers.txt",
    "feed_info.txt",
]

ALL_KNOWN_FILES = REQUIRED_FILES + CALENDAR_FILES + OPTIONAL_FILES


# ---------------------------------------------------------------------------
# Container for parsed data
# ---------------------------------------------------------------------------

@dataclass
class GTFSData:
    """
    Holds one DataFrame (or None) per GTFS file, plus metadata populated
    during parsing.

    Attributes set to None indicate the file was absent from the zip.
    Attributes that are empty DataFrames indicate the file was present
    but contained no data rows.

    `cleaning_log` accumulates a human-readable record of every adjustment
    made during parsing so nothing is silently transformed.
    """

    agency: Optional[pd.DataFrame] = None
    stops: Optional[pd.DataFrame] = None
    routes: Optional[pd.DataFrame] = None
    trips: Optional[pd.DataFrame] = None
    stop_times: Optional[pd.DataFrame] = None
    calendar: Optional[pd.DataFrame] = None
    calendar_dates: Optional[pd.DataFrame] = None
    shapes: Optional[pd.DataFrame] = None
    fare_attributes: Optional[pd.DataFrame] = None
    fare_rules: Optional[pd.DataFrame] = None
    frequencies: Optional[pd.DataFrame] = None
    transfers: Optional[pd.DataFrame] = None
    feed_info: Optional[pd.DataFrame] = None

    # Files present in the zip that we do not recognise
    unknown_files: List[str] = field(default_factory=list)

    # Files present in the zip (names only)
    files_present: List[str] = field(default_factory=list)

    # Transformations and anomalies recorded during parsing
    cleaning_log: List[str] = field(default_factory=list)


# Mapping from GTFS filename to the GTFSData attribute name
_FILE_TO_ATTR: Dict[str, str] = {
    "agency.txt": "agency",
    "stops.txt": "stops",
    "routes.txt": "routes",
    "trips.txt": "trips",
    "stop_times.txt": "stop_times",
    "calendar.txt": "calendar",
    "calendar_dates.txt": "calendar_dates",
    "shapes.txt": "shapes",
    "fare_attributes.txt": "fare_attributes",
    "fare_rules.txt": "fare_rules",
    "frequencies.txt": "frequencies",
    "transfers.txt": "transfers",
    "feed_info.txt": "feed_info",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_gtfs_files(raw_files: Dict[str, bytes]) -> GTFSData:
    """
    Convert a dict of {filename: bytes} (from loader.py) into a GTFSData
    container of DataFrames.

    Parameters
    ----------
    raw_files:
        Dict mapping GTFS filenames (e.g. "stops.txt") to their raw bytes.
        Typically the output of loader.load_from_bytes() or load_from_url().

    Returns
    -------
    GTFSData
        Container with one attribute per known GTFS file.  Unknown files are
        listed in GTFSData.unknown_files.
    """
    data = GTFSData()
    data.files_present = list(raw_files.keys())

    for filename, content in raw_files.items():
        attr_name = _FILE_TO_ATTR.get(filename)

        if attr_name is None:
            data.unknown_files.append(filename)
            logger.info("Unknown GTFS file encountered and skipped: %s", filename)
            continue

        df, log_entries = _parse_single_file(filename, content)
        setattr(data, attr_name, df)
        data.cleaning_log.extend(log_entries)

    return data


# ---------------------------------------------------------------------------
# Single-file parser
# ---------------------------------------------------------------------------

def _parse_single_file(
    filename: str, content: bytes
) -> tuple[Optional[pd.DataFrame], List[str]]:
    """
    Parse one GTFS text file from raw bytes into a DataFrame.

    Returns a (DataFrame | None, list_of_log_entries) tuple.
    Returns (None, []) only if content is completely empty (zero bytes).
    Returns (empty_DataFrame, log) if there is a header but no data rows.
    """
    log: List[str] = []

    # Truly empty file (not even a header)
    if not content.strip():
        log.append(f"{filename}: file is empty (0 bytes). Treated as absent.")
        return None, log

    # Attempt encoding: utf-8-sig handles BOM transparently
    df, encoding_used = _read_csv_with_fallback(filename, content, log)

    if df is None:
        # Could not parse at all — treat as absent and log
        return None, log

    # Strip BOM artifacts from column names (belt-and-suspenders)
    df.columns = [col.lstrip("\ufeff").strip() for col in df.columns]

    # Strip leading/trailing whitespace from all string columns.
    # This is the ONLY value transformation applied in the parser layer.
    # It is logged so it is not silent.
    str_cols = df.select_dtypes(include="object").columns.tolist()
    if str_cols:
        df[str_cols] = df[str_cols].apply(
            lambda col: col.str.strip() if col.dtype == object else col
        )
        log.append(
            f"{filename}: stripped leading/trailing whitespace from "
            f"{len(str_cols)} string column(s) [{', '.join(str_cols)}]."
        )

    if len(df) == 0:
        log.append(
            f"{filename}: file parsed successfully but contains 0 data rows "
            f"(encoding: {encoding_used})."
        )
    else:
        logger.debug(
            "%s: parsed %d rows, %d columns (encoding: %s)",
            filename,
            len(df),
            len(df.columns),
            encoding_used,
        )

    return df, log


def _read_csv_with_fallback(
    filename: str, content: bytes, log: List[str]
) -> tuple[Optional[pd.DataFrame], str]:
    """
    Try to parse CSV bytes using UTF-8-sig first, then latin-1.

    Uses pandas `on_bad_lines="warn"` so malformed rows are skipped rather
    than raising an exception.  We capture the warnings to count and log
    bad lines.

    Returns (DataFrame | None, encoding_string).
    """
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always")
                df = pd.read_csv(
                    io.BytesIO(content),
                    encoding=encoding,
                    dtype=str,           # Keep everything as strings; type validation is the validator's job
                    on_bad_lines="warn", # Skip malformed rows, emit warning
                    skipinitialspace=True,
                )

            # Count and log bad-line warnings
            bad_line_warnings = [
                w for w in caught_warnings
                if issubclass(w.category, pd.errors.ParserWarning)
            ]
            if bad_line_warnings:
                count = len(bad_line_warnings)
                log.append(
                    f"{filename}: {count} malformed row(s) skipped during parsing "
                    f"(encoding: {encoding}). These rows had an unexpected number of fields."
                )
                logger.warning(
                    "%s: %d malformed row(s) skipped (encoding: %s)",
                    filename,
                    count,
                    encoding,
                )

            if encoding != "utf-8-sig":
                log.append(
                    f"{filename}: UTF-8 decoding failed; successfully parsed using {encoding}."
                )

            return df, encoding

        except UnicodeDecodeError:
            # Will try the next encoding in the loop
            logger.debug("%s: failed to decode with %s, trying next.", filename, encoding)
            continue
        except pd.errors.EmptyDataError:
            # File has content but no parseable CSV (e.g. only whitespace lines)
            log.append(f"{filename}: file appears to have no parseable CSV content.")
            return None, encoding
        except Exception as exc:  # noqa: BLE001
            log.append(f"{filename}: unexpected parse error ({type(exc).__name__}: {exc}).")
            logger.exception("Unexpected error parsing %s", filename)
            return None, encoding

    # Should not be reached given the encodings list, but be safe
    log.append(f"{filename}: could not parse with any supported encoding.")
    return None, "unknown"
