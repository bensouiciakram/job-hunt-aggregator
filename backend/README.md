# Job Hunt Aggregator — Backend

Django 6.1 project under `backend/`, Python 3.13, SQLite (WAL + busy_timeout).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (manages Python 3.13 + the venv).

## Setup

```powershell
uv python install 3.13        # one-time, user-local
uv venv --python 3.13         # creates .venv
uv pip install "Django>=6.1,<7"
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

## Conventions (AD-2 / AD-4)

- SQLite runs in WAL mode with `busy_timeout` (30s) — applied on every
  connection via the `connection_created` signal in `listings/apps.py`;
  the Django app is the single writer (all writes via the ORM).
- `Listing.dedup_fingerprint` is unique at the DB level and immutable;
  `seen_sources` is append-only; schema changes exist only as migrations.

## Apps

- `listings/` — models `Source`, `Listing`, `FetchLog` (no `Application` yet; Epic 2).