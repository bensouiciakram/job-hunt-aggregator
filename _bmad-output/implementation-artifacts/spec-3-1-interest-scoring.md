---
title: 'Story 3.1: Interest scoring'
type: 'feature'
created: '2026-08-19'
status: 'draft'
review_loop_iteration: 0
context:
  - _bmad-output/implementation-artifacts/epic-3-context.md
  - _bmad-output/implementation-artifacts/spec-1-8-listings-ui.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The sweep lists everything; Akram must mentally rank each row. He wants the engine to judge worth-my-time so he can skip the noise and apply where it counts (FR-6).

**Approach:** A pure scoring function in a new `backend/judge/` app: `score(listing, profile) -> 0..100`. The profile is a hand-maintained Django settings constant (`INTEREST_PROFILE`) with `tech_stack`, `domains`, `project_types` term lists. Scoring weights problem-domain overlap and post sanity OVER tech-stack overlap (PRD §4.4 brainstorm decision); absurd requirement stacks are penalized by a rule-based sanity heuristic. The score is computed at read time and appears as `interest_score` in the listings API payload and as a color-coded chip in the UI rows. Scoring is pure: it never mutates `status`, `seen_sources`, `dedup_fingerprint`, or anything else (AD-4).

## Boundaries & Constraints

**Always:**
- **New app `backend/judge/`**: `scoring.py` with `score(listing, profile) -> int` (0..100, clamped) and `score_text(title, keywords, profile) -> int` (pure; no DB access). No models, no migrations.
- **Profile shape** (Django settings, hand-maintained): `INTEREST_PROFILE = {'tech_stack': [...], 'domains': [...], 'project_types': [...]}` — term lists, lowercase matching, substring-free word-ish matching (term is matched as a word in text, case-insensitive; the term itself may contain spaces).
- **Weighting** (PRD §4.4: domain + sanity > stack):
  - Base 50.
  - +8 per distinct domain/project-type term matched in title OR keywords (the domain signal).
  - +4 per distinct tech-stack term matched in title (stack signal; HALF the domain weight).
  - Sanity: count distinct stack terms matched in the TITLE alone; ≥ 4 distinct stack terms in one title → −40 (absurd requirement stack). Also −15 if the title is empty or uninformative (title < 4 chars after strip — posts with no real title).
  - Clamp to [0, 100]. Integers only.
- **Never mutates anything** (AD-4): score() takes (listing, profile) and reads title/company/keywords only — pinned by test (status, seen_sources, fingerprint, raw_snapshot untouched after scoring).
- **Payload**: `_listing_payload` gains `interest_score` (computed per item with the settings profile); raw_snapshot stays excluded. No schema change, no migration.
- **UI**: each row shows a small color-coded score chip: green (≥70), zinc (40–69), red (<40), computed server-side (comes with the payload, not client math).
- **Keywords note**: keywords are the user's search terms — identical across listings — so they contribute to the domain signal only when the term is genuinely in the profile (a profile term that also appears in keywords counts once; duplicates are collapsed).
- Tests: weighting order (domain-only outscores stack-only), absurd-stack penalty, empty-title penalty, clamp boundaries (0 and 100), purity (no mutation), payload includes `interest_score`, chip rendering in the E2E smoke.

**Ask First:** (none)

**Never:**
- No DB writes, no models, no migration, no changes to frozen collection code (collect/pipeline/repository/adapters/worker) — this story is strictly read-side.
- No client-side scoring (the server owns the profile and the score).
- No changes to the envelope shape (interest_score is an additive key; existing keys unchanged).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| SCORE_DOMAIN | title/keywords hit 2 domains, no stack | base 50 + 2×8 = 66 | n/a |
| SCORE_STACK | title hits 3 stack terms, no domain | 50 + 3×4 = 62 (stack < domain weight) | n/a |
| SCORE_SANITY | title hits 5 stack terms | 50 + 5×4 − 40 = 30 | n/a |
| SCORE_EMPTY_TITLE | title '' or '<4 chars' | 50 − 15 = 35 | n/a |
| SCORE_ABSENT | no profile terms matched | 50 (neutral) | n/a |
| SCORE_CLAMP | very high sum | 100 | clamp |
| SCORE_CLAMP_LOW | very low sum | 0 | clamp |
| SCORE_PURITY | score(listing) called | listing fields byte-identical afterwards | n/a |
| SCORE_KEYWORD_DUP | profile term present in both title and keywords | counted once | n/a |
| PAYLOAD_SCORE | GET /api/listings/ | every item has integer interest_score 0..100 | n/a |
| UI_CHIP | row renders | chip with score + color class | n/a |

</frozen-after-approval>

## Code Map

- `backend/judge/__init__.py`, `backend/judge/scoring.py` -- the pure scorer.
- `backend/job_hunt_aggregator/settings.py` -- `INTEREST_PROFILE` (hand-maintained, seed with Akram's stack from the PRD: python, django, react, nextjs, typescript, postgresql, sqlite, playwright, scraping, automation, web scraping, data engineering, api, backend, fullstack, freelancing, remote, algeria, alger, ouedkniss ...).
- `backend/api/views.py` -- `interest_score` in `_listing_payload`.
- `backend/api/tests.py` -- scoring + payload tests.
- `frontend/app/components/listings-view.tsx` -- score chip in each row.
- `frontend/app/types.ts` (if created) or inline type -- `interest_score: number` on ListingItem.

## Tasks & Acceptance

**Execution:**
- [ ] `backend/judge/` app with pure `score()`/`score_text()` (weights per spec, clamp, duplicate collapse)
- [ ] `INTEREST_PROFILE` settings seed
- [ ] Payload `interest_score`
- [ ] Score chip in the UI rows (green/zinc/red)
- [ ] Tests: SCORE_* matrix rows + purity + payload
- [ ] E2E smoke check for the chip; build/lint gates; Spec Change Log

**Acceptance Criteria:**
- Given persisted Listings with keywords and text, when the scoring service runs against a hand-maintained profile of Akram's stack and project types, then every Listing receives an Interest Score from 0–100 (FR-6, AD-4 data only).
- And the score weights problem-domain overlap and post sanity over tech-stack overlap (brainstorm decision, PRD §4.4).
- And posts with absurd requirement stacks (e.g., nodejs + python + go + java for one backend role) score low via rule-based sanity heuristics.
- And the score appears in the listings API payload and the UI detail view.
- And scoring never mutates `status`, `seen_sources`, or the dedup fingerprint (AD-4).

## Spec Change Log

(Append-only; empty until first review loopback.)

### Review loopback 1 (2026-08-19) — implemented + patched, APPROVE

Findings applied:
- **Substring false positives** (edge + blind): 'api' matched inside 'scraping'; the matcher is now token-exact with adjacency required for multi-word terms ('web scraping' does not match 'Web content scraping'), while 'Next.js' still matches via de-punctuated sequence matching.
- **Spelling-variant double count** (edge): 'full-stack' + 'fullstack' in one title counted twice — signatures are canonical (sorted tokens joined), so variants collapse to one match ('web scraping'/'webscraping' likewise).
- **Crash paths** (edge): non-list `keywords` (corrupt row would 500 the whole listings endpoint), non-list/missing profile sections, non-string terms, `profile=None` — all guarded; pinned by `test_bad_keywords_and_profile_shapes_do_not_crash`.
- **Punctuation-only title** (edge): '....' bypassed the empty-title penalty — `len(title) < 4 or not _tokens(title)`; pinned.
- **Term in both lists** (edge): a term configured as both stack and domain now counts once (domain weight wins).
- **Real profile never verified** (verification-gap): all matrix tests used a synthetic profile, so a settings typo silently degraded real scoring with a green suite. Added `test_real_profile_pins_concrete_scores` (26 for a 4-stack title — the absurd branch — and 66 for a 2-domain title computed from `settings.INTEREST_PROFILE`) and `test_real_profile_is_structurally_sound` (three keys, non-empty, strings, no duplicates — fixed the duplicate 'data engineering' in settings).
- **Chip verified by nothing** (verification-gap): the story promised an E2E smoke; added `story-3-1-smoke/` (4/4 PASS — chips render on every row, values 0–100 with valid tones, emerald/red/zinc variety, no undefined text) with evidence.md.
- **Chip 'undefined' guard** (edge): `ScoreChip` returns null for non-number scores.

Not adopted (spec intent): none.

## Design Notes

- **Read-time scoring, not denormalized:** the profile is hand-edited config; computing at read time means edits re-score the whole list instantly and nothing needs migration/backfill. The list is ≤ 25 items per page — trivially cheap.
- **Title is the sanity surface:** keywords are the user's own search terms (constant across listings), so "absurd requirement stack" can only be detected in the title text (where the posting states its requirements).
- **Keywords only feed the domain signal** when the profile term actually appears — search terms that aren't in the profile change nothing; duplicates are collapsed to distinct terms.
- **Integer score, clamp, no surprises:** the UI chip reads `interest_score` directly; color thresholds (70/40) are display-only and live in the client.

## Verification

**Commands (in `backend\`):**
- `uv run python manage.py check` -- 0 issues
- `uv run python manage.py test` -- all pass (231 + new)
- `uv run python manage.py makemigrations --check --dry-run` -- "No changes detected" (read-side only)

**Commands (in `frontend\`):**
- `npm.cmd run build` -- exit 0
- `npm.cmd run lint` -- exit 0