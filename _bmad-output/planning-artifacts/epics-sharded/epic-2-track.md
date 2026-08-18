# Epic 2: Close the loop — track applications

One click from any listing records the application; records are idempotent and visible everywhere — the application state survives across days.

**FRs covered:** FR4 (apply action), FR5

## Story 2.1: Application model and apply endpoint

As a job hunter,
I want my applications recorded when I apply,
So that my application state survives across days without manual bookkeeping.

**Acceptance Criteria:**

**Given** the backend foundation and a persisted Listing
**When** `POST /listings/<listing_id>/apply` is called
**Then** an `Application` record (Listing, timestamp, nullable `outcome`) is created and the Listing `status` becomes "applied"
**And** the database enforces at most one Application per Listing (unique constraint on `listing_id`, AD-5)
**And** re-applying the same Listing is idempotent: 200 with the existing Application record, no duplicate (AD-10)
**And** Listing status changes only through this service, never through collection upserts (AD-4)
**And** the `outcome` field (response/interview/silence) exists but is nullable in v1 for FR-8

## Story 2.2: Apply flow in the UI

As a job hunter,
I want to mark a job as applied in one click,
So that tracking happens inside the sweep, not as a separate chore.

**Acceptance Criteria:**

**Given** a Listings list and detail view
**When** Akram clicks **Mark as applied** on a detail view or list row
**Then** the Listing shows an applied state immediately and everywhere it appears
**And** applied Listings disappear from the "new since last visit" bucket but remain visible in the full list
**And** the applied state persists across page reloads and days (state comes from the Django API, AD-2)
**And** clicking apply twice shows no error and no duplicate record (idempotent, FR-5)