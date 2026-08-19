---
title: 'Story 1.8: Listings UI (Next.js + API)'
type: 'feature'
created: '2026-08-19'
status: 'done'
review_loop_iteration: 0
context:
  - _bmad-output/implementation-artifacts/epic-1-context.md
  - _bmad-output/implementation-artifacts/spec-1-3-collection-pipeline.md
  - _bmad-output/implementation-artifacts/spec-1-7-facebook-groups-adapter.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Three adapters now fill the store, but the user has no way to SEE what was collected — the product is a headless database.

**Approach:** Ship the first user-visible surface: a Next.js 16 (App Router, React 19) frontend in `frontend/` that renders stored Listings sorted by `published_at DESC, id DESC` (AD-9), paged 25 per page, with a server-provided `last_sweep_at` stamp and a refresh action. The backend gains the missing listings endpoint (`GET /api/listings/`, AD-10 envelope) and CORS for the local dev origin (the item deferred since Story 1.1). Two local processes (AD-2): Django on :8000, Next dev on :3000.

## Boundaries & Constraints

**Always:**
- **Backend — `GET /api/listings/`** in `backend/api/`:
  - Query params: `page` (1-based, default 1), `keyword` (optional; case-insensitive match on title OR company — `icontains`), `per_page` fixed at 25 (AD-9 page size; not client-settable).
  - Sort: `published_at DESC, id DESC` (AD-9; NULLS — SQLite sorts NULLs last in DESC by default, acceptable and pinned by test).
  - Envelope (AD-10): `{ok: true, data: {items: [...], page, has_next, total, last_sweep_at}, error: null}`. Item shape: `id, title, company, url, published_at, source: {name, adapter_key}, status, keywords` (no raw_snapshot in the list — payload discipline).
  - `last_sweep_at`: created_at of the latest ok=True `pass` FetchLog (worker convention, Story 1.4), else null — the server-side freshness stamp (AD-9).
  - `page` out of range → empty items, `has_next: false` (not an error). Invalid `page` (non-int, <1) → 422-style error in the envelope (`ok: false, error: 'invalid page'`).
  - csrf_exempt + AD-10 envelope conventions from Stories 1.2.
- **CORS:** add `django-cors-headers` (pinned in requirements.txt) allowing `http://localhost:3000` and `http://127.0.0.1:3000` only (no wildcard); `CORS_ALLOW_CREDENTIALS` off (no auth). This resolves the deferred CORS entry.
- **Frontend — `frontend/` Next.js 16 (App Router) + React 19:**
  - `npm create next-app` (or manual scaffold with pinned versions; Next 16, React 19, TypeScript). Node 24 is installed; npm must be invoked as `npm.cmd` (PowerShell blocks the .ps1 shim).
  - Home page `/`: fetches `GET http://127.0.0.1:8000/api/listings/` server-side (App Router Server Component fetch — clean, no client-state for the initial load); renders a list sorted by date with title, company, source badge, relative/absolute published_at, and a permalink out to the original posting (`<a href={url} target="_blank">`).
  - Pagination: prev/next controls (client component), fetching page N.
  - `last_sweep_at` rendered as "Last sweep: <relative>" with a refresh button (client component re-fetching the current page).
  - Keyword search box (optional filter, client-side fetch of `&keyword=`).
  - Base URL: `NEXT_PUBLIC_API_URL` env, default `http://127.0.0.1:8000`.
  - Dark-or-light neutral minimal styling (Tailwind v4 is the Next 16 default — use it; no extra design system).
  - `frontend/.env.local` NOT committed (gitignore); `.env.example` committed.
- **Tests — backend:** endpoint tests (sort order incl. NULL published_at, paging, keyword filter, last_sweep_at from the latest ok pass row, invalid page, envelope shape). Frontend verification: `npm run build` must pass; a `README.md` in `frontend/` documents `npm install && npm run dev`.

**Ask First:** (none)

**Never:**
- No auth/login, no SSR of raw_snapshot, no changes to frozen backend collection code (collect/pipeline/repository/adapters).
- No scraping/collection work in this story — read-only surface.
- No new database columns or migrations.
- No writing to the store from the frontend (that is Story 2.x territory).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| LIST_DEFAULT | stored Listings, no params | page 1, 25 items, sorted published_at DESC then id DESC, envelope ok | n/a |
| PAGE_2 | page=2 | items 26-50, has_next true/false correctly | n/a |
| PAGE_OOR | page=999 | items [], has_next false, ok true | not an error |
| PAGE_BAD | page=abc / page=0 | ok false, error 'invalid page' | envelope error |
| KEYWORD | keyword=python | only title/company icontains matches | n/a |
| NULL_DATE | listings with published_at NULL | sorted last (SQLite DESC NULLS-last), pinned | n/a |
| SWEEP_STAMP | latest ok pass FetchLog | last_sweep_at = its created_at; none → null | n/a |
| CORS | Origin http://localhost:3000 | Access-Control-Allow-Origin echoes it; disallowed origin gets none | n/a |
| UI_LOAD | server running, data present | list renders, sorted, source badges, links, sweep stamp | fetch failure → friendly error block |
| UI_PAGE | next/prev clicked | page 2 renders via API | ditto |

</frozen-after-approval>

## Code Map

- `backend/api/views.py` (+ `urls.py`) -- sources + test-fetch views (frozen); listings view added here.
- `backend/job_hunt_aggregator/settings.py` -- `INSTALLED_APPS` + `CORS_ALLOWED_ORIGINS` + `MIDDLEWARE` (django-cors-headers).
- `backend/requirements.txt` -- `django-cors-headers` pinned.
- `backend/api/tests.py` -- endpoint tests added.
- `frontend/` -- new Next.js 16 app (App Router): `app/page.tsx` (server component, initial fetch), `app/components/` (client pagination/refresh/search), `app/layout.tsx`, `app/globals.css` (Tailwind v4), `next.config.ts`, `package.json` (pinned), `.env.example`, `.gitignore` (incl. `.env.local`), `README.md`.

## Tasks & Acceptance

**Execution:**
- [ ] Backend: `GET /api/listings/` view + URL + tests (LIST_DEFAULT, PAGE_2, PAGE_OOR, PAGE_BAD, KEYWORD, NULL_DATE, SWEEP_STAMP, CORS) -- AD-9 sort/paging/last_sweep_at + AD-10 envelope
- [ ] Backend: `django-cors-headers` pinned + settings (allowed origins localhost:3000/127.0.0.1:3000 only) -- deferred CORS entry resolved
- [ ] Frontend: Next.js 16 scaffold in `frontend/` (TypeScript, Tailwind v4); home page server-fetching the API; pagination + refresh + keyword client components; `NEXT_PUBLIC_API_URL` default; `.env.example`; `.gitignore` with `.env.local`; `README.md` -- the user-visible surface
- [ ] Frontend: `npm.cmd install` + `npm.cmd run build` must pass -- build gate
- [ ] Smoke: with Django running on :8000 (dev DB seeded via a collect_source shell call with the google stub or fixtures) and `npm run dev` on :3000, a browser check of the page rendering the list (manual, via the available browser tooling) -- end-to-end proof

**Acceptance Criteria:**
- Given stored Listings, when the user opens the web app, then the newest postings are shown in a list sorted by date.
- And the user can open individual listings (permalink to the original posting).
- And the list refreshes server-side (`last_sweep_at` stamp shown; refresh re-fetches the current page).

## Spec Change Log

(Append-only; empty until first review loopback.)

## Suggested Review Order

**API surface** — listings view: sort/paging/last_sweep_at, envelope discipline, page clamp
- [`views.py:140`](../../backend/api/views.py#L140)

**CORS** — django-cors-headers, localhost-only origins
- [`settings.py:1`](../../backend/job_hunt_aggregator/settings.py#L1)

**Frontend** — server component fetch (no-store), client islands, href guards, empty-state branches
- [`page.tsx:1`](../../frontend/app/page.tsx#L1)
- [`pagination.tsx:1`](../../frontend/app/components/pagination.tsx#L1)

**E2E evidence** — headless-Chromium smoke, screenshots, gates
- [`story-1-8-smoke/evidence.md:1`](../story-1-8-smoke/evidence.md#L1)

## Design Notes

- **Server-component first load:** the initial page render fetches the API server-side — the user sees data immediately, no client spinner on first paint; pagination/search/refresh are the only client islands (standard Next 16 pattern).
- **last_sweep_at is server-owned:** the stamp comes from the worker's ok pass rows (Story 1.4 bookkeeping), not from the client clock — the UI cannot lie about freshness.
- **No raw_snapshot in the list:** payload discipline; the snapshot stays in the store (a future detail view is Story 2.x / deferred).
- **CORS is the last deferred item from Story 1.1's plan** — closing it here makes the two-process envelope fully operable.
- **NULL published_at sorts last** under SQLite DESC — acceptable, pinned by test so the semantics are explicit.

## Verification

**Commands (backend, in `backend\`):**
- `uv run python manage.py check` -- 0 issues
- `uv run python manage.py test` -- all pass (195 + new)
- `uv run python manage.py makemigrations --check --dry-run` -- "No changes detected"

**Commands (frontend, in `frontend\`):**
- `npm.cmd install` -- clean install
- `npm.cmd run build` -- exits 0
- `npm.cmd run dev` + browser smoke on http://localhost:3000 with Django on :8000 -- list renders sorted, pagination works, sweep stamp visible

**Manual checks (if no CLI):**
- `backend/.gitignore` still excludes `.env.local` if the frontend adds one; `frontend/.env.local` (if created for smoke) is not committed.
- CORS headers verified via the API tests, not just browser inspection.