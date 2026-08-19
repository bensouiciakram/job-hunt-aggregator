---
title: 'Story 3.3: Outcome feedback and pacing'
type: 'feature'
created: '2026-08-19'
status: 'done'
review_loop_iteration: 1
context:
  - _bmad-output/implementation-artifacts/epic-3-context.md
  - _bmad-output/implementation-artifacts/spec-3-2-urgency-signals.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Applications today end in a dead end — a badge, then nothing. Akram never records what happened, so the engine cannot learn which sources actually respond, and nothing tells him when to stop. (FR-8.)

**Approach:** Outcomes (response/interview/silence) are entered manually against existing Applications; the apply flow stays untouched (AD-5). The engine turns outcome history into pacing: a per-source response-rate weight that reorders collection toward responding sources, and a stop signal when 10 great matches were applied in the last 7 days ("rest"). No new sources of truth: pacing is derived from Applications, Listings, and Sources the engine already persists (AD-8).

## Boundaries & Constraints

**Always:**
- **Outcome service** `set_outcome(listing, outcome)` in `listings/services.py` (AD-4): outcome ∈ {`response`, `interview`, `silence`} or `''`/`None` to clear; raises/returns error when the listing has no Application; never creates or deletes Application rows (AD-5).
- **Outcome endpoint** `POST /api/listings/<pk>/outcome/` with JSON body `{"outcome": ...}`: 404 unknown listing, 400 not-applied, 422 invalid value, 200 with `{application, status}` (mirrors the apply endpoint's shape). csrf_exempt like its sibling. Outcome never changes `listing.status`.
- **Pacing service** `judge/pacing.py` (read-only, AD-4):
  - `source_weights(at=None) -> {source_id: weight}`: outcomes within the last 30 days grouped by `application.listing.source_id`; weight = `0.5 + (responses + 1) / (total + 2)` (Laplace-smoothed response rate: response/interview count, silence counts as total only); sources with no recent outcomes get no key (= 1.0 neutral).
  - `compute_pacing(at=None) -> {applied_7d, rest, source_weights}`: `applied_7d` = Applications created within the last 7 days; `rest` = `applied_7d >= 10`.
- **Payload**: listings GET `data` gains `pacing: {applied_7d, rest, source_weights}`. Additive; envelope and existing keys unchanged.
- **Collector consultation**: `collector/worker.py` `poll_all` consults `judge.pacing.source_weights` once per cycle and collects Sources in weight-descending order (responders first). Frozen pipeline files (collect.py, pipeline/*) are NOT touched.
- **UI**: applied rows render a small outcome picker (response / interview / silence, plus clear) under the Applied badge; choosing one updates the badge text to `Applied · <outcome>`. When `rest` is true, a quiet line in the page header reads "10 great matches applied this week — rest".
- Tests: outcome endpoint matrix (404/400/422/200/clear/idempotent/never-creates), pacing math (weights incl. smoothing + no-key neutral, 7-day count + boundary, rest at 9 vs 10), payload shape, worker poll order under weights, and the smoke (apply → pick outcome → badge updates; 10 seeded applications → header rest line) + gates + Change Log.

**Ask First:** (none)

**Never:**
- No new Application rows from outcome entry (AD-5), no outcome deletion flows.
- No changes to the frozen collection pipeline files (collect.py / pipeline/*).
- No changes to the envelope or existing payload keys.
- No status mutation by the outcome endpoint.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| OUT_RESPONSE | applied listing, outcome=response | Application.outcome='response', 200 | n/a |
| OUT_INTERVIEW | applied listing, outcome=interview | outcome='interview' | n/a |
| OUT_SILENCE | applied listing, outcome=silence | outcome='silence' | n/a |
| OUT_CLEAR | applied listing, outcome='' | outcome=None | n/a |
| OUT_NOT_APPLIED | listing without Application | no row created (AD-5) | 400 'not applied yet' |
| OUT_UNKNOWN | pk with no listing | n/a | 404 |
| OUT_INVALID | outcome='maybe' | no change | 422 |
| OUT_REPEAT | same outcome twice | same value, idempotent | n/a |
| PACE_COUNT_0 | no applications in 7d | applied_7d=0, rest=false | n/a |
| PACE_REST_9 | 9 applications in 7d | rest=false | n/a |
| PACE_REST_10 | 10 applications in 7d | rest=true | n/a |
| PACE_WINDOW | application at 7d + 1h | excluded from applied_7d | n/a |
| WEIGHT_RESPONDER | source: 1 response, 1 silence | weight = 0.5 + 2/4 = 1.0 | n/a |
| WEIGHT_SILENT | source: 0 responses, 1 silence | weight = 0.5 + 1/3 ≈ 0.83 | n/a |
| WEIGHT_NEUTRAL | source with no outcomes | no key (1.0) | n/a |
| WEIGHT_NULL_SOURCE | application with source=None | skipped | n/a |
| POLL_ORDER | two sources, different weights | collected weight-desc first | n/a |
| PAYLOAD_PACE | GET /api/listings/ | data has pacing with exactly 3 keys | n/a |

</frozen-after-approval>

## Code Map

- `backend/listings/services.py` -- `set_outcome` service (AD-4/AD-5).
- `backend/listings/models.py` -- `Application.outcome` TextChoices (Python-level only, no migration).
- `backend/api/views.py` -- outcome endpoint + `pacing` in listings payload.
- `backend/judge/pacing.py` -- `source_weights` + `compute_pacing`.
- `backend/collector/worker.py` -- `poll_all` consults weights for order.
- `backend/api/tests.py` -- outcome/pacing/payload tests; `backend/collector/tests.py` -- poll-order test.
- `frontend/app/components/apply-button.tsx` -- outcome picker on applied state.
- `frontend/app/components/listings-view.tsx` -- `outcome` on items (from apply response) + badge text.
- `frontend/app/page.tsx` -- header rest line from `data.pacing`.

## Tasks & Acceptance

**Execution:**
- [ ] Application.outcome choices + set_outcome service
- [ ] POST /api/listings/<pk>/outcome/ (404/400/422/200, never creates)
- [ ] judge/pacing.py (weights + applied_7d + rest)
- [ ] pacing in listings payload (exact shape)
- [ ] poll_all weight-desc order
- [ ] UI: outcome picker + badge text + header rest line
- [ ] Tests (OUT_*, PACE_*, WEIGHT_*, POLL_ORDER, PAYLOAD_PACE) + smoke + gates + Change Log

**Acceptance Criteria:**
- Given an applied listing, when Akram records response/interview/silence, then the outcome is stored on the existing Application without creating duplicates (AD-5), and the badge reflects it.
- And collection order shifts toward sources whose recent outcomes were responses (per-source response rate).
- And a stop signal surfaces when 10 applications were made in the last 7 days, advising rest (FR-8).

## Spec Change Log

(Append-only)

- 2026-08-19 Implementation fixes found by the test run, not by review: `Application.Outcome` cannot be referenced as `Application.Outcome` inside the class body (NameError) — fields use `Outcome.choices` directly; `set_outcome` rejected `''` (clear) because the guard tested `is not None` — now `outcome not in (None, '')`; the new test helpers collided on `dedup_fingerprint` because `compute_fingerprint` hashes the url HOST only (path variants hash identically) — helpers vary the title per listing; the 404 test deleted the listing before reading its pk (`delete()` nulls `pk`); the poll-order test's sources needed a valid `keywords` config or `collect_source` bails before `fetch`.
- 2026-08-19 Smoke: 4/4 PASS (11 seeded applications → rest line in header; outcome picker click → badge "Applied · response"; cleanup); 278 backend tests OK; frontend build + lint exit 0.

## Suggested Review Order

1. `judge/pacing.py` — weight math + rest threshold.
2. `listings/services.py` `set_outcome` — AD-5 no-create contract.
3. `api/views.py` outcome view + `pacing` payload key.
4. `collector/worker.py` `poll_all` — weight-descending order (the only collector touch).
5. `api/tests.py` OutcomeApiTests + PacingTests.
6. `collector/tests.py` poll-order test.
7. `frontend/app/components/apply-button.tsx` + `frontend/app/page.tsx` — picker + rest line.
8. `_bmad-output/implementation-artifacts/story-3-3-smoke/` — smoke + evidence.

## Design Notes

- **Outcome entry rides the existing Application** (2.1's nullable `outcome` was created for exactly this epic): no schema, no new rows — AD-5's idempotence backstop stays untouched.
- **Weight math is deliberately tame:** Laplace smoothing keeps a single silent outcome from zeroing a source (0.83, not 0), and the base 0.5 floor means weights live in a narrow band — collection order nudges, never starves (a source with no outcomes stays neutral 1.0).
- **`rest` is count-only on purpose:** the PRD copy ("10 great matches applied this week — rest") is a quiet advisory line, not a gate; intensity scoring stays in Story 3.1's domain.
- **Worker touches only worker.py:** `poll_all` consults the pacing service for order; the frozen collect/pipeline files are untouched, honoring Epic 3's constraint.