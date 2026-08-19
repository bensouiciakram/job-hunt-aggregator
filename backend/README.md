# Job Hunt Aggregator — Backend

Django 6.1 project under `backend/`, Python 3.13, SQLite (WAL + busy_timeout).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (manages Python 3.13 + the venv).

## Setup

```powershell
uv python install 3.13        # one-time, user-local
uv venv --python 3.13         # creates .venv
uv pip install -r requirements.txt
uv run playwright install chromium   # one-time, ~150MB (facebook-groups adapter)
```

## Run

From `backend/`:

```powershell
uv run python manage.py migrate      # apply migrations (creates db.sqlite3)
uv run python manage.py runserver    # dev server on http://127.0.0.1:8000/
```

Or activate the venv and use `python` directly:

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py migrate
python manage.py runserver
```

## Running

Two processes (AD-2): the dev server and the collector worker run
independently:

```powershell
uv run python manage.py runserver       # dev server on http://127.0.0.1:8000/
uv run python manage.py run_collector   # collector worker (separate process)
```

- Run **exactly one** collector worker — there is no double-run guard or
  locking (personal single-user tool); a second worker would poll Sources
  redundantly.
- Cadence (AD-7): the worker polls every registered Source every
  `COLLECTOR_INTERVAL_MINUTES` (default 30). On startup it catches up after
  downtime — when this is the first pass or the gap since the last
  successful pass is >= 2x the interval — and logs a `backfill` FetchLog
  carrying the count of stale listings (`published_at` older than 24h).
- Ctrl+C stops the worker cleanly (graceful scheduler shutdown, exit 0).

## Conventions (AD-2 / AD-4)

- SQLite runs in WAL mode with `busy_timeout` (30s) — applied on every
  connection via the `connection_created` signal in `listings/apps.py`;
  the Django app is the single writer (all writes via the ORM).
- `Listing.dedup_fingerprint` is unique at the DB level and immutable;
  `seen_sources` is append-only; schema changes exist only as migrations.

## Apps

- `listings/` — models `Source`, `Listing`, `FetchLog` (no `Application` yet; Epic 2).

## Sources

- `ouedkniss-jobs` — ouedkniss GraphQL adapter (Story 1.5).
- `google-jobs` — live via JobSpy (`python-jobspy`, pinned in
  `requirements.txt`; requests-based Google Jobs scraper, no API key).
  JobSpy reverse-engineers Google's endpoints, so Google may block or
  rate-limit — failures surface as `fetch` FetchLogs and stale counts.
- `facebook-groups` — Playwright (headless chromium, sync API) adapter
  for logged-out **public** Facebook groups (Story 1.7; `playwright`
  pinned in `requirements.txt`). The browser binary is a one-time
  download (`uv run playwright install chromium`, ~150MB). Requires
  `config['groups']` (list of public group URLs); private/gated groups
  raise a labelled 'login required' fetch failure. Facebook ships DOM
  changes weekly — the pinned selectors and the test fixture
  (`collector/tests/fixtures/facebook_feed.html`) are the drift
  maintenance points. The test suite is hermetic (fake page objects) and
  never launches the browser.