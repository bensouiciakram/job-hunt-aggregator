---
title: 'Story 2.2: Apply flow in the UI'
type: 'feature'
created: '2026-08-19'
status: 'done'
review_loop_iteration: 0
context:
  - _bmad-output/implementation-artifacts/epic-2-context.md
  - _bmad-output/implementation-artifacts/spec-2-1-application-model.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The backend can record applications (Story 2.1) but the sweep UI has no way to mark a listing applied — the loop still requires leaving the app.

**Approach:** Add one-click **Mark as applied** to every listing row, an applied state that renders immediately and everywhere (list + across reloads, state comes from the Django API), and the New (24h) / All bucket toggle that Story 2.1's `bucket` filter enables. Applied listings disappear from the New bucket and remain visible in All with an Applied badge. Double-click is safe: the button disables while the request is in flight, and the backend is idempotent regardless.

## Boundaries & Constraints

**Always:**
- `ApplyButton` (client island): POST to `/api/listings/<id>/apply/` via the shared `applyToListing` helper (`frontend/app/lib/api.ts`); while pending the button shows "Applying…" and is disabled; on success calls `onApplied(id)` (no refetch); on failure shows an inline error and keeps the button enabled for retry (server is idempotent).
- Applied state: server-owned (`item.status === "applied"`) — the badge is rendered from the API payload, so it persists across reloads and days (AD-2).
- Bucket toggle (`BucketToggle`): two buttons, New (24h) / All; URL-driven (`router.push`), absent `bucket` in the URL = New (the default), `?bucket=all` = full list; preserved across pagination and search.
- List behavior: in New bucket, an applied listing is removed from the rendered list on success; in All bucket, its button becomes the non-interactive Applied badge. No confirmation dialogs (FR-5).
- The server fetch ALWAYS sends `bucket` (New included) — the API treats absent `bucket` as the full list, so omitting it would silently show everything.
- Server-rendered initial data + a remounted client view keyed on `${bucket}-${keyword}-${page}` so `router.push` navigations reset the list from fresh server data (stale client state must not survive a bucket/page/search change).

**Ask First:** (none)

**Never:**
- No backend changes (Story 2.1 owns the endpoint; 231 backend tests already pin it).
- No duplicate-record path: never POST from the client more than once per click (pending guard) and never render an extra Apply button once applied.
- No changes to the frozen collection code.
- No client-only state as the source of truth for the applied status — the reload must show the same state.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| APPLY_NEW | fresh unapplied row, New bucket | row removed from view on success | inline error text, button re-enabled |
| APPLY_ALL | fresh unapplied row, All bucket | row shows Applied badge | inline error text, button re-enabled |
| DOUBLE_CLICK | rapid second click during flight | second click ignored (disabled) | none (idempotent server too) |
| TOGGLE_NEW | click New (24h) from All | URL → `/`, list re-fetches bucket=new | server 422 never sent (UI only emits valid values) |
| TOGGLE_ALL | click All from New | URL → `/?bucket=all`, applied items visible with badge | n/a |
| SEARCH_BUCKET | search in New bucket | keyword preserved with bucket; empty → "No listings match your search." | n/a |
| PAGE_BUCKET | paginate in New bucket | page param preserved with bucket | clamp handled by API |
| SERVER_DOWN | POST fails (network) | inline error "Could not reach the backend." | button re-enabled |
| APPLIED_BADGE | applied row, All bucket | badge shown, no button, not clickable | n/a |

</frozen-after-approval>

## Code Map

- `frontend/app/lib/api.ts` -- shared `API_URL` + `applyToListing`.
- `frontend/app/components/apply-button.tsx` -- the one-click island (pending/error/applied states).
- `frontend/app/components/bucket-toggle.tsx` -- New/All toggle (URL-driven).
- `frontend/app/components/listings-view.tsx` -- client list: rows, apply wiring, empty-state copy, applied-removal/badge logic.
- `frontend/app/components/search-box.tsx` -- preserves bucket across searches.
- `frontend/app/components/pagination.tsx` -- preserves bucket across pages.
- `frontend/app/page.tsx` -- bucket param parsing, always-send-bucket fetch, keyed remount.

## Tasks & Acceptance

**Execution:**
- [x] Shared API helper (applyToListing, stripped API_URL)
- [x] ApplyButton island (pending/error/applied)
- [x] BucketToggle (New/All, URL-driven, param preservation)
- [x] ListingsView (apply wiring, empty-state branch for the New bucket)
- [x] page.tsx bucket parse + always-send-bucket + keyed remount
- [x] Build + lint gates, E2E smoke (6/6), evidence recorded

**Acceptance Criteria:**
- Given a Listings list and detail view, when Akram clicks **Mark as applied** on a detail view or list row, then the Listing shows an applied state immediately and everywhere it appears.
- And applied Listings disappear from the "new since last visit" bucket but remain visible in the full list.
- And the applied state persists across page reloads and days (state comes from the Django API, AD-2).
- And clicking apply twice shows no error and no duplicate record (idempotent, FR-5).

## Spec Change Log

(Append-only; empty until first review loopback.)

### Review loopback 1 (2026-08-19) — smoke-driven, fixed + APPROVE

The headless-Chromium smoke acted as the review gate and caught one real bug:

- **New bucket never filtered server-side** (E2E step 5 regression): `fetchListings` set `bucket` only when `all`; the API treats absent `bucket` as the full list, so `/` rendered everything including applied items until a manual reload. Fixed — the fetch now always sends `bucket`. Pinned by smoke steps 3/5.
- **Stale client state across `router.push`**: the `useState(items)` list survived navigations (same component type), so toggling bucket showed stale rows. Fixed by keying `ListingsView` on `${bucket}-${keyword}-${page}` (same remount pattern as `SearchBox`).

Not adopted (spec intent): none.

## Design Notes

- **URL convention:** absent `bucket` = New (the default view), `?bucket=all` = full list. This keeps the default URL clean while the API filter is always explicit on the fetch side (API contract: absent = full list).
- **No optimistic apply:** the row is updated only after a successful POST (no fake-Applied flash that would lie if the request failed). FR-5 wants speed, but correctness of the server-owned state wins; the button gives immediate feedback while pending.
- **Empty-state copy for New:** "No new listings in the last 24 hours." — distinct from the keyword no-match copy, so the default view never lies about what it's showing.

## Verification

**Commands (backend, in `backend\`):**
- `uv run python manage.py test` -- 231 OK (no backend change in this story)
- `uv run python manage.py check` -- 0 issues

**Commands (frontend, in `frontend\`):**
- `npm.cmd run build` -- exit 0 (Next.js 16.3.1; `/` is ƒ Dynamic)
- `npm.cmd run lint` -- exit 0 (0 warnings)

**E2E (headless Chromium):**
- `uv run python ..\_bmad-output\implementation-artifacts\story-2-2-smoke\run_smoke.py` -- 6/6 PASS
- Evidence: `_bmad-output/implementation-artifacts/story-2-2-smoke/evidence.md`