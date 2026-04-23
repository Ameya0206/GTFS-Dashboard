# GTFS Dashboard — Project Context for Claude Code

## What this project is

A lightweight GTFS feed triage tool. Users input a GTFS feed (URL or zip upload), and the system:
1. Ingests and parses the GTFS data
2. Validates it (missing files, broken references, nulls, incomplete fields)
3. Flags data quality issues clearly and transparently
4. Performs only safe, explicit cleaning (nothing silent)
5. Generates a dashboard from **only the usable data**

This is NOT a transit analytics platform. It is a **feed health + usability tool**.

---

## Core design principles (never violate these)

- **Never fabricate insights from missing or broken data**
- **Never silently clean or impute data** — all transformations must be logged
- **Transparency is the product** — always show what was excluded and why
- If a file or field is missing, say so clearly rather than proceeding as if it's fine
- The dashboard only renders insights that can be derived from validated, complete data

---

## Tech stack

- **Backend**: Python + FastAPI
- **Frontend**: React (Vite)
- **No database** for MVP — stateless, per-request processing
- **GTFS parsing**: custom parser (do not rely on feed being clean)
- **Deployment target**: local-first for MVP, cloud-ready structure

---

## GTFS required files (per spec)

- `agency.txt`
- `stops.txt`
- `routes.txt`
- `trips.txt`
- `stop_times.txt`
- `calendar.txt` OR `calendar_dates.txt` (at least one required)

Optional but commonly present: `shapes.txt`, `fare_attributes.txt`, `fare_rules.txt`, `frequencies.txt`, `transfers.txt`, `feed_info.txt`

---

## Validator logic (build this first)

The validator should check and return structured results for:

### File-level checks
- Required files present or missing
- Optional files detected

### Field-level checks (per file)
- Required fields present
- Null / empty value rates per field
- Data type correctness (lat/lon are numeric, times are HH:MM:SS format, etc.)

### Referential integrity checks
- All `route_id` values in `trips.txt` exist in `routes.txt`
- All `trip_id` values in `stop_times.txt` exist in `trips.txt`
- All `stop_id` values in `stop_times.txt` exist in `stops.txt`
- All `service_id` values in `trips.txt` exist in `calendar.txt` or `calendar_dates.txt`

### Calendar logic
- Handle `calendar.txt` only, `calendar_dates.txt` only, or both
- Flag if neither is present

### Issue severity tiers
- `BLOCKER` — feed cannot be used without fixing this
- `WARNING` — data will be incomplete or degraded
- `INFO` — non-standard but workable

---

## Health report JSON schema (target output from validator)

```json
{
  "feed_summary": {
    "agency_name": "string or null",
    "feed_version": "string or null",
    "files_present": ["agency.txt", "stops.txt", ...],
    "files_missing": ["shapes.txt", ...]
  },
  "health_score": 0.0,  // 0.0 to 1.0
  "issues": [
    {
      "severity": "BLOCKER | WARNING | INFO",
      "file": "trips.txt",
      "field": "route_id",
      "message": "47 trip records reference route_ids not found in routes.txt",
      "count": 47
    }
  ],
  "usable_data": {
    "routes": true,
    "stops": true,
    "trips": false,
    "service_calendar": true
  },
  "safe_insights": {
    "route_count": 12,
    "stop_count": 340,
    "trip_count": null,  // null = could not be derived safely
    "agency_count": 1,
    "service_days": ["monday", "tuesday", "wednesday", "thursday", "friday"]
  },
  "cleaning_log": []  // log any transformations applied
}
```

---

## Project structure

```
gtfs-dashboard/
├── backend/
│   ├── main.py                  # FastAPI app entry point
│   ├── parser/
│   │   ├── __init__.py
│   │   ├── loader.py            # Ingest zip from URL or upload
│   │   └── gtfs_parser.py       # Parse individual GTFS files into dataframes
│   ├── validator/
│   │   ├── __init__.py
│   │   ├── file_validator.py    # Required/optional file checks
│   │   ├── field_validator.py   # Field presence, nulls, types
│   │   ├── integrity_validator.py # Referential integrity
│   │   └── calendar_validator.py  # Calendar logic
│   ├── insights/
│   │   ├── __init__.py
│   │   └── safe_insights.py     # Only derive insights from validated data
│   └── models/
│       └── report.py            # Pydantic models for health report
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── HealthScorecard.jsx
│   │   │   ├── IssueLog.jsx
│   │   │   └── InsightsPanel.jsx
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── index.html
│   └── vite.config.js
├── tests/
│   ├── test_parser.py
│   ├── test_validator.py
│   └── fixtures/                # Sample GTFS zips for testing
├── CLAUDE.md                    # This file
├── DECISIONS.md                 # Architecture decisions log
└── README.md
```

---

## Build order (follow this sequence)

1. `backend/parser/` — loader + GTFS file parser
2. `backend/validator/` — all four validator modules
3. `backend/models/report.py` — Pydantic health report schema
4. `backend/insights/safe_insights.py` — safe insight derivation
5. `backend/main.py` — FastAPI endpoints (`POST /validate`)
6. `tests/` — unit tests for parser and validator with fixture data
7. `frontend/` — React dashboard shell + components

---

## API endpoints (MVP)

### `POST /validate`
- Accepts: multipart file upload (zip) OR JSON body `{ "url": "https://..." }`
- Returns: health report JSON (see schema above)
- Must handle large files gracefully (stream/chunk if needed)

---

## What NOT to build in MVP

- GTFS-RT (real-time feeds)
- Fare data analysis
- Multi-feed comparison
- Map rendering of shapes/stops
- User accounts or saved reports
- Automated feed fixing with exported edits

---

## DECISIONS.md

Update `DECISIONS.md` whenever you make a non-obvious architectural or implementation choice. Format:

```
## [Date] Decision: <title>
**Context**: why this came up
**Decision**: what was chosen
**Rationale**: why
**Alternatives considered**: what else was on the table
```
