# Epic 1: Discover every matching opportunity in one place

Akram sees all matching jobs from all his sources in one paged list, deduplicated, with a "new since last visit" bucket and full detail views — the morning sweep becomes one session.

**FRs covered:** FR1, FR2, FR3, FR4 (detail view)

## Story 1.1: Backend foundation

As a developer,
I want a running Django backend with the core data models,
So that all collection and application features have a home.

**Acceptance Criteria:**

**Given** an empty workspace
**When** the backend scaffold is created (Django 6.1, Python 3.13, SQLite with WAL mode and busy_timeout)
**Then** `manage.py runserver` starts without errors
**And** the `Source`, `Listing`, and `FetchLog` models exist with migrations applied
**And** `Listing` enforces a unique constraint on `dedup_fingerprint`, carries `status` (default "new"), and an append-only `seen_sources` field
**And** no other tables exist yet (Application model is NOT created here)

## Story 1.2: Source registry with SourcePort

As a job hunter,
I want to register job sites and test their fetches,
So that adding a source is a UI action, not a code change.

**Acceptance Criteria:**

**Given** the backend foundation
**When** a `SourcePort` protocol is defined (`fetch(keywords) → raw items; parse() → canonical field set`)
**Then** adapters implement it and never touch the database
**And** the API exposes register/list/test-fetch endpoints for Sources with the AD-10 envelope
**And** a Source record stores name, adapter key, config (including the Keyword Set)
**And** a test fetch on a Source returns a sample of raw items with the raw snapshot visible
**And** an invalid selector returns the raw HTML snapshot with a selector-mismatch notice (FR-1)

## Story 1.3: Collection pipeline

As a job hunter,
I want scraped postings processed through the six-stage pipeline,
So that raw site data becomes clean, deduplicated, validated Listings.

**Acceptance Criteria:**

**Given** a registered Source with a working adapter
**When** collection runs for that Source
**Then** items pass extract → clean → normalize (pure stages) → dedupe → validate (repository-backed)
**And** a canonical field set is produced (title, company, url, published_at ISO-8601 UTC, keywords, raw_snapshot)
**And** upsert is atomic: existing `dedup_fingerprint` updates only content fields; `status`, `seen_sources`, and the fingerprint itself are never modified by collection (AD-4)
**And** failures are isolated: a malformed fetch writes a FetchLog `{source, stage, ok, error}` and does not stop other Sources (AD-6)

## Story 1.4: Collector worker

As a job hunter,
I want collection to run automatically,
So that I never miss the 24-hour window on fresh postings.

**Acceptance Criteria:**

**Given** registered Sources
**When** the collector worker runs (APScheduler 3.x, 30-minute interval)
**Then** all Sources are polled with the Keyword Set
**And** after downtime, the next pass backfills missed polls
**And** Listings older than 24 hours at backfill carry a freshness marker (AD-7)
**And** the worker runs as a separate process from the Django server (two-process envelope, AD-2)

## Story 1.5: Adapter — ouedkniss jobs

As a job hunter,
I want ouedkniss job postings collected,
So that Algerian-market roles appear in my list.

**Acceptance Criteria:**

**Given** the SourcePort contract
**When** the `ouedkniss-jobs` adapter (Scrapy) fetches with the Keyword Set
**Then** raw listings parse into the canonical field set with valid ISO-8601 UTC dates
**And** postings map to the canonical field set per AD-1 (value harmonization stays in the pipeline, not the adapter)
**And** a Source row with adapter key `ouedkniss-jobs` collects end-to-end (register → test fetch → pipeline → persisted Listing)

## Story 1.6: Adapter — google jobs

As a job hunter,
I want Google Jobs postings collected,
So that roles surfaced by Google's job search appear in my list.

**Acceptance Criteria:**

**Given** the SourcePort contract
**When** the `google-jobs` adapter (wrapping JobSpy, pinned version) fetches with the Keyword Set
**Then** Google results parse into the canonical field set
**And** JobSpy failures (blocking, CAPTCHA) surface as FetchLog entries without stopping other Sources (AD-6)
**And** a Source row with adapter key `google-jobs` collects end-to-end

## Story 1.7: Adapter — facebook developer groups

As a job hunter,
I want Facebook developer-group job posts collected,
So that community-posted roles appear in my list.

**Acceptance Criteria:**

**Given** the SourcePort contract
**When** the `facebook-groups` adapter (Playwright, Google SERP post-URL workaround) fetches
**Then** discovered post URLs scrape into the canonical field set
**And** login-wall failures surface as FetchLog entries and never crash the worker (AD-6)
**And** a Source row with adapter key `facebook-groups` collects end-to-end

## Story 1.8: Listings UI

As a job hunter,
I want a paged list with detail views in my browser,
So that the morning sweep is one session instead of six sites.

**Acceptance Criteria:**

**Given** collected Listings in the database
**When** Akram opens the Next.js app (localhost) and the Listings page
**Then** Listings render newest-first (`published_at DESC, id DESC`), 25 per page, stable across pages and days (AD-9)
**And** a "new since last visit" bucket is the default view, driven by a server-side `last_sweep_at` timestamp; applied Listings are excluded
**And** the detail view shows title, company, source, URL, published date, keywords, raw snapshot access, and the original link (FR-4)
**And** all API calls use the AD-10 envelope from the Django API — the frontend never touches the database (AD-2)