# Story 3.1 — E2E Smoke Evidence (2026-08-19)

## Environment
- Django dev server (:8000) + Next dev (:3000), `cmd /c` log-redirection pattern
- Headless Chromium via the backend venv's Playwright
- Dev DB: 34 seeded Listings + two smoke listings (`https://smoke.example/high` = "Web Scraping API Backend Engineer" → emerald band; `https://smoke.example/low` = "Dev" → red band)

## Assertions (headless Chromium, `run_smoke.py`)

| # | Assertion | Result |
|---|-----------|--------|
| 1 | Every listing row renders a score chip (`span[title='Interest score']`) | **PASS** (25 rows) |
| 2 | Every chip shows an integer 0–100 with a valid tone class (emerald/red/zinc) | **PASS** |
| 3 | Tone variety across rows (emerald, red, zinc all present) | **PASS** |
| 4 | No "undefined" chip text | **PASS** |

Screenshot: `step-1-scores.png` (same directory).

## Gates

| Command | Result |
|---------|--------|
| `uv run python manage.py test` (backend) | **249 OK** (231 + 18 new in 3.1) |
| `uv run python manage.py check` | 0 issues |
| `uv run python manage.py makemigrations --check --dry-run` | No changes detected (read-side story) |
| `npm.cmd run build` (frontend) | exit 0 |
| `npm.cmd run lint` | exit 0 |

## Notes
- First smoke run showed only the zinc tone — the 34-row seed scores uniformly mid-band with the real profile; the smoke was re-run after seeding one emerald and one red listing (step 3 asserts variety, not specific titles).
- Scoring is read-time pure (no migration, no write path); the profile is the hand-maintained `INTEREST_PROFILE` settings constant.
- Cleanup: smoke listings deleted; ports 8000/3000 free at teardown.