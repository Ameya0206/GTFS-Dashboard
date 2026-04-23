"""
backend/parser/loader.py

Responsible for ingesting a GTFS feed from two possible sources:
  1. A file upload (raw bytes of a zip archive sent via multipart form data)
  2. A URL pointing to a remote zip file

In both cases the zip is opened entirely in memory — nothing is written to disk.
The result is a dict mapping filename (e.g. "stops.txt") to raw bytes, covering
every .txt file found at the root of the archive (GTFS files must not be nested
inside sub-directories to be spec-compliant, but we do a shallow scan).

Edge cases handled:
- URL download failures: raises a descriptive ValueError rather than crashing.
- Non-zip bytes: ZipFile will raise BadZipFile, which is allowed to propagate
  so callers can present a clear error to the user.
- Zip entries inside sub-directories: skipped (only root-level .txt files are
  returned, matching the GTFS spec).
- Very large remote files: downloaded with a streaming response and a configurable
  size cap (DEFAULT_MAX_BYTES) to avoid exhausting memory. Raises ValueError if
  the cap is exceeded.
- Connection/timeout errors from requests are re-raised as ValueError with a
  user-friendly message.
"""

from __future__ import annotations

import io
import zipfile
from typing import Dict

import requests

# 200 MB hard cap on remote downloads.  Local uploads are trusted to be
# controlled by FastAPI's own upload size limits.
DEFAULT_MAX_BYTES = 200 * 1024 * 1024  # 200 MB


def load_from_bytes(data: bytes) -> Dict[str, bytes]:
    """
    Open a zip archive from raw bytes and return its GTFS text files.

    Parameters
    ----------
    data:
        Raw bytes of a zip file (e.g. from an HTTP multipart upload).

    Returns
    -------
    dict mapping filename -> raw file bytes for every .txt file at the
    root of the archive.

    Raises
    ------
    zipfile.BadZipFile
        If `data` is not a valid zip archive.
    """
    return _extract_txt_files(io.BytesIO(data))


def load_from_url(url: str, max_bytes: int = DEFAULT_MAX_BYTES) -> Dict[str, bytes]:
    """
    Download a zip file from `url` and return its GTFS text files.

    Streams the response in chunks so that very large files don't load
    entirely into memory before we know the size.

    Parameters
    ----------
    url:
        HTTP/HTTPS URL pointing to a GTFS zip file.
    max_bytes:
        Maximum number of bytes to download.  Raises ValueError if
        the remote file exceeds this limit.

    Returns
    -------
    dict mapping filename -> raw file bytes for every .txt file at the
    root of the archive.

    Raises
    ------
    ValueError
        For network errors, non-200 status codes, or oversized files.
    zipfile.BadZipFile
        If the downloaded content is not a valid zip archive.
    """
    try:
        response = requests.get(url, stream=True, timeout=30)
    except requests.exceptions.ConnectionError as exc:
        raise ValueError(f"Could not connect to URL: {url!r}. Detail: {exc}") from exc
    except requests.exceptions.Timeout as exc:
        raise ValueError(f"Request timed out for URL: {url!r}.") from exc
    except requests.exceptions.RequestException as exc:
        raise ValueError(f"Request failed for URL: {url!r}. Detail: {exc}") from exc

    if response.status_code != 200:
        raise ValueError(
            f"URL returned HTTP {response.status_code}: {url!r}"
        )

    buffer = io.BytesIO()
    downloaded = 0
    chunk_size = 65_536  # 64 KB chunks

    for chunk in response.iter_content(chunk_size=chunk_size):
        if chunk:
            downloaded += len(chunk)
            if downloaded > max_bytes:
                raise ValueError(
                    f"Remote file exceeds the {max_bytes // (1024 * 1024)} MB size limit. "
                    "Download aborted."
                )
            buffer.write(chunk)

    buffer.seek(0)
    return _extract_txt_files(buffer)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_txt_files(zip_buffer: io.BytesIO) -> Dict[str, bytes]:
    """
    Open a zip from a BytesIO buffer and return root-level .txt files.

    Only files whose ZipInfo.filename does not contain a path separator are
    included — this matches the GTFS spec requirement that files live at the
    archive root.
    """
    result: Dict[str, bytes] = {}

    with zipfile.ZipFile(zip_buffer, "r") as zf:
        for info in zf.infolist():
            filename = info.filename

            # Skip directories and nested files
            if info.is_dir():
                continue
            # Normalise separators and reject anything with a path component
            if "/" in filename.lstrip("/") and filename.lstrip("/").index("/") != len(filename.lstrip("/")) - 1:
                # More precisely: skip if there's a directory component before the filename
                parts = filename.replace("\\", "/").split("/")
                if len(parts) > 1 and parts[0] != "":
                    # File is inside a sub-directory — skip
                    continue

            if not filename.endswith(".txt"):
                continue

            # Strip any leading directory component that might remain
            bare_name = filename.replace("\\", "/").split("/")[-1]
            result[bare_name] = zf.read(info.filename)

    return result
