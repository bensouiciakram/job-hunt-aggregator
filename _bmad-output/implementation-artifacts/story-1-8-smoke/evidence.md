# Story 1.8 — E2E Smoke Evidence (2026-08-19)

## Environment
- Django dev server: `uv run python manage.py runserver 8000` (started via `cmd /c` + log redirection — `Start-Process -RedirectStandardOutput` blocks forever with a process tree, so `cmd /c` owns the redirection)
- Next dev: `npm.cmd run dev` on :3000
- Headless Chromium via the backend venv's Playwright (installed in Story 1.7)
- Dev DB seeded: 34 Listings (varied titles incl. 'Smoke Zigzag Keyword Listing', 'Python Developer', one NULL published_at) + 7 FetchLogs (one ok=True stage='pass' → sweep stamp)
  - Seed input recorded in `seed-input.py` (same directory)

## Assertions (headless Chromium, `run_smoke.py` + `run_step5.py`)

| # | Assertion | Result |
|---|-----------|--------|
| 1 | Newest listing title renders on `/` (sorted) | **PASS** |
| 1b | 'Last sweep' stamp renders (server-owned, from ok pass FetchLog) | **PASS** |
| 2 | Next button → page 2 renders a different first title | **PASS** (`SMOKE REFRESH PROOF` → `Finance Analyst`) |
| 3 | New listing inserted mid-session + Refresh click → new listing appears (AC3 server-side refresh) | **PASS** |
| 4 | `?keyword=zzzzz` → 'No listings match your search.' empty-state copy | **PASS** |
| 5 | Django killed → reload → 'Could not reach the backend … Is Django running?' error block | **PASS** |

Screenshots: `step-1-load.png`, `step-2-page2.png`, `step-3-refresh.png`, `step-4-search.png`, `step-5-error.png` (same directory).

## Gates

| Command | Result |
|---------|--------|
| `uv run python manage.py test` (backend, `backend\`) | **214 OK** (195 + 17 new in 1.8) |
| `uv run python manage.py check` | 0 issues |
| `uv run python manage.py makemigrations --check --dry-run` | No changes detected |
| `npm.cmd run build` (frontend, `frontend\`) | **exit 0** (Next.js 16.3.1, Turbopack; `/` is ƒ Dynamic) |
| `npm.cmd run lint` | **exit 0** |

## Notes
- First run failed step 2 with `a[href*='page=2']` — pagination uses `<button>` + `router.push`, not anchors; fixed the locator (not the app).
- First run failed step 4 with `keyword=zigzag` — the seed itself contains a 'Smoke Zigzag Keyword Listing', so the match was real; switched the probe keyword to `zzzzz` (no app change).
- Multiple Django instances from earlier cancelled dispatches held :8000 (PIDs 14156, 18060, 2308); all terminated. Ports 8000/3000 free at teardown.
- Cleanup: the script's `SMOKE REFRESH PROOF` rows (url `*.smoke.example`) deleted from the dev DB; the 34-row seed remains (scratch dev data, harmless — includes the ok pass FetchLog the sweep stamp reads).