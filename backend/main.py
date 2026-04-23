"""
backend/main.py

FastAPI application entry point for the GTFS Dashboard.

Exposes a single endpoint for the MVP:
  POST /validate
    - Accepts a multipart file upload (zip) OR a JSON body { "url": "..." }
    - Returns a HealthReport JSON object

Edge cases handled here:
- If both `file` and `url` are provided, the uploaded file takes precedence.
- If neither is provided, a 422 is returned with a descriptive message.
- If the zip is invalid (bad format), a 400 is returned.
- If the URL is unreachable or returns a non-200, a 400 is returned.
- Unexpected internal errors are caught and returned as 500 with a safe message.
- File size for uploads is not capped in this layer — set that in a reverse
  proxy (nginx/caddy) or FastAPI's own middleware for production.

Pipeline (per request):
  1. Ingest  — load_from_bytes / load_from_url  →  dict[filename, bytes]
  2. Parse   — parse_gtfs_files                 →  GTFSData
  3. Validate— validate(gtfs_data)              →  HealthReport
     (The validator orchestrator already calls safe_insights internally, so
     main.py does not need to call safe_insights directly.)
"""

from __future__ import annotations

import logging
import zipfile
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from backend.models.report import HealthReport
from backend.parser.loader import load_from_bytes, load_from_url
from backend.parser.gtfs_parser import parse_gtfs_files
from backend.validator import validate

logger = logging.getLogger(__name__)

app = FastAPI(
    title="GTFS Dashboard API",
    description="Feed health and validation tool for GTFS static feeds.",
    version="0.1.0",
)

# Allow local frontend dev server (Vite defaults to :5173) to hit the API.
# Tighten this for production deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check() -> dict:
    """Simple liveness check. Returns 200 if the server is running."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Main validation endpoint
# ---------------------------------------------------------------------------

@app.post("/validate", response_model=HealthReport)
async def validate_feed(
    file: Optional[UploadFile] = File(default=None),
    url: Optional[str] = Form(default=None),
) -> HealthReport:
    """
    Validate a GTFS feed supplied either as a zip upload or a remote URL.

    Multipart form fields
    ---------------------
    file : zip file upload (optional if `url` is provided)
    url  : HTTP/HTTPS URL pointing to a GTFS zip (optional if `file` is provided)

    Returns
    -------
    HealthReport JSON with:
    - feed_summary  : agency name, feed version, files present/missing
    - health_score  : 0.0 (broken) to 1.0 (fully valid)
    - issues        : list of BLOCKER / WARNING / INFO issues with context
    - usable_data   : per-group boolean flags (routes, stops, trips, calendar)
    - safe_insights : counts derived only from validated, usable data
    - cleaning_log  : record of every transformation applied during parsing

    Notes
    -----
    - If both `file` and `url` are provided, `file` takes precedence.
    - Feed validation is synchronous inside this async handler; for large feeds
      consider wrapping in `asyncio.to_thread()` in a production deployment.
    """
    # --- 1. Ingest -------------------------------------------------------
    raw_files: dict[str, bytes]

    if file is not None:
        # Uploaded zip
        content = await file.read()
        try:
            raw_files = load_from_bytes(content)
        except zipfile.BadZipFile:
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is not a valid zip archive.",
            )
        except Exception as exc:
            logger.exception("Failed to read uploaded zip file.")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to read uploaded file: {exc}",
            )
    elif url:
        # Remote URL
        try:
            raw_files = load_from_url(url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except zipfile.BadZipFile:
            raise HTTPException(
                status_code=400,
                detail="The content at the provided URL is not a valid zip archive.",
            )
        except Exception as exc:
            logger.exception("Failed to download feed from URL: %s", url)
            raise HTTPException(
                status_code=400,
                detail=f"Failed to download feed from URL: {exc}",
            )
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide either a 'file' upload or a 'url' form field.",
        )

    # --- 2. Parse --------------------------------------------------------
    try:
        gtfs_data = parse_gtfs_files(raw_files)
    except Exception as exc:
        logger.exception("Unexpected error during GTFS parsing.")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error during feed parsing: {exc}",
        )

    # --- 3. Validate (includes safe insights derivation) -----------------
    try:
        report = validate(gtfs_data)
    except Exception as exc:
        logger.exception("Unexpected error during GTFS validation.")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error during feed validation: {exc}",
        )

    return report
