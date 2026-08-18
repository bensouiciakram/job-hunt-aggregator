---
name: Job Hunt Aggregator
type: architecture-spine
purpose: build-substrate
altitude: feature
paradigm: Hexagonal collector (Ports & Adapters) with a filter-chain pipeline core, behind a single-owner Django API
scope: Job Hunt Aggregator v1 (FR-1..FR-5) + v2 hooks (FR-6..FR-8)
status: final
created: 2026-08-18
updated: 2026-08-18
binds: [FR-1, FR-2, FR-3, FR-4, FR-5, FR-6, FR-7, FR-8]
sources:
  - _bmad-output/planning-artifacts/prds/prd-Job Hunt Mangement System-2026-08-18/prd.md
companions: []
---

# Architecture Spine — Job Hunt Aggregator

## Design Paradigm

**Hexagonal collector behind a single-owner core.** The system is a small Django monolith whose two outer faces are: (a) a *SourcePort* boundary through which pluggable per-site scrapers (adapters) feed raw data, and (b) a JSON API consumed by a local Next.js frontend. Inside the core, collection processing is a **filter-chain pipeline**: raw → extraction → cleaning → normalization → deduplication → validation (adapted from Akram's ouedkniss real-estate platform). One invariant does most of the work: **everything that touches the database goes through the Django app** — adapters and the frontend are both outsiders.

```
browser ⇄ Next.js (localhost) ⇄ Django JSON API ⇄ Django core (ORM, services)
                                     ▲
                          SourcePort boundary
                          │ adapters (per site)
                          │ JobSpy/google · scrapy/ouedkniss · playwright/facebook
                          ▼
                     filter-chain pipeline → SQLite
```

## Invariants & Rules

### AD-1 — The SourcePort extension contract

- **Binds:** FR-1, FR-2, FR-5 (all collection)
- **Prevents:** core edits per new site; adapter-specific logic leaking into the core or DB
- **Rule:** Every Source is an adapter implementing `SourcePort: fetch(keywords) → raw items; parse() → canonical field set` plus one row in the Source Registry (name, adapter key, config). The canonical field set is fixed: `title, company, url, published_at (ISO-8601 UTC), keywords, raw_snapshot`. Adapters map *site structure* into canonical fields; cross-source *value harmonization* (salary units, date formats, location strings) belongs to the pipeline's normalize stage (AD-3) — never to adapters. Adding a site = new adapter + registry row; **reusing a registered adapter = registry row only, no code change**. Adapters may not import each other or touch the DB. Resolution of PRD OQ1: code-first adapters (a Python module per site), YAML-only configs deferred.

### AD-2 — Single owner of persisted state

- **Binds:** all
- **Prevents:** two writers (frontend vs collector) drifting the schema; direct DB access from Next.js
- **Rule:** The Django app is the only writer to SQLite; all writes go through Django ORM/services (adapters and the Next.js frontend included). The Next.js app reads and issues commands only via the JSON API. Schema changes exist only as Django migrations. The two local processes (Django server + collector worker) both write via the ORM; SQLite runs in WAL mode with `busy_timeout` set so interleaved writes serialize at the DB, not in app logic. [ASSUMPTION: WAL + busy_timeout are the whole locking story for a single-user localhost load]

### AD-3 — Pipeline stages are pure filters

- **Binds:** FR-2
- **Prevents:** pipeline stages coupling to each other or to storage
- **Rule:** Extraction, cleaning, and normalization are pure transforms (raw item → canonical fields). Boundary: adapters map site structure into canonical fields (AD-1); the normalize stage harmonizes *values* across sources (salary units, date formats, location strings). Only deduplication and validation consult the database, through a thin repository interface. [ASSUMPTION: repository = Django ORM queries wrapped in a `ListingRepository` service class]

### AD-4 — Listing identity and idempotent upsert

- **Binds:** FR-2, FR-3
- **Prevents:** duplicate Listings across Sources; re-collection creating duplicates; collection clobbering application state
- **Rule:** Canonical `Listing` entity (title, company, url, source, published_at, keywords, raw_snapshot, status, dedup_fingerprint). `dedup_fingerprint` = hash of normalized(title) + company + url host, computed **once at ingestion and immutable thereafter** — it is never part of an upsert and never updates. Upsert semantics: an incoming item whose fingerprint exists updates only content fields (title, company, url, published_at, keywords, raw_snapshot) via atomic get-or-create; it never touches `status`, `seen_sources`, or `dedup_fingerprint`. `status` changes only through explicit services (the apply action; later, expiry). `seen_sources` is append-only — cross-posting footprint is derived from it, never overwritten. The fingerprint carries a DB unique constraint (AD-5's pattern) so concurrent collection passes cannot insert duplicates. [ADOPTED — PRD FR-2; amended: PRD FR-1 consequence "without code changes" narrowed to "reusing a registered adapter"]

### AD-5 — Application uniqueness

- **Binds:** FR-5
- **Prevents:** double-apply records
- **Rule:** One `Application` per `Listing` (DB unique constraint on listing_id); marking applied is idempotent. An `Application` stores outcome (response/interview/silence — v2 field, nullable in v1) so FR-8's feedback loop needs no migration.

### AD-6 — Failure isolation per Source

- **Binds:** FR-2
- **Prevents:** one broken Source halting collection
- **Rule:** Each adapter fetch runs in its own error boundary: malformed or empty fetches are logged as `FetchLog` entries and never stop other Sources. Every persisted Listing keeps its raw snapshot for selector repair. [ADOPTED — PRD FR-2]

### AD-7 — Collection cadence and backfill

- **Binds:** FR-2, FR-3, FR-4
- **Prevents:** missed polls without catch-up (the "24-hour window" value prop)
- **Rule:** A collector worker polls all Sources every 30 minutes via APScheduler. After downtime, the next pass backfills missed polls and marks Listings older than 24 hours with a freshness flag. [ADOPTED — PRD FR-2 consequence]

### AD-8 — Cross-source dedup feeds Urgency Signals for free

- **Binds:** FR-2, FR-7 (v2)
- **Prevents:** a second v2 pipeline that duplicates collection data
- **Rule:** The dedup stage records cross-posting footprint (same normalized role seen on N Sources) and deletion events in the Listing history; v2 Urgency Signals (FR-7) are queries over this data, not new collection. [ASSUMPTION: history = timestamps + a `seen_sources` set per Listing; deletion events from absent-in-next-fetch detection]

### AD-9 — Listing order, paging, and the new bucket

- **Binds:** FR-3, FR-4
- **Prevents:** two builders choosing incompatible sort keys, page shapes, or bucket definitions for the same view
- **Rule:** Listings sort newest-first by `published_at DESC, id DESC` (tie-break stable across pages and days). Page size is 25. The "new since last visit" bucket is defined server-side: the app records `last_sweep_at` on the sweep view; a Listing is "new" while `published_at > last_sweep_at` and `status` is not applied. [ASSUMPTION: single-user means one server-side timestamp suffices; no per-device tracking]

### AD-10 — JSON API contract

- **Binds:** FR-3, FR-4, FR-5
- **Prevents:** frontend/API ambiguity (envelope shape, idempotency semantics, identifier location)
- **Rule:** The Django API is a DRF-style JSON API with envelope `{ok: bool, data: … | error: {code, message}}`. Listings and Applications are addressed by listing ID in the path. `POST /listings/<listing_id>/apply` is idempotent: it returns 200 with the existing Application record when one exists (no 409). Timestamps serialize as ISO-8601 UTC. Next.js consumes only this envelope.

```
┌──────────────┐  ┌─────────────────┐  ┌────────────────────────────┐
│ Next.js 16   │→ │ Django API      │→ │ Django core: services, ORM │
│ (localhost)  │  │ (JSON, no auth) │  │ SQLite (single writer)     │
└──────────────┘  └─────────────────┘  └────────────┬───────────────┘
                                                    ▲
                          SourcePort: fetch(keywords)→raw items
            ┌─────────────────────┬─────────────────┴──────────────┐
            │                     │                                 │
   adapter: google          adapter: ouedkniss           adapter: facebook-groups
   (wraps JobSpy)           (Scrapy, JSON-LD/HTML)       (Playwright, SERP workaround)
            └─────────────┬─────────┴──────────┬──────────────┘
                          ▼                    ▼
               filter-chain pipeline    APScheduler worker
               raw→extract→clean→       (30 min polling,
               normalize→dedupe→        backfill on downtime)
               validate
```

## Consistency Conventions

| Concern | Convention |
| --- | --- |
| Naming (entities, files, interfaces, events) | kebab-case adapter keys (`ouedkniss-jobs`, `google-jobs`, `facebook-groups`); PascalCase entities; snake_case fields |
| Data & formats (ids, dates, error shapes, envelopes) | Timestamps UTC ISO-8601; `listing_id` UUID; error envelope `{source, stage, ok, error}` in FetchLog; salary/location normalization per pipeline |
| State & cross-cutting (mutation, errors, logging, config) | All mutation via ORM (AD-2); FetchLog for scrape failures; config = registry rows + settings.py; no auth (localhost) |

## Stack

| Name | Version |
| --- | --- |
| Python | 3.13 |
| Django | 6.1 |
| Next.js | 16.x |
| React | 19.x |
| SQLite | bundled with Python |
| JobSpy (`python-jobspy`) | latest (pin at install; wraps google adapter) |
| Scrapy | pin at install (ouedkniss adapter) |
| Playwright | pin at install (facebook adapter) |
| APScheduler | 3.x (pin <4; 4.0 still alpha) |

## Structural Seed

```text
job-hunt-aggregator/
  backend/                # Django project (single owner of state)
    collector/
      ports.py            # SourcePort protocol
      adapters/
        google.py         # wraps JobSpy
        ouedkniss.py      # Scrapy-based
        facebook_groups.py# Playwright-based, SERP workaround
      pipeline/           # pure filter stages
        extract.py  clean.py  normalize.py  dedupe.py  validate.py
      worker.py           # APScheduler loop, 30-min poll + backfill
    listings/             # models: Source, Listing, Application, FetchLog
    api/                  # JSON API for the frontend
  frontend/               # Next.js 16, localhost
```

## Capability → Architecture Map

| Capability / Area | Lives in | Governed by |
| --- | --- | --- |
| FR-1 register + test Source | backend/collector/adapters + listings.Source | AD-1 |
| FR-2 collect + pipeline | backend/collector/pipeline | AD-1, AD-3, AD-6, AD-7, AD-8 |
| FR-3 browse Listings | frontend + backend/api | AD-2, AD-4 |
| FR-4 detail + apply action | frontend + backend/api | AD-2, AD-5 |
| FR-5 record Application | backend/api + listings.Application | AD-2, AD-5 |
| FR-6 Interest Score (v2) | backend/scoring (future) | AD-2, AD-4 |
| FR-7 Urgency Signals (v2) | queries over Listing history | AD-8 |
| FR-8 feedback + pacing (v2) | backend/scoring (future) | AD-5 (outcome field) |

## Deferred

- **Scoring algorithms** (FR-6, v2): profile hand-maintained, rule-based sanity heuristics; LLM parsing later. The data (Listing keywords + Application outcomes) is already captured.
- **Notifications / real-time push** (v1.5): frontend polls; APScheduler loop is the v1 "real-time."
- **LinkedIn source** (v1.5): ban risk on personal account; revisit with dedicated-account option.
- **Auth / multi-user / hosting**: localhost single-user forever at this altitude; deployment envelope = one Windows machine, two processes (Django server + collector worker).
- **DB engine**: SQLite; Postgres only if this ever leaves localhost.
- **Dashboard/analytics** (v2+), **social/viral engines** (later): engine generality unexercised.
- **Google Jobs fragility**: the `google-jobs` adapter (JobSpy) is the most brittle source (SERP blocking, CAPTCHA); AD-6 isolates failures — a proxy/SERP-API fallback for that adapter is a v1.5 option, not a v1 requirement.
- **Adapter form** (PRD OQ1): resolved — code-first adapters (Python module per site, registry row to enable); YAML-only configs deferred. Reusing a registered adapter requires no code changes; adding a new site type does (AD-1). [ASSUMPTION: user approves this resolution of the PRD's "without code changes" wording — PRD FR-1 consequence to be amended accordingly]