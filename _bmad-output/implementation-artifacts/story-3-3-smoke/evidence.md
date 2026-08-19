# Story 3.3 — Outcome Feedback & Pacing: Smoke Evidence

- Date: 2026-08-19
- Status: 4/4 PASS
- Scope: outcome picker updates the Applied badge; the pacing rest line appears in the header at the threshold.

## Steps

| Step | Check | Result |
|------|-------|--------|
| seed_listings | Seeded 11 listings via backend venv `manage.py shell`, each applied (status `applied`, Application row created) | PASS |
| pacing_rest_line | Page header shows the amber rest line ("10 great matches applied this week — rest") — 11 applications in the last 7 days ≥ 10 | PASS |
| target_row_found | `Smoke Pace Job 0` row present with the outcome picker | PASS |
| outcome_badge_updates | Clicking **response** updates the badge to `Applied · response` (POST /api/listings/<pk>/outcome/ → 200) | PASS |
| cleanup_smoke_rows | Smoke rows deleted from dev DB (listings back to 34, applications 0) | PASS |

## Screenshots

- `step-1-outcome-and-pacing.png` — header rest line + outcome badge.

## Gates (same run)

- Backend: `manage.py test` → 278 tests, OK (incl. new OutcomeApiTests + PacingTests + the worker poll-order test).
- Frontend: `npm run build` exit 0, `npm run lint` exit 0.
- Dev DB restored: 34 listings, 0 applications, 1 source.