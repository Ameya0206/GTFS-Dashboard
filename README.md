# GTFS Feed Health Dashboard

A lightweight GTFS feed triage tool for transit agencies and consultants. Upload a GTFS zip or provide a URL — the dashboard validates the feed, scores its health, and surfaces consultant-grade insights without fabricating anything from missing data.

## What it does

- **Validates** required files, field completeness, referential integrity, and calendar logic
- **Scores** feed health from 0.0 (broken) to 1.0 (fully valid) with BLOCKER / WARNING / INFO tiers
- **Derives insights** only from data that passes validation — nothing is guessed or imputed
- **Route analysis** — headways, service span, timed stop coverage, wheelchair accessibility, flags per route
- **Transfer hubs** — stops served by 3+ routes
- **Feed expiry** — flags feeds expiring within 30 days

## Live demo

> Coming soon

## Tech stack

- **Backend**: Python + FastAPI
- **Frontend**: React + Vite + Tailwind CSS

## Running locally

**Prerequisites**: Python 3.9+, Node 18+

**Backend**
```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
# Runs on http://localhost:8000
```

**Frontend**
```bash
cd frontend
npm install
npm run dev
# Runs on http://localhost:5173
```

Then open `http://localhost:5173` and upload a GTFS zip or paste a feed URL.

## API

### `POST /validate`

Accepts a GTFS zip as a multipart file upload or a JSON body with a URL.

```bash
# File upload
curl -X POST http://localhost:8000/validate \
  -F "file=@your_feed.zip"

# URL
curl -X POST http://localhost:8000/validate \
  -F "url=https://example.com/gtfs.zip"
```

Returns a health report JSON:

```json
{
  "feed_summary": { "agency_name": "...", "feed_version": "...", "files_present": [], "files_missing": [] },
  "health_score": 0.71,
  "issues": [{ "severity": "WARNING", "file": "stop_times.txt", "field": "arrival_time", "message": "...", "count": 11952 }],
  "usable_data": { "routes": true, "stops": true, "trips": true, "service_calendar": true },
  "safe_insights": {
    "route_count": 16,
    "stop_count": 387,
    "trip_count": 845,
    "feed_expiry_days": 29,
    "wheelchair_accessible_pct": 94.4,
    "timed_stop_pct": 27.2,
    "routes_detail": []
  },
  "cleaning_log": []
}
```

## What it does NOT do (MVP scope)

- GTFS-RT (real-time feeds)
- Ridership or on-time performance analysis
- Multi-feed comparison
- Map rendering
- Automated feed fixing or export

## Test data

Frederick County TransIT (Maryland) GTFS feed sourced from the [Mobility Database](https://mobilitydatabase.org) — MDB source ID 2432.
