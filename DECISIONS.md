# Architecture Decisions Log

## 2026-04-13 Decision: Stateless per-request processing (no database)
**Context**: MVP needs to work across many agencies without setup overhead  
**Decision**: All GTFS processing is stateless — no DB, no persistence  
**Rationale**: Simplicity, portability, no data retention concerns for agency feeds  
**Alternatives considered**: SQLite for caching results, PostgreSQL for multi-feed history

## 2026-04-13 Decision: Custom GTFS parser over existing libraries
**Context**: Existing Python GTFS libraries (gtfs-kit, partridge) assume clean feeds  
**Decision**: Build a custom parser that handles missing files, malformed rows, and encoding issues gracefully  
**Rationale**: Our core value proposition is handling dirty feeds — can't rely on libraries that fail silently  
**Alternatives considered**: `partridge`, `gtfs-kit`, `pandas` direct CSV reads

## 2026-04-13 Decision: FastAPI backend + React (Vite) frontend
**Context**: Needed a lightweight, modern stack suitable for local-first MVP  
**Decision**: FastAPI for async Python backend, React/Vite for frontend  
**Rationale**: FastAPI has excellent async file handling and auto-generates OpenAPI docs; Vite is fast to set up  
**Alternatives considered**: Flask, Django, Next.js

## 2026-04-13 Decision: In-memory zip extraction (no disk writes)
**Context**: GTFS zips can be large and multi-user; writing temp files raises cleanup and concurrency concerns  
**Decision**: `loader.py` reads the zip entirely into a `BytesIO` buffer and extracts file bytes to a dict in memory — nothing touches disk  
**Rationale**: Keeps the backend stateless, avoids temp-file cleanup bugs, works cleanly under async FastAPI  
**Alternatives considered**: `tempfile.TemporaryDirectory`, writing to `/tmp`

## 2026-04-13 Decision: Parser applies only whitespace stripping, nothing else
**Context**: Core principle is no silent data transformation  
**Decision**: `gtfs_parser.py` strips leading/trailing whitespace from string columns and logs every instance; all other cleaning deferred to the validator layer which must explicitly log changes  
**Rationale**: Whitespace stripping is universally safe and prevents phantom referential integrity failures (e.g. `" S1"` vs `"S1"`); anything beyond that risks masking real data quality issues  
**Alternatives considered**: Type coercion in parser, no stripping at all

## 2026-04-13 Decision: UTF-8-sig primary encoding with latin-1 fallback
**Context**: Real-world GTFS feeds regularly ship with Windows BOM or latin-1 encoding  
**Decision**: Try `utf-8-sig` first (handles BOM transparently), fall back to `latin-1`  
**Rationale**: `utf-8-sig` is a strict superset for BOM handling; `latin-1` accepts every byte value so it never raises a decode error and is the correct fallback for legacy feeds  
**Alternatives considered**: `chardet` auto-detection (adds dependency, slower), `utf-8` only (breaks on many real feeds)

## 2026-04-13 Decision: Three-tier issue severity (BLOCKER / WARNING / INFO)
**Context**: Need to communicate data quality issues at different urgency levels  
**Decision**: BLOCKER = unusable without fix, WARNING = degraded output, INFO = non-standard but workable  
**Rationale**: Actionability — users need to know what to fix first  
**Alternatives considered**: Binary valid/invalid, numeric score only

## 2026-04-13 Decision: Null check treats empty string and NaN as equivalent
**Context**: GTFS files parsed as string dtype (parser decision); missing values may appear as empty strings rather than NaN after pandas reads them  
**Decision**: field_validator counts both `NaN` and `""` as null/missing when computing null rates  
**Rationale**: After the parser's whitespace strip, a blank field is indistinguishable from a missing one semantically — both mean "no data"  
**Alternatives considered**: Treat empty strings as valid (would undercount data quality issues)

## 2026-04-13 Decision: Null rate threshold at 10% for WARNING
**Context**: Need a concrete threshold to decide when a field's null rate warrants surfacing to the user  
**Decision**: Fields with > 10% null/empty values get a WARNING issue  
**Rationale**: 10% is a common convention for "meaningfully incomplete" in data quality tooling; low enough to catch real problems without being too noisy  
**Alternatives considered**: 5% (too noisy for optional-ish fields), 25% (too permissive)

## 2026-04-13 Decision: Health score uses weighted penalty formula (BLOCKER weight 4×)
**Context**: Single numeric score needed that reflects both blockers and warnings, with blockers being more severe  
**Decision**: `score = 1.0 - (4 * blockers + 1 * warnings) / (4 * blockers + 1 * warnings + 5)`. Baseline denominator of +5 prevents a single warning from collapsing the score too far  
**Rationale**: Heuristic formula that is transparent and tunable; BLOCKER/WARNING ratio of 4:1 matches the severity naming intent  
**Alternatives considered**: Simple blocker count fraction, pass/fail binary, external scoring library

## 2026-04-13 Decision: Usable data flag for trips requires both routes AND calendar to be usable
**Context**: A trip record is only meaningful if its referenced route and service schedule are also valid  
**Decision**: `usable_data.trips` is True only when routes, calendar, trips, and stop_times are all free of BLOCKERs and non-empty  
**Rationale**: A trip count derived from trips with broken route or calendar references would be misleading — better to surface null than a wrong number  
**Alternatives considered**: Flag trips as usable independently (risks fabricating insights from partial data)

## 2026-04-13 Decision: Calendar validator returns service_ids and service_days to orchestrator
**Context**: Insights layer needs the set of valid service_ids (to inform integrity checks) and active weekday names (for the service_days safe insight) without re-scanning the DataFrames  
**Decision**: `validate_calendar()` returns a 3-tuple: `(issues, service_ids, service_days)` instead of issues-only  
**Rationale**: Avoids a second pass over the calendar DataFrames in the orchestrator; keeps calendar logic co-located with calendar data  
**Alternatives considered**: Have orchestrator re-derive service_days directly from calendar DataFrame

## 2026-04-13 Decision: Integrity validator skips checks when source DataFrame is None or empty
**Context**: A feed with a missing required file will have None for that DataFrame; running set operations on None would crash  
**Decision**: Each integrity check calls `_is_empty()` which returns True for None, 0-row DataFrames, or DataFrames missing the join column — skipping silently  
**Rationale**: Absence is already flagged as BLOCKER by file_validator; double-reporting the same root cause adds noise without adding information  
**Alternatives considered**: Raise an exception (bad UX), generate a duplicate issue (noisy)

## 2026-04-13 Decision: safe_insights.py is a standalone module with a skipped_insights log
**Context**: The spec required a dedicated `backend/insights/safe_insights.py`; however the validator orchestrator already derived insights inline. We need a clean module boundary.  
**Decision**: `safe_insights.py` exposes `derive_safe_insights(gtfs_data, usable_data) -> (SafeInsights, skipped_insights)`. It is called by the validator orchestrator, which passes the already-computed `UsableData` flags. The `skipped_insights` list is returned but not included in the HealthReport schema (it is used for internal logging/debugging).  
**Rationale**: Keeps insight derivation logic co-located and testable in isolation; the orchestrator remains the single place that assembles the final HealthReport  
**Alternatives considered**: Embedding insight logic only in the orchestrator (harder to test in isolation), including `skipped_insights` in the HealthReport JSON (adds noise for end users)

## 2026-04-13 Decision: service_days is None when only calendar_dates.txt is present
**Context**: `service_days` is defined as a list of weekday names (monday–sunday). calendar_dates.txt encodes specific calendar dates with added/removed exceptions, not repeating weekday patterns.  
**Decision**: `service_days` is derived only from calendar.txt weekday columns. When only calendar_dates.txt is present, `service_days` is set to None and the reason is recorded in `skipped_insights`.  
**Rationale**: Fabricating weekday patterns from specific dates would require assumptions about the schedule that the tool cannot safely make  
**Alternatives considered**: Infer weekday patterns from the day-of-week distribution of calendar_dates entries (too speculative, violates the no-fabrication principle)

## 2026-04-13 Decision: main.py wires directly to validator.__init__.validate() — no separate insights call
**Context**: The validator orchestrator already calls `derive_safe_insights()` internally and returns a fully populated HealthReport.  
**Decision**: `main.py` calls `validate(gtfs_data)` and returns the result directly. It does not call `safe_insights` separately.  
**Rationale**: Single orchestration point reduces coupling and keeps main.py minimal (ingest → parse → validate → return)  
**Alternatives considered**: Having main.py call each validator module and the insights module independently (fragile, requires main.py to know validation internals)

## 2026-04-13 Decision: Frontend uses Tailwind CSS utility classes only (no component library)
**Context**: MVP needs a clean, minimal UI without the overhead of a full component library  
**Decision**: Tailwind CSS v3 via PostCSS; no Headless UI, MUI, or Chakra  
**Rationale**: Utility-first approach keeps the bundle small, avoids version-lock on a component library, and gives full control over DOM structure; a full component library would be premature for a single-page triage tool  
**Alternatives considered**: shadcn/ui, Chakra UI, plain CSS modules

## 2026-04-13 Decision: FeedInput uses a tab switcher (file / URL) rather than two separate sections
**Context**: Original stub rendered both input methods simultaneously, making the page feel cluttered  
**Decision**: Two-tab switcher with a shared card container; only one input mode is visible at a time  
**Rationale**: Reduces cognitive load; most users will know which input method they need upfront  
**Alternatives considered**: Both visible simultaneously (original stub layout), separate pages/routes (over-engineered for MVP)

## 2026-04-13 Decision: IssueLog groups and collapses by severity group, not individual issue type
**Context**: A feed can produce dozens of issues; a flat list becomes unreadable quickly  
**Decision**: Issues are grouped into three collapsible sections (BLOCKER / WARNING / INFO). Sections start expanded. Users can collapse any group.  
**Rationale**: Grouping mirrors the severity model already established in the backend; collapsibility lets users focus on BLOCKERs first  
**Alternatives considered**: Flat list with color coding only (original stub), collapsing individual issues, filtering by severity

## 2026-04-13 Decision: InsightsPanel renders null insights as greyed-out cards with a reason string
**Context**: The spec requires transparency about what could not be derived and why  
**Decision**: Each insight key has a static `reason` string in `INSIGHT_META`. Null values render a greyed italic card rather than being hidden or showing "N/A"  
**Rationale**: Hiding null insights would violate the core "transparency is the product" principle; showing a reason string is more actionable than a bare "N/A"  
**Alternatives considered**: Omit null insights entirely, show "N/A" without reason, derive reason dynamically from issue list (complex, brittle)

## 2026-04-13 Decision: Integration test uses a committed fixture zip, with optional network tests
**Context**: Tests that require network access are brittle in CI and slow locally.  
**Decision**: `tests/test_api.py` has two classes: `TestValidateWithFixture` (always runs, uses `tests/fixtures/sample_gtfs.zip`) and `TestValidateWithRealFeed` (marked `@pytest.mark.network`, skipped when GitHub is unreachable). The fixture is a minimal 6-file valid GTFS feed generated by a one-off script.  
**Rationale**: Offline tests are fast and deterministic; network tests provide a smoke-check against a real-world feed without blocking the main suite  
**Alternatives considered**: Mocking the HTTP layer for all tests (loses confidence that real feeds parse correctly), always downloading (brittle in CI)
