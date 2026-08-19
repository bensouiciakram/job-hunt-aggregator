# Epic 2 Context: Close the loop — track applications

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Epic 2 turns the read-only sweep into a tracking loop: one click from any listing records the application, records are idempotent and visible everywhere, and the application state survives across days. This epic covers FR-4 (apply action) and FR-5 (idempotent re-apply), with the nullable `outcome` field reserving FR-8 for Epic 3. It builds directly on Epic 1's Listing model (status field), the API conventions (envelope {ok, data|error}, csrf_exempt, UUID listing ids), and the Next.js surface (list rows + refresh), all delivered in Stories 1.1–1.8.

## Stories

- Story 2.1: Application model and apply endpoint
- Story 2.2: Apply flow in the UI

## Requirements & Constraints

- `POST /listings/<listing_id>/apply` creates an `Application` record (Listing OneToOne FK, created_at, nullable `outcome`) and sets the Listing `status` to "applied" — atomically.
- The database enforces at most one Application per Listing: unique constraint on `listing_id` (AD-5).
- Re-applying the same Listing is idempotent: 200 with the existing Application record, no duplicate, no error (AD-10).
- Listing `status` changes ONLY through explicit services (apply service here; Epic 3 adds outcome/feedback services) — collection upserts must never touch status (AD-4, already enforced by Story 1.3's update_fields).
- `outcome` (response/interview/silence) exists but stays nullable in v1 (FR-8 arrives with Epic 3).
- The frontend marks a listing applied in one click from a list row or detail view; the applied state renders immediately and everywhere it appears; state comes from the Django API, so it persists across reloads and days (AD-2).
- Applied Listings disappear from the "new since last visit" bucket but remain visible in the full list.
- The "new" bucket: no auth/visit-tracking exists by design (NFR-1, two local processes) — the bucket is the AD-7 freshness window: `published_at >= now - 24h` AND `status != 'applied'`, served by the listings API (`bucket=new`), default view in the UI with a toggle to the full list.
- CORS is already open for http://localhost:3000 / http://127.0.0.1:3000 (Story 1.8) — the client-side apply POST is a cross-origin JSON fetch; Django views are csrf_exempt by convention.

## Technical Decisions

- `Application` model: `listing` OneToOneField(unique — the AD-5 constraint), `created_at` auto_now_add, `outcome` CharField(null=True, blank=True) with choices pending Epic 3; Django migration (schema change is normal in story scope — only collection-code files are frozen).
- Apply service in `backend/listings/services.py`: `apply_to_listing(listing)` — one `transaction.atomic` block; `Application.objects.get_or_create(listing=...)` (idempotent by construction); on create, set `listing.status = 'applied'` and save with `update_fields=['status']`; never downgrades status. Returns the (application, created) pair.
- Endpoint `POST /api/listings/<id>/apply/` in `backend/api/`: 404 envelope for unknown listing; 200 envelope `{ok, data: {application: {id, listing, created_at, outcome}, status: 'applied'}}` on both create and re-apply (AD-10).
- Bucket filter: `GET /api/listings/?bucket=new` — `published_at >= now - 24h` AND `status != 'applied'`, same sort/paging/envelope as Story 1.8; `bucket=all` or absent = full list (unchanged behavior).
- Frontend (Story 2.2): `ApplyButton` client component (fetch POST, optimistic or confirmed state, disabled "Applied" state after success), used on list rows; bucket toggle (New / All) on the home page; double-click safe (idempotent server, no duplicate).
- Verification: backend tests (create/flip, re-apply, 404, envelope, bucket filter incl. applied-excluded) + an E2E smoke with headless Chromium (Playwright) like Story 1.8's, recorded under `_bmad-output/implementation-artifacts/`.

## UX & Interaction Patterns

- **Mark as applied:** one click on any row (or detail view) — the button is the row's primary action; after success it becomes a non-interactive "Applied" marker. No confirmation dialogs (FR-5 wants speed).
- **New bucket default:** the home page defaults to "New (24h)" — applied items drop out of it automatically; the toggle shows "All (n)" to see the full list where applied items remain visible with their marker.
- **Persistence:** the applied marker is rendered from the API's `status` field — a reload or a new day shows the same state.

## Cross-Story Dependencies

- 2.1 depends on 1.1 (Listing model + status field), 1.2 (API conventions, envelope, csrf_exempt), 1.3 (status untouched by collection — proven by the update_fields patch), 1.8 (bucket filter lands on the listings endpoint; the sweep stamp exists).
- 2.2 depends on 2.1 (endpoint) and 1.8 (Next.js surface, CORS already open).
- Epic 3 (Stories 3.1–3.3) depends on 2.1's nullable `outcome` field and the status service pattern.
- The Application model MUST NOT have been created earlier (Story 1.1 deliberately omitted it) — it lands here with its migration.