---
title: 'Story 2.1: Application model and apply endpoint'
type: 'feature'
created: '2026-08-19'
status: 'draft'
review_loop_iteration: 0
context:
  - _bmad-output/implementation-artifacts/epic-2-context.md
  - _bmad-output/implementation-artifacts/spec-1-8-listings-ui.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The system is read-only — a user who applies to a job has nowhere to record it, and the sweep cannot distinguish "not seen yet" from "applied".

**Approach:** Add the `Application` model (the AD-5 unique constraint) with its migration, the apply service (`listings/services.py` — the AD-4 "status changes only through explicit services" home), and the idempotent `POST /api/listings/<id>/apply/` endpoint. Also add the `bucket=new` filter to the listings endpoint: the "new since last visit" bucket for Epic 2's UI, defined as `published_at >= now - 24h` AND `status != 'applied'` (the AD-7 freshness window — no auth/visit-tracking exists by design, NFR-1).

## Boundaries & Constraints

**Always:**
- **Model** (in `backend/listings/models.py`): `Application` — `listing = OneToOneField(Listing, on_delete=CASCADE, unique=True)` (AD-5), `created_at = DateTimeField(auto_now_add=True)`, `outcome = CharField(max_length=20, null=True, blank=True)` (nullable, FR-8 reserved; NO choices yet — Epic 3 owns them). Migration created.
- **Service** (`backend/listings/services.py`): `apply_to_listing(listing) -> (Application, created)` — single `transaction.atomic`; `Application.objects.get_or_create(listing=listing)`; on created, `listing.status = 'applied'` + `save(update_fields=['status'])`; never downgrades status (re-apply leaves it 'applied' whatever it is now); returns the pair.
- **Endpoint** `POST /api/listings/<id>/apply/` (in `backend/api/`): unknown listing → envelope 404 `{ok: false, error: 'listing not found'}`; success (create OR re-apply) → 200 `{ok: true, data: {application: {id, listing, created_at, outcome}, status: 'applied'}, error: null}` (AD-10); csrf_exempt convention.
- **Bucket filter** on `GET /api/listings/`: `bucket` query param — `new` → `published_at >= now - 24h` AND `status != 'applied'` (same sort/page/envelope; `last_sweep_at` unchanged); absent or `all` → current behavior. Unknown bucket value → 422 envelope `{ok: false, error: 'invalid bucket'}`.
- `status` values: the Listing model's existing choices; 'applied' must be one of them (verify; add to choices if the v1 seed lacks it — that's a model change with the same migration).
- Tests: create→flip, re-apply idempotent (same record, 200, no dup, status not downgraded), 404, envelope shapes (apply + bucket), bucket=new excludes applied + old listings, bucket=all unaffected, invalid bucket 422, DB-level unique constraint (integrity error on raw duplicate insert).
- E2E seam: the frontend POST (Story 2.2) will be cross-origin from :3000 — CORS already allows it (Story 1.8).

**Ask First:** (none)

**Never:**
- No changes to frozen collection code (collect/pipeline/repository/adapters/worker).
- No auth, no per-user state, no Application endpoints other than the apply POST (outcome updates are Epic 3).
- No changes to the listings list payload shape beyond the `bucket` param (no raw_snapshot in items — unchanged).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| APPLY_CREATE | existing Listing, no Application | Application created, status 'applied', 200 envelope | n/a |
| APPLY_REAPPLY | same Listing applied already | same Application returned, no duplicate, status stays 'applied', 200 | idempotent (AD-5/AD-10) |
| APPLY_UNKNOWN | nonexistent listing id | 404 envelope ok:false | not an error page |
| APPLY_OUTCOME | created record | outcome is null | n/a |
| BUCKET_NEW | listings: fresh+unapplied, fresh+applied, old+unapplied | bucket=new → only fresh+unapplied | n/a |
| BUCKET_ALL | same state | all three (applied included) | n/a |
| BUCKET_BAD | bucket=weird | 422 envelope ok:false 'invalid bucket' | envelope error |
| DB_UNIQUE | raw duplicate Application insert | IntegrityError at DB level (pinned) | n/a |
| STATUS_CHOICE | model lacks 'applied' choice | migration adds it (model change, same migration) | n/a |

</frozen-after-approval>

## Code Map

- `backend/listings/models.py` -- Application model (+ status choice if missing).
- `backend/listings/services.py` -- new; apply_to_listing (the AD-4 service home).
- `backend/listings/migrations/` -- new migration (Application table + choice change if any).
- `backend/listings/admin.py` -- Application registered (parity with the other models).
- `backend/api/views.py` -- apply endpoint + bucket param on the listings view.
- `backend/api/urls.py` -- `listings/<id>/apply/` route.
- `backend/api/tests.py` -- new tests.

## Tasks & Acceptance

**Execution:**
- [ ] Model + migration + admin (Application; status 'applied' in choices if absent) -- AD-5 constraint
- [ ] `listings/services.py` -- `apply_to_listing` (atomic, get_or_create, update_fields=['status'], no downgrade) -- AD-4
- [ ] `POST /api/listings/<id>/apply/` -- 404 / 200 envelopes, csrf_exempt -- FR-4/FR-5 + AD-10
- [ ] `GET /api/listings/?bucket=new|all` -- freshness window + applied exclusion; invalid → 422 -- the sweep bucket
- [ ] Tests (APPLY_CREATE, APPLY_REAPPLY, APPLY_UNKNOWN, APPLY_OUTCOME, BUCKET_NEW, BUCKET_ALL, BUCKET_BAD, DB_UNIQUE) -- matrix audit
- [ ] Spec Change Log appended if any deviation -- audit trail

**Acceptance Criteria:**
- Given the backend foundation and a persisted Listing, when `POST /listings/<listing_id>/apply` is called, then an Application record (Listing, timestamp, nullable outcome) is created and the Listing status becomes "applied".
- And the database enforces at most one Application per Listing (unique constraint on listing_id, AD-5).
- And re-applying the same Listing is idempotent: 200 with the existing Application record, no duplicate (AD-10).
- And Listing status changes only through this service, never through collection upserts (AD-4).
- And the outcome field exists but is nullable in v1 for FR-8.

## Spec Change Log

(Append-only; empty until first review loopback.)

### Review loopback 1 (2026-08-19) — implemented + patched, APPROVE

Findings applied:
- **Huge pk → 500** (edge-case): `pk=10**20` raises `OverflowError` in SQLite instead of a miss — now caught with `Listing.DoesNotExist` → 404 envelope. Pinned by `test_apply_huge_pk_returns_404_envelope_not_500`.
- **Empty `bucket=` silently = all** (blind): now 422 when the param is present with an invalid value (`'bucket' in request.GET and bucket not in ('new','all')`).
- **CORS/CSRF seam unpinned** (verification-gap): the apply POST is the Story 2.2 cross-origin seam; added `ApplyCorsTests` — preflight OPTIONS with `Access-Control-Request-Method: POST`, Origin'd POST with echo, disallowed-origin preflight.
- **bucket never exercised with keyword/page** (verification-gap): added `test_new_bucket_combined_with_keyword` and `test_new_bucket_pages_within_the_filtered_set` (30 fresh → page 2 = 5 items, total 30).
- **Re-apply verified only by id** (verification-gap): now asserts the full first/second payload equality (incl. `created_at`).
- **Envelope keys unasserted on bucket responses** (blind): `test_new_bucket_returns_fresh_unapplied_only` now asserts the full `{ok,data,error}` shape.
- **NULL published_at invisible in `bucket=new`** (verification-gap other + edge-case): decision documented by test — NULL-date listings excluded from `new` (no freshness window) but present in `all`, status untouched.
- **Force-applied on re-apply** (edge-case + blind): kept per frozen spec ("leaves it 'applied' whatever it is now") — behavior unchanged; added a comment marking the Epic 3 revisit point in `services.py`.
- **Bucket filter uses `exclude(applied)`** (edge-case): kept per frozen spec ("status != 'applied'"); equivalent to `filter(NEW)` today, no change.

Not adopted (spec intent): none.

## Design Notes

- **get_or_create is the idempotence mechanism:** the OneToOne unique constraint makes the second POST find the existing row — no extra query dance, no race.
- **Status via service only:** `apply_to_listing` is the first resident of `services.py`; Epic 3's outcome/feedback services join it there. Collection code never touches status (already proven by Story 1.3's update_fields patch + its concurrency test).
- **The bucket is the freshness window, not a visit log:** without auth, a "visit" marker has no home; `published_at >= now - 24h` (the AD-7 window the worker already enforces) is the honest equivalent and gives the UI its default view. Bucket is a pure filter on the existing endpoint — no new endpoint, no payload change.
- **Migration is expected here:** only collection-code files are frozen; schema evolution for new features is the normal path (and the reason migrations exist).

## Verification

**Commands (in `backend\`):**
- `uv run python manage.py check` -- 0 issues
- `uv run python manage.py test` -- all pass (214 + new)
- `uv run python manage.py makemigrations --check --dry-run` -- "No changes detected" (migration already applied to the tree)
- `uv run python manage.py migrate` -- applies cleanly

**Manual checks (if no CLI):**
- No collection file changed (git diff limited to listings/, api/, migrations).