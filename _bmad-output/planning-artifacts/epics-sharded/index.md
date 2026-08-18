---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories]
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-Job Hunt Mangement System-2026-08-18/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-Job Hunt Mangement System-2026-08-18/ARCHITECTURE-SPINE.md
---

# Job Hunt Aggregator - Epic Breakdown (Sharded)

## Overview

This document indexes the complete epic and story breakdown for the Job Hunt Aggregator. Each epic lives in its own file so a dev agent can load only the epic it works on. The flat `epics.md` was sharded into this folder.

## Requirements Inventory

### Functional Requirements

FR1: Akram can add a Source (name, URL pattern with keyword placeholder, listing selector), and the system can run a test fetch that returns a sample of raw listings for validation. A Source reusing a registered adapter needs no code changes; a new site type ships one adapter module.

FR2: The system can fetch Listings for each Source using the Keyword Set and run them through the Collection Pipeline (extraction, cleaning, normalization, deduplication, validation) before persistence. Dedup is atomic (unique fingerprint); malformed fetches are logged and isolated; downtime backfills missed polls with a freshness marker on items older than 24 hours.

FR3: Akram can browse the full Listings list in pages of 25, newest-first (published_at DESC, id DESC), with a "new since last visit" bucket as the default view; applied Listings are visually marked and excluded from the new bucket.

FR4: Akram can open a Listing's detail view (title, company, source, URL, published date, keywords, raw snapshot access, original link) and mark it as applied in one action.

FR5: Marking a Listing as applied persists an Application record (Listing, timestamp); re-marking is idempotent (one Application per Listing).

FR6 (v2): The system can score a Listing 0-100 by problem-domain overlap with Akram's prior work and post sanity (rule-based heuristics), weighted over tech-stack overlap.

FR7 (v2): The system can flag urgency (cross-posting footprint per recruiter-role) and churn/growth (repost history) using only engine-persisted data.

FR8 (v2): The system can record application outcomes (response/interview/silence, manual entry) and use them to steer collection weighting (self-tuning) and surface a stop signal.

### NonFunctional Requirements

NFR1: All data stays local — no hosting, no external data transmission; runs on one Windows machine as two processes (Django server + collector worker).

NFR2: Collection robustness — one Source failing (malformed fetch, block, CAPTCHA) is logged and never stops other Sources; every persisted Listing keeps its raw snapshot.

NFR3: Idempotency — re-collection and re-applying never duplicate rows (unique constraints on dedup fingerprint and listing_id).

NFR4: SQLite write safety — WAL mode with busy_timeout; all writes through the Django ORM.

NFR5: Pagination stability — sort order (published_at DESC, id DESC) is stable across pages and days.

NFR6: API consistency — all endpoints return the envelope {ok, data|error}; timestamps ISO-8601 UTC.

### Additional Requirements

- Greenfield project — no starter template specified; scaffold per the Structural Seed (backend/ + frontend/ layout, AD-2/AD-1 boundaries).
- SourcePort contract (AD-1): adapters implement fetch(keywords) → raw items; parse() → canonical field set (title, company, url, published_at ISO-8601 UTC, keywords, raw_snapshot); adapters never touch the DB.
- Adapter implementations: google-jobs wraps JobSpy (pin python-jobspy); ouedkniss-jobs via Scrapy; facebook-groups via Playwright with Google SERP workaround.
- Listing identity (AD-4): dedup_fingerprint = hash(normalized title + company + url host), immutable, DB unique constraint; upsert updates only content fields; status changes only via explicit services; seen_sources append-only.
- Application uniqueness (AD-5): unique constraint on listing_id; outcome field nullable in v1 for FR-8.
- Failure isolation (AD-6): per-Source error boundary + FetchLog entries {source, stage, ok, error}.
- Collection cadence (AD-7): APScheduler 3.x (<4) in collector worker, 30-min polling, backfill after downtime.
- Urgency data (AD-8): dedup stage records cross-posting footprint + deletion events in Listing history.
- Listing view semantics (AD-9): sort published_at DESC, id DESC; page size 25; server-side last_sweep_at defines the new bucket.
- API contract (AD-10): DRF-style JSON, envelope {ok, data|error}, POST /listings/<listing_id>/apply idempotent (200 with existing record).
- SQLite WAL + busy_timeout as the locking story (AD-2); config via registry rows + settings.py; no auth.
- Version pins: Python 3.13, Django 6.1, Next.js 16.x, React 19.x, JobSpy latest, Scrapy latest, Playwright latest, APScheduler 3.x.

### UX Design Requirements

No UX design contract exists for this project; UI stories derive from the PRD journeys (UJ-1 morning sweep, UJ-2 add source) and AD-9/AD-10 semantics.

### FR Coverage Map

FR1: Epic 1 - Register and test Sources via SourcePort + registry (adapter reuse = no code change)
FR2: Epic 1 - Keyword-driven collection through the six-stage pipeline with atomic dedup, failure isolation, backfill
FR3: Epic 1 - Paged browsing, stable sort, "new since last visit" bucket
FR4: Epic 1 (detail view) + Epic 2 (apply action) - detail view with original link; one-click mark-as-applied
FR5: Epic 2 - Idempotent Application records (unique on listing_id)
FR6: Epic 3 - Interest Score 0-100 (problem-domain + post sanity over tech-stack)
FR7: Epic 3 - Urgency signals from cross-posting footprint + repost history
FR8: Epic 3 - Outcome-driven self-tuning and stop signal

## Epic List

- [Epic 1: Discover every matching opportunity in one place](epic-1-discover.md) — FR1, FR2, FR3, FR4 (detail view) · 8 stories
- [Epic 2: Close the loop — track applications](epic-2-track.md) — FR4 (apply action), FR5 · 2 stories
- [Epic 3: Judge and pace the hunt (v2)](epic-3-judge.md) — FR6, FR7, FR8 · 3 stories