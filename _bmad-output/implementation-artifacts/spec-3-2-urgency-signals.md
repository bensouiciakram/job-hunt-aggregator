---
title: 'Story 3.2: Urgency signals'
type: 'feature'
created: '2026-08-19'
status: 'done'
review_loop_iteration: 1
context:
  - _bmad-output/implementation-artifacts/epic-3-context.md
  - _bmad-output/implementation-artifacts/spec-3-1-interest-scoring.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The sweep shows everything at equal urgency. Akram needs to know which postings are live opportunities (posted everywhere = recruiter in a hurry) and which are ghosts (reposted after deletion = churn), without relying on platform metadata that sparse sources like Facebook groups lack (FR-7).

**Approach:** Three signals computed from engine-persisted history alone (AD-8): **cross-posted** (dire-need) — a Listing whose `seen_sources` shows the same role on ≥ 2 sources (Story 1.3 dedup merges cross-posts into one row, appending sources); **churn-possible** — a Listing whose normalized title+company+host matches a recent audit entry of a deleted Listing; **growth-possible** — a company that posted a cluster of new roles recently. Deletions are engine history: a new `ListingDeletion` audit model records every Listing deletion via a Django `post_delete` signal (admin, shell, and future flows alike), so the churn signal works for any deletion path.

## Boundaries & Constraints

**Always:**
- **`ListingDeletion` model** (in `listings/models.py`): `fingerprint` (the deleted listing's dedup fingerprint), `title`, `company`, `url`, `deleted_at` (auto_now_add). Append-only audit — nothing ever edits these rows. Migration `0003`. Registered in admin.
- **Deletion hook**: `listings/signals.py` with `post_delete` → `ListingDeletion.objects.create(...)`; wired in `listings/apps.py` `AppConfig.ready()` (guard against double-import in tests). Pinned: deleting a Listing (via ORM) records the audit row; `Listing.objects.all().delete()` deletes records the same way.
- **Signal service** `judge/signals.py`: `compute_signals(listings, now=None) -> {listing_id: signals_dict}` — batch, reads engine history only:
  - `cross_posted`: `len(listing.seen_sources) >= 2` (the same role on ≥ 2 sources = dire-need; AD-8 append-only set).
  - `churn_possible`: a `ListingDeletion` row with the same normalized title, company, and url-host, `deleted_at >= now - 30 days`. Normalization: lowercase, strip, collapse whitespace.
  - `growth_possible`: company (non-empty) with ≥ 3 Listings (including this one) created within the last 7 days.
  - Single efficient pass: one deletions query (30-day window), one company cluster query (7-day window) — no per-item queries.
- **Payload**: each listing item gains `signals: {cross_posted, churn_possible, growth_possible}` (all bools). Additive; envelope and existing keys unchanged.
- **UI**: small zinc chips on rows where a signal is true: `cross-posted`, `churn?`, `growth?` — rendered next to the source chip; absent when false. Chip text is fixed, not dynamic.
- Tests: cross_posted thresholds (0/1/2 sources), churn (match + no-match + stale > 30 days + host differs), growth (2 vs 3 vs 7-day boundary), deletion audit (single delete, bulk delete), payload shape (exact `signals` keys), batch correctness (mixed page), and the smoke seeds one cross-posted + one growth listing and asserts chips render.

**Ask First:** (none)

**Never:**
- No changes to frozen collection code (dedup/source appending already produce the `seen_sources` history this story reads).
- No edits to `ListingDeletion` rows (append-only), no mutation of Listing fields.
- No new endpoints (signals ride the existing listings payload).
- No changes to the envelope or existing payload keys.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| CROSS_0 | seen_sources = [] | cross_posted false | n/a |
| CROSS_1 | seen_sources = ['ouedkniss'] | false | n/a |
| CROSS_2 | seen_sources = ['ouedkniss','google-jobs'] | true | n/a |
| CHURN_MATCH | new listing, deletion audit (same title/company/host, ≤ 30d) | churn_possible true | n/a |
| CHURN_NOMATCH | no audit row | false | n/a |
| CHURN_STALE | audit row > 30 days | false | n/a |
| CHURN_HOST | same title/company, different host | false | n/a |
| CHURN_CASE | audit title case/whitespace differs | true (normalized) | n/a |
| GROWTH_2 | company has 2 listings in 7d | false | n/a |
| GROWTH_3 | company has 3 listings in 7d | true | n/a |
| GROWTH_STALE | 3 listings but oldest > 7d | false | n/a |
| GROWTH_EMPTY | company empty/None | false | n/a |
| DELETE_ONE | delete a Listing via ORM | audit row created | n/a |
| DELETE_BULK | queryset delete | audit row per listing | n/a |
| PAYLOAD | GET /api/listings/ | item has signals with exactly 3 bool keys | n/a |
| UI_CHIP | row with cross_posted true | 'cross-posted' chip visible | n/a |

</frozen-after-approval>

## Code Map

- `backend/listings/models.py` -- `ListingDeletion` (append-only audit).
- `backend/listings/migrations/0003_listingdeletion.py` -- generated.
- `backend/listings/signals.py` -- post_delete hook.
- `backend/listings/apps.py` -- ready() wiring.
- `backend/listings/admin.py` -- audit registered.
- `backend/judge/signals.py` -- `compute_signals` batch service.
- `backend/api/views.py` -- `signals` in `_listing_payload`.
- `backend/api/tests.py` -- signal/deletion/payload tests.
- `frontend/app/components/listings-view.tsx` -- signal chips + type.

## Tasks & Acceptance

**Execution:**
- [ ] ListingDeletion model + migration + admin
- [ ] post_delete hook + AppConfig wiring
- [ ] compute_signals batch service (3 rules, 2 queries)
- [ ] Payload `signals` (exact shape)
- [ ] Signal chips in rows
- [ ] Tests (CROSS_*, CHURN_*, GROWTH_*, DELETE_*, PAYLOAD) + smoke + gates + Change Log

**Acceptance Criteria:**
- Given engine-persisted history (seen_sources sets, fetch history, deletion events), when the urgency service runs, then a role appearing on N Sources yields a cross-posting footprint per recruiter-role (dire-need signal).
- And a Listing whose normalized title+text reappears after deletion is flagged churn-possible.
- And a company posting a cluster of new, related roles yields a growth-possible flag.
- And signals derive from engine history alone, so they work on sparse platforms with limited metadata (FR-7, AD-8).

## Spec Change Log

(Append-only)

- 2026-08-19 Review loopback (edge-case + verification-gap reviewers): the initial test data contradicted its own rules — `test_churn_match_and_miss` deleted `old` on `old.example` then asserted `fresh` on `new.example` churned (CHURN_HOST makes that false), leaving the CHURN_NOMATCH/HOST assertions unexecuted; `test_growth_requires_cluster_of_three_in_seven_days` reused one company for both 2- and 3-listing cases so the cluster leaked; the SignalsTests class insertion absorbed three ScoringTests methods (class split). Fixed: churn test now shares one host across the deleted/fresh pair, growth uses separate companies, the three absorbed tests were moved back under ScoringTests, and `test_item_shape_excludes_raw_snapshot` gained the `signals` key.
- 2026-08-19 Edge-case hardening adopted into `judge/signals.py`: host extraction via `urlsplit` (strips scheme, port, hash fragment; protocol-relative `//host/x` handled), NFKC + casefold normalization (CHURN_CASE also covers Unicode), `list(listings)` materialization (one-shot iterables safe), deletion rows missing title/company/host are skipped, whitespace-only/empty companies never cluster (GROWTH_EMPTY), `seen_sources` non-list guard + set-dedup for duplicates, naive `at` made timezone-aware.
- 2026-08-19 Append-only admin enforcement: `has_add_permission`/`has_delete_permission`/`has_change_permission` False, `has_view_permission` True (list stays readable). `post_delete` receiver now logs-and-swallows so an audit failure never aborts a deletion.
- 2026-08-19 Test suite repair (pre-existing time bomb, surfaced during the 3.2 run): `RAW_ITEMS` fixture carries fixed `2026-08-18` dates, so `test_startup_first_pass_logs_backfill_with_stale_count` started seeing the polled RAW_ITEMS rows as stale once the clock passed them — now isolates itself from the setUp stub sources like its sibling test; expected stale count message still pinned to the isolated rows.
- 2026-08-19 Smoke: 5/5 PASS (cross-posted chip, growth chip, control has none, seed + cleanup; screenshot `story-3-2-smoke/step-1-signals.png`); 262 backend tests OK; frontend build + lint exit 0.

## Suggested Review Order

1. `judge/signals.py` — normalization + batch queries (the rules themselves).
2. `listings/signals.py` + `listings/apps.py` + `listings/models.py` — deletion audit path.
3. `listings/admin.py` — append-only enforcement.
4. `api/views.py` `_listing_payload` — additive payload change.
5. `api/tests.py` `SignalsTests` — matrix coverage incl. the corrected churn/growth fixtures.
6. `frontend/app/components/listings-view.tsx` — chips + data hooks.
7. `_bmad-output/implementation-artifacts/story-3-2-smoke/` — smoke + evidence.

## Design Notes

- **Deletions become first-class history:** the churn signal needs a deletion trail that no flow writes today; the `post_delete` ORM hook records every deletion path (admin, shell, future story flows) with zero call-site changes — engine history, AD-8 spirit.
- **seen_sources is the dire-need detector:** Story 1.3's dedup merges a role posted on N sources into ONE listing whose seen_sources grows — so `>= 2` is exactly "a recruiter posting the same role everywhere", no extra machinery.
- **Batch, not per-item:** one deletions query (30-day window) + one company cluster query (7-day window) serve a whole page; the view is unchanged in shape.
- **Chips are boolean, not styled by intensity:** signals are advisory (FR-7); intensity/ranking stays out of scope for v1 of the signals.