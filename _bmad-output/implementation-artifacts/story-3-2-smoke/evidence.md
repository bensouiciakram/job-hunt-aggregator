# Story 3.2 — Urgency Signals: Smoke Evidence

- Date: 2026-08-19
- Status: 5/5 PASS
- Scope: urgency signal chips (`cross-posted`, `churn?`, `growth?`) render for the right listings and never for the control.

## Steps

| Step | Check | Result |
|------|-------|--------|
| seed_listings | Seeded via backend venv `manage.py shell`: 1 cross-posted row (`seen_sources` = ouedkniss + google-jobs), 3 GrowthCo rows (3 listings in the last 7 days, incl. target), 1 control row (single source, unique company, no deletions) | PASS |
| cross_posted_chip | `Cross Posted Job` row renders `cross-posted` chip; nothing else | PASS |
| growth_chip | `Growth Role 3` row renders `growth?` chip; nothing else | PASS |
| control_no_signals | `Control Job` row renders zero signal chips | PASS |
| cleanup_smoke_rows | Smoke rows deleted from dev DB (listings back to 34, applications 0) | PASS |

## Screenshots

- `step-1-signals.png` — full New-bucket list with signal chips visible.

## Gates (same run)

- Backend: `manage.py test` → 262 tests, OK (incl. 13 SignalsTests; fixes for the churn-host mismatch, growth-cluster contamination, ScoringTests class absorption, `signals` key in item-shape pin, and the RAW_ITEMS stale-date time bomb).
- Frontend: `npm run build` exit 0, `npm run lint` exit 0.
- Dev DB restored: 34 listings, 0 applications, 1 source.