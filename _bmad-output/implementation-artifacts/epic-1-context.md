# Epic 1 Context: Discover every matching opportunity in one place

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Build the core of the Job Hunt Aggregator: an extensible collection engine and the main browsing experience. Akram registers job sources (ouedkniss, Google Jobs, Facebook developer groups) via the Source Registry, the collector fetches each source with his Keyword Set and runs everything through a six-stage pipeline, and he sees all matching jobs in one paged, deduplicated, newest-first list with a "new since last visit" bucket and full detail views — turning the multi-site morning sweep into one session. This epic covers FR-1 (register/test sources), FR-2 (collect and process), FR-3 (browse), and FR-4's detail view; the mark-as-applied action ships in Epic 2.

## Stories

- Story 1.1: Backend foundation
- Story 1.2: Source registry with SourcePort
- Story 1.3: Collection pipeline
- Story 1.4: Collector worker
- Story 1.5: Adapter — ouedkniss jobs
- Story 1.6: Adapter — google jobs
- Story 1.7: Adapter — facebook developer groups
- Story 1.8: Listings UI

## Requirements & Constraints

- Adding a Source is a registry action (name, adapter key, config with Keyword Set); reusing a registered adapter requires no code changes — a new site type ships one adapter module.
- A test fetch returns a sample of raw items with the raw snapshot visible; an invalid selector returns the raw HTML snapshot with a selector-mismatch notice.
- All collection output passes extract → clean → normalize (pure) → dedupe → validate (repository-backed) before persistence, producing the canonical field set: title, company, url, published_at (ISO-8601 UTC), keywords, raw_snapshot.
- Dedup is atomic and idempotent: unique dedup_fingerprint per Listing; re-collection never duplicates rows; upserts update content fields only, never status, seen_sources, or the fingerprint.
- Failure isolation: a malformed/blocked/CAPTCHA fetch is logged (FetchLog {source, stage, ok, error}) and never stops other Sources; every persisted Listing keeps its raw snapshot.
- Collection runs automatically every 30 minutes; after downtime the next pass backfills missed polls, with a freshness marker on Listings older than 24 hours.
- Browsing is paged at 25, sorted published_at DESC, id DESC — stable across pages and days; applied Listings are excluded from the "new" bucket.
- Runs entirely on one local Windows machine as two processes (Django server + collector worker); all state in SQLite (WAL mode, busy_timeout); no auth, no hosting.
- All API responses use the envelope {ok, data|error}; timestamps ISO-8601 UTC.

## Technical Decisions

- Hexagonal design: a SourcePort boundary (`fetch(keywords) → raw items; parse() → canonical field set`) separates per-site adapters from the core; adapters never touch the DB or each other. Value harmonization (salary units, date formats, location strings) lives in the pipeline's normalize stage, not adapters.
- Django app is the single writer to SQLite (all writes via ORM/services); the Next.js frontend reads and commands only through the JSON API. Schema changes exist only as Django migrations.
- Listing identity: dedup_fingerprint = hash(normalized title + company + url host), computed once at ingestion, immutable, DB-unique; status changes only through explicit services; seen_sources is append-only.
- Pipeline stages are pure filters except dedupe/validate, which consult a thin `ListingRepository` over the ORM.
- Collector worker uses APScheduler 3.x (pin <4), separate process from the Django server.
- Adapters: `ouedkniss-jobs` (Scrapy), `google-jobs` (wraps JobSpy, pinned — most brittle source; AD-6 isolates failures), `facebook-groups` (Playwright with Google SERP post-URL workaround). Code-first adapters (Python module per site + registry row); YAML configs deferred.
- API: DRF-style JSON, envelope {ok, data|error}, listing_id UUIDs in paths; `POST /listings/<id>/apply` idempotent (returns 200 with existing record).
- Stack pins: Python 3.13, Django 6.1, Next.js 16.x, React 19.x, SQLite bundled, Scrapy/Playwright pinned at install.
- Layout per Structural Seed: `backend/` (collector/ with ports, adapters, pipeline, worker; listings/ models; api/) and `frontend/` (Next.js). Naming: kebab-case adapter keys, PascalCase entities, snake_case fields.

## UX & Interaction Patterns

No UX design contract exists; UI derives from the PRD journeys and AD-9/AD-10 semantics. Two flows matter:

- **Morning sweep (UJ-1):** default view is the "new since last visit" bucket — server-side `last_sweep_at` recorded on the sweep view; a Listing is "new" while published_at > last_sweep_at and status is not applied. Applied markers persist across pages and days.
- **Add source (UJ-2):** small form (site name, URL pattern with keyword placeholder, listing selector) plus a test fetch; failures surface the raw page snippet so the selector can be tuned.
- Detail view shows title, company, source, URL, published date, keywords, raw snapshot access, and the original link.

## Cross-Story Dependencies

- 1.1 (backend foundation) is the base for everything: 1.2 needs its models, 1.3 needs the Listing model's unique fingerprint and FetchLog, 1.4 needs the pipeline.
- 1.5/1.6/1.7 (adapters) each depend on 1.2's SourcePort contract and are independent of each other; all three must land for the registry to reach its three launch sources.
- 1.8 (Listings UI) depends on 1.3/1.4 (data exists to display) and 1.2 (API for listings data).
- Epic 2 (apply action) builds on this epic's Listing model (status field) and API conventions; the Application model must NOT be created in Story 1.1.