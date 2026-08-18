---
title: 'Story 1.1: Backend foundation'
type: 'feature'
created: '2026-08-18'
status: 'done'
baseline_commit: ed2d3647de7ccf44257101b6fb9e685b53351d2c
review_loop_iteration: 0
context:
  - _bmad-output/implementation-artifacts/epic-1-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Job Hunt Aggregator has no code yet; everything (registry, pipeline, worker, UI) depends on a running Django backend with the core data models.

**Approach:** Scaffold the Django 6.1 project under `backend/` with Python 3.13 via uv, configure SQLite (WAL + busy_timeout), and create the `listings` app with the `Source`, `Listing`, and `FetchLog` models (epic boundary: NO `Application` model in this story).

## Boundaries & Constraints

**Always:**
- Python 3.13, Django 6.1, SQLite bundled; run from `backend/` with a uv-managed venv.
- SQLite in WAL mode with busy_timeout set (AD-2 locking story); all writes via Django ORM.
- `Listing.dedup_fingerprint` has a DB unique constraint and is computed once at ingestion (AD-4); `status` default "new"; `seen_sources` append-only JSON; `published_at` ISO-8601 UTC.
- Models live in the `listings` app; only `Source`, `Listing`, `FetchLog` tables may exist after this story.
- `manage.py runserver` must start and migrations must apply cleanly.
- Scaffold per the Structural Seed (`backend/listings/`); do NOT create `collector/`, `api/`, or `frontend/` yet.

**Ask First:**
- Installing a uv-managed Python 3.13 toolchain (`uv python install 3.13`) — user-local download, no admin rights; only alternative is a manual Python 3.12+ install by the user.

**Never:**
- No `Application` model (Epic 2 boundary), no adapters, no pipeline, no API endpoints, no frontend.
- No alternative runtimes (conda, system install), no Postgres, no external hosting.
- Do not pin Django <6.1 or fall back to Python 3.10.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| HAPPY_PATH | fresh scaffold, `python manage.py migrate` | All 3 app tables + Django built-ins created; 0001_initial migration exists | exit non-zero with traceback |
| RUNSERVER | `python manage.py runserver` | Server starts on localhost:8000 with no warnings | error surfaced, fix before done |
| DUP_FINGERPRINT | two Listings with identical fingerprint (e.g. via shell) | Second insert rejected | IntegrityError from DB unique constraint |
| WAL_PRAGMA | any connection opened | `PRAGMA journal_mode` returns `wal` | signal/pragma not applied — must fix |
| DOWNTIME | `python manage.py runserver` with stale sqlite file | WAL/busy_timeout settings still applied | n/a |

</frozen-after-approval>

## Code Map

- `backend/` -- new Django project root (greenfield; Structural Seed, spine §Structural Seed). Root whitelisted in `.gitignore` so it is tracked automatically.
- `backend/manage.py`, `backend/job_hunt_aggregator/` -- Django project package (settings, urls, wsgi/asgi).
- `backend/listings/` -- new app: models `Source`, `Listing`, `FetchLog` (spine: "listings/ — models: Source, Listing, Application, FetchLog"; Application deferred to Epic 2).
- `backend/db.sqlite3` -- runtime artifact; ignored via `*.sqlite3` in `.gitignore`.
- `_bmad-output/implementation-artifacts/epic-1-context.md` -- compiled epic context (stories, requirements, AD-1..AD-10 distillations).
- `_bmad-output/planning-artifacts/architecture/architecture-Job Hunt Mangement System-2026-08-18/ARCHITECTURE-SPINE.md` -- AD-2 (SQLite WAL/busy_timeout single-writer rule), AD-4 (Listing identity rules), Structural Seed layout.

## Tasks & Acceptance

**Execution:**
- [x] `backend/` -- `uv python install 3.13` + `uv venv --python 3.13` + `uv pip install "Django>=6.1,<7"`; scaffold project `job_hunt_aggregator` and app `listings` -- foundation per Structural Seed
- [x] `backend/job_hunt_aggregator/settings.py` -- set SQLite `OPTIONS` with busy_timeout (e.g. `timeout`), add `listings` to INSTALLED_APPS, sensible TIME_ZONE/UTC defaults -- AD-2 concurrency + time handling
- [x] `backend/job_hunt_aggregator/apps.py` (or db init module) -- WAL mode via `connection_created` signal (`PRAGMA journal_mode=WAL`) -- AD-2 locking story
- [x] `backend/listings/models.py` -- `Source` (name, adapter_key, config JSON), `Listing` (dedup_fingerprint unique, title, company, url, published_at nullable, keywords JSON, raw_snapshot JSON, status default "new", seen_sources JSON append-only, source FK nullable), `FetchLog` (source FK, stage, ok, error, created_at) -- Story 1.1 AC + AD-4/AD-6
- [x] `backend/listings/migrations/0001_initial.py` -- `makemigrations` output committed -- schema changes only as migrations (AD-2)
- [x] `backend/README.md` -- how to run: uv venv activation, migrate, runserver -- handoff for next stories
- [x] `backend/listings/tests.py` -- Django tests covering the I/O matrix: (1) fresh DB connection reports journal_mode=wal and busy_timeout>0 (WAL_PRAGMA/DOWNTIME rows), (2) second Listing with identical dedup_fingerprint raises IntegrityError (DUP_FINGERPRINT row), (3) model defaults (status "new", seen_sources [], published_at null) -- matrix rows become automated, repeatable tests (bad_spec loopback entry 1)
- [x] `backend/job_hunt_aggregator/settings.py` -- remove the dead `MAILERS` block -- no email feature exists; dead config misleads (patch, review 1)
- [x] `backend/listings/admin.py` -- register Source, Listing, FetchLog with the admin -- scaffold inspectability for pipeline debugging in later stories (patch, review 1)
- [x] `backend/listings/models.py` + `backend/listings/migrations/0001_initial.py` -- add `db_index=True` to `Listing.published_at` (in lockstep, keep makemigrations clean) -- AD-9 sorted paged queries (patch, review 1)

**Acceptance Criteria:**
- Given an empty workspace, when the backend scaffold is created (Django 6.1, Python 3.13, SQLite WAL + busy_timeout), then `manage.py runserver` starts without errors.
- And the `Source`, `Listing`, and `FetchLog` models exist with migrations applied.
- And `Listing` enforces a unique constraint on `dedup_fingerprint`, carries `status` (default "new"), and an append-only `seen_sources` field.
- And no other tables exist (Application model NOT created).

## Spec Change Log

- **Entry 1 (bad_spec loopback, review 1):** Triggering findings — verification-gap review: (a) matrix rows WAL_PRAGMA/DUP_FINGERPRINT had no automated tests, only human-run CLI probes that a fresh checkout could silently fail (dead signal or removed unique constraint would ship undetected); (b) the Verification section's sqlite3-CLI variant can never satisfy `busy_timeout > 0` (per-connection, defaults 0 on raw CLI) and WAL check passes trivially on the persisted file; (c) the grep-for-Application check false-positives on README/settings wording. Blind-hunter review also flagged zero tests and dead `MAILERS` config. **Amended:** Tasks gained a tests task (WAL pragma + IntegrityError + model defaults as Django tests) and three patch tasks (remove MAILERS, register models in admin, `db_index` on `published_at` for AD-9); Verification commands fixed (Django-connection-only PRAGMA check; grep narrowed to `class Application`). **Known-bad state avoided:** foundation shipping with AD-2/AD-4 invariants unenforced-by-test and verification commands that cannot pass or give false failures. **KEEP (survives re-derivation):** entire scaffold verified correct — models (Source/Listing/FetchLog with unique fingerprint, status default "new", append-only seen_sources, nullable source FK), 0001_initial migration, settings (OPTIONS timeout=30, INSTALLED_APPS, UTC/TZ), WAL+busy_timeout via connection_created signal in listings/apps.py, README conventions; 'applied' status choice kept (Epic 2 boundary); JSON fields for seen_sources/raw_snapshot; no revert performed — the amendment is strictly additive (tests + 3 small patches) and touches no code the root cause drove.

## Design Notes

- **WAL on every connection:** `connection_created` signal is the reliable way to run `PRAGMA journal_mode=WAL` in Django 6.1 (`init_command` was removed in 4.2). busy_timeout maps to SQLite `OPTIONS.timeout`; both must be visible in `PRAGMA` output to satisfy AD-2.
- **Model shape:** `Listing.raw_snapshot` as JSON keeps the raw-data promise (NFR-2) without schema churn when site markup changes; `seen_sources` as JSON list, appended by the pipeline, never overwritten in place by collection (AD-4).
- **Applies-before-status:** `status` choices `new`/`applied` (Epic 2 sets "applied"); the `applied` value may exist as a choice now but only the apply service (Epic 2) may set it.

## Verification

**Commands:**
- `uv run python manage.py check` -- expected: "System check identified no issues (0 silenced)."
- `uv run python manage.py makemigrations --check --dry-run` -- expected: "No changes detected" (migrations committed)
- `uv run python manage.py runserver` -- expected: server starts on localhost:8000; opening http://127.0.0.1:8000/ returns the Django welcome page
- `uv run python manage.py test` -- expected: all tests pass, including the WAL/busy_timeout pragma test and the duplicate-fingerprint IntegrityError test (matrix rows)
- `uv run python manage.py shell -c "from django.db import connection; c=connection.cursor(); c.execute('PRAGMA journal_mode'); print(c.fetchone()); c.execute('PRAGMA busy_timeout'); print(c.fetchone())"` -- expected: `('wal',)` and `(30000,)` on a Django connection (the automated test covers this on a fresh DB file; the raw sqlite3-CLI variant is invalid because busy_timeout is per-connection)
- `uv run python manage.py migrate` -- expected: all migrations applied, `listings_*` tables present in sqlite

**Manual checks (if no CLI):**
- `grep -rn "class Application" backend/` finds nothing (models grep, not a bare word grep — README and the settings "Application definition" comment legitimately contain the word).

## Suggested Review Order

**Data model — design intent**

- Listing identity and state: unique immutable fingerprint, status, append-only seen_sources (AD-4)
  [`models.py:15`](../../backend/listings/models.py#L15)

- FetchLog failure-isolation record (AD-6)
  [`models.py:61`](../../backend/listings/models.py#L61)

- Schema as migration: fingerprint unique constraint, published_at index (AD-9)
  [`0001_initial.py:32`](../../backend/listings/migrations/0001_initial.py#L32)

**SQLite concurrency — the locking story (AD-2)**

- WAL + busy_timeout applied on every connection via signal (Django 4.2+ removed init_command)
  [`apps.py:5`](../../backend/listings/apps.py#L5)

- Settings: OPTIONS.timeout=30 pairs with the signal pragma
  [`settings.py:76`](../../backend/job_hunt_aggregator/settings.py#L76)

**Tests — the matrix rows automated**

- Pragma tests on a fresh file-backed connection (test DB is in-memory; WAL unsupported there), busy_timeout pinned to 30000
  [`tests.py:12`](../../backend/listings/tests.py#L12)

- Duplicate fingerprint → IntegrityError; model defaults incl. refresh_from_db round-trip
  [`tests.py:66`](../../backend/listings/tests.py#L66)

**Peripherals**

- Admin visibility for pipeline debugging; fingerprint read-only (AD-4)
  [`admin.py:8`](../../backend/listings/admin.py#L8)

- Runbook: uv venv, migrate, runserver, test
  [`README.md:1`](../../backend/README.md#L1)