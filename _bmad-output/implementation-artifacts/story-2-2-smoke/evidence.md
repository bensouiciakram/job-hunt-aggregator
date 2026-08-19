# Story 2.2 — E2E Smoke Evidence (2026-08-19)

## Environment
- Django dev server (`uv run python manage.py runserver 8000`, `cmd /c` log-redirection pattern)
- Next dev (`npm.cmd run dev`, :3000)
- Headless Chromium via the backend venv's Playwright
- Dev DB: 34 seeded Listings (all status `new`) + 7 FetchLogs; one `SMOKE APPLY TARGET` seeded per run (url `https://smoke.example/apply/target`, published_at now)

## Assertions (headless Chromium, `run_smoke.py`)

| # | Assertion | Result |
|---|-----------|--------|
| 1 | `/` defaults to the New (24h) bucket; newest fresh unapplied listing visible | **PASS** |
| 2 | Click **Mark as applied** on the newest row → row disappears from New bucket, no error text | **PASS** |
| 3 | Toggle **All** → applied listing visible with **Applied** badge | **PASS** |
| 4 | Full reload on `?bucket=all` → Applied badge persists (server-side state) | **PASS** |
| 5 | Toggle back to **New (24h)** → applied listing stays hidden | **PASS** |

Screenshots: `step-1-new-bucket.png`, `step-2-applied-new.png`, `step-3-applied-in-all.png`, `step-4-reload-persists.png` (same directory).

## Bug found by the smoke (fixed)

**The New bucket view never applied the server filter.** `fetchListings` set the `bucket` param only when it was `all`; the API treats an *absent* `bucket` as the full list (Story 2.1 spec: "absent or `all` → current behavior"). So `/` rendered all listings including applied ones until a manual reload. Fixed in `frontend/app/page.tsx` — the fetch now always sends `params.set("bucket", bucket)`. The bucket param was consistently threaded through SearchBox, PaginationControls, and BucketToggle URLs (absent `bucket` = New, the default).

## Gates

| Command | Result |
|---------|--------|
| `uv run python manage.py test` (backend) | **231 OK** (no backend change in 2.2 — all from 2.1) |
| `uv run python manage.py check` | 0 issues |
| `npm.cmd run build` (frontend) | **exit 0** (Next.js 16.3.1; `/` is ƒ Dynamic) |
| `npm.cmd run lint` | **exit 0** (0 warnings) |

## Notes
- Apply is a cross-origin POST from :3000 to :8000 with `Content-Type: application/json` → browser preflight; covered by Story 2.1's `ApplyCorsTests`.
- Idempotent double-click: the button disables while pending; a second click is ignored client-side, and the backend `get_or_create` returns the existing Application (Story 2.1 tests). No duplicate-record path exists.
- A stale-state trap surfaced while debugging: a client `useState(items)` list survives `router.push` navigations (same component type in the tree), so toggling bucket showed stale rows until reload. Fixed by keying `ListingsView` on `${bucket}-${keyword}-${page}` — same remount pattern already used for `SearchBox`.
- Cleanup: `SMOKE APPLY TARGET` rows + all Applications deleted; seeded listings reset to `status='new'`. Ports 8000/3000 free at teardown.