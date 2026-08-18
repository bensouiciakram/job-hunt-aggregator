---
title: Job Hunt Aggregator
status: final
created: 2026-08-18
updated: 2026-08-18
---

# PRD: Job Hunt Aggregator
*Working title — confirm.*

## 0. Document Purpose
PRD for a personal, local-first job-hunt tool owned and used by Akram Bensouici. Built on the locked direction from the brainstorming session (`_bmad-output/brainstorming/brainstorm-job-hunt-aggregator-2026-08-18/brainstorm-intent.md`): a simple extensible engine plus an application loop first, with interest scoring and urgency signals as the next layer. Downstream owners: `bmad-architecture`, `bmad-create-epics-and-stories`, and Akram as the sole developer. Assumptions are tagged inline `[ASSUMPTION]` and indexed in §9.

## 1. Vision
A local web app that replaces the three-stop manual search routine (job boards → Google with time filters → Facebook groups + LinkedIn) with one place: every job matching his keywords, scraped from an extensible set of sources, deduplicated, and scored for "worth my time." The tool's edge is judgment — it ranks posts by problem-domain overlap and post sanity rather than keyword density, and its persistence gives it history: cross-posting footprints and repost patterns that reveal which postings are urgent and which are churn. For a solo user, the win is hours per week recovered and no posting missed.

## 2. Target User

### 2.1 Jobs To Be Done
- Collect every relevant job posting from his sources into one list, so he stops visiting six places a day.
- Know a posting is worth his time before clicking it (domain match, sane requirements).
- Record the application without ceremony, so the hunt state survives across days.
- Never miss the 24-hour window on a fresh posting (the highest-probability application window in his routine).

### 2.2 Non-Users (v1)
Anyone other than Akram. No accounts, no multi-user, no sharing, no public hosting.

### 2.3 Key User Journeys
- **UJ-1. Akram does the morning sweep.**
  Akram, hunting for a full-stack role in Algeria, opens the local app after coffee. The listing view shows every new posting since yesterday, paged and sorted by recency [ASSUMPTION: recency is the default sort for v1]. He scans titles, opens the two that mention his stack and a familiar problem type, reads the details page, and clicks through to the original posting to apply. Back in the app he hits **Mark as applied** on each. Total time: one session, one tab, no board-hopping. **Edge case:** a post he already applied to yesterday must not re-enter the new list — the applied marker persists across pages and days.
- **UJ-2. Akram adds a new source.**
  He discovers a developer job board he likes. In the app's source management view he adds it by filling a small form — site name, URL pattern with keyword placeholder, listing selector [ASSUMPTION: v1 sources are added via a config-driven adapter, not code edits] — and runs a test fetch. The new source shows in the registry and feeds the next collection pass. If the fetch fails, the app shows the raw page snippet so he can adjust the selector.

## 3. Glossary
- **Source** — a job board or job-hunting surface (e.g., LinkedIn Jobs, Google Jobs, a Facebook developer group) that the engine collects from. Registered in the **Source Registry**.
- **Source Registry** — the extensible, config-driven list of Sources; adding a Source is the primary extension path.
- **Listing** — a single collected job posting after passing the pipeline: a normalized record with title, company, URL, keywords, published date, raw snapshot.
- **Collection Pipeline** — the processing chain every raw scrape passes through: raw → extraction → cleaning → normalization → deduplication → validation (adapted from Akram's real-estate platform).
- **Keyword Set** — Akram's search terms (e.g., "full stack," "backend," "python," "nextjs," "django") used for fetching and filtering.
- **Application** — the record of Akram applying to a Listing, marked in the Application Loop.
- **Application Loop** — the mark-as-applied flow plus, later, the feedback mechanisms (self-tuning, stop signal) built on Application records.
- **Interest Score** — the "worth my time" rating of a Listing. v2 feature.
- **Urgency Signal** — a derived indicator on a Listing (cross-posting footprint, repost pattern). v2 feature.

## 4. Features

### 4.1 Source Registry and Collection (v1)
**Description:** The engine's skeleton. A Source Registry holds every configured Source; each Source defines how to fetch (URL pattern with the Keyword Set substituted), how to select listings, and how to map them into the pipeline's raw stage. Collection runs on a schedule with polling [ASSUMPTION: polling interval 30 minutes, configurable; real-time push is later]. Sources are added through the registry UI with a test-fetch that surfaces the raw page for selector tuning. Realizes UJ-2.

**Functional Requirements:**

#### FR-1: Register and test a Source
Akram can add a Source (name, URL pattern with keyword placeholder, listing selector), and the system can run a test fetch that returns a sample of raw listings for validation.

**Consequences (testable):**
- A Source added through the UI appears in the registry and is included in the next collection pass without code changes when it reuses a registered adapter; a new site type ships one adapter module (resolution at architecture step, AD-1).
- A test fetch with an invalid selector returns the raw HTML snapshot with a selector-mismatch notice.

#### FR-2: Collect and process Listings
The system can fetch Listings for each Source using the Keyword Set and run them through the Collection Pipeline (extraction, cleaning, normalization, deduplication, validation) before persistence.

**Consequences (testable):**
- Two Sources yielding the same posting produce one Listing (deduplication by normalized title+company [ASSUMPTION: plus URL host; cross-platform cross-posting rules land with Urgency Signals in v2]).
- Malformed or empty fetches are logged and do not stop other Sources' collection.
- After downtime (machine off for hours or days), the next collection pass backfills missed polls, and the "new" bucket fills in published-date order with a freshness marker on anything older than 24 hours.
- A Listing stores: title, company, URL, published date (when available), raw snapshot.

### 4.2 Listings View (v1)
**Description:** The main screen of the local web app: a paged full list of Listings, newest first, with a "new since last visit" bucket as the default view [ASSUMPTION: v1 filters are keyword-based; ranking lands with Interest Scoring]. Each row shows title, company, source, age, and — once scoring lands — its Interest Score. The v1 detail view shows: title, company, source, URL, published date, extracted keywords, raw snapshot access, and the link to the original posting, with the **Mark as applied** button. Realizes UJ-1.

**Functional Requirements:**

#### FR-3: Browse Listings by page
Akram can browse the full Listings list in pages of a fixed size [ASSUMPTION: 25 per page].

**Consequences (testable):**
- Paging returns stable order (newest first) across page boundaries and days.
- Applied Listings are visually marked and do not reappear in the "new" bucket.

#### FR-4: View a Listing detail with application action
Akram can open a Listing's detail view, see all stored data and the original link, and mark it as applied in one action.

**Consequences (testable):**
- One click on **Mark as applied** persists an Application record and changes the Listing's state everywhere it appears.
- Applying from the detail view realizes the loop without navigation away from the local app.

### 4.3 Application Loop (v1 core, v2 feedback)
**Description:** The Application record is the seed of the product's memory: once Applications exist, the self-tuning filter (steer collection toward postings that respond) and the stop signal (e.g., "10 great matches applied this week — rest") are the same feedback loop worn two ways. v1 ships only the mark-as-applied record; self-tuning and stop are v2. Realizes UJ-1.

**Functional Requirements:**

#### FR-5: Record an Application
Akram can mark a Listing as applied, at which point the system stores an Application record (Listing, timestamp, optional note [ASSUMPTION: note field deferred]).

**Consequences (testable):**
- A Listing can have at most one Application record; re-marking is idempotent.
- Applications survive restarts (local persistence).

### 4.4 Interest Scoring and Urgency Signals (v2)
**Description:** The judgment layer. Interest Score = weighted combination of problem-domain overlap and post sanity, deliberately weighted over tech-stack overlap (decision from brainstorming). Urgency Signals derive from engine history: cross-posting footprint (same recruiter, same role, many Sources → dire need) and repost patterns (same text reappearing after deletion → churn; cluster of new roles → growth). Deferred to v2 per the locked build order; requirements captured now so architecture accommodates them.

**Functional Requirements:**

#### FR-6: Compute an Interest Score (v2)
The system can score a Listing from 0–100 [ASSUMPTION: range pinned for architecture; weights tuned in v2] by problem-domain overlap with Akram's prior work and post sanity (realistic, non-absurd requirement stacks), weighted per the decision from the brainstorming session (path: `_bmad-output/brainstorming/brainstorm-job-hunt-aggregator-2026-08-18/brainstorm-intent.md`) over tech-stack overlap.

**Consequences (testable):**
- Score inputs are computed from Listing text and a profile of Akram's stack and project types [ASSUMPTION: profile is hand-maintained in v2].
- Post sanity flag identifies e.g. "nodejs, python, go, and java for one backend role" [ASSUMPTION: sanity = rule-based heuristics in v2; LLM parsing deferred].

#### FR-7: Derive Urgency Signals (v2)
The system can flag a Listing with urgency (cross-posting footprint) and churn/growth (repost history) using only data the engine already persists.

**Consequences (testable):**
- A role appearing on N Sources yields a cross-posting footprint count per recruiter-role.
- A Listing whose normalized title+text reappears after deletion is flagged churn-possible.
- A company posting a cluster of new, related roles yields a growth-possible flag.
- Signals derive from engine history alone, so they work on sparse platforms with limited metadata.

#### FR-8: Feed back and pace (v2)
The system can record application outcomes (response / interview / silence) [ASSUMPTION: outcome entry is manual in v2] and use them to steer future collection weighting (self-tuning) and to surface a stop signal (e.g., "N great matches applied this week — rest").

**Consequences (testable):**
- An outcome recorded against an Application updates the source/score weighting of the next collection pass.
- The stop signal appears only when Application outcomes indicate sustained high-quality activity.

## 5. Non-Goals (Explicit)
- Not a public/multi-user platform; never hosted.
- Not an auto-apply tool (no automated applications).
- Not a general job-search engine (no global coverage).
- Not a LinkedIn-network tool (no messaging, InMail, endorsements).

## 6. MVP Scope

### 6.1 In Scope
- Source Registry with add-and-test-fetch flow, 3 sources at launch: Google Jobs (JSON-LD parse), ouedkniss jobs section, Facebook developer groups (via Google SERP post-URL workaround). LinkedIn Jobs deferred to v1.5 [decision: ban risk on a personal account; revisit with a dedicated account option].
- Collection Pipeline (reused design from real-estate platform) with keyword-driven polling.
- Paged Listings view with detail page and Mark-as-applied.
- Local web app: Django API + scrapers, Next.js frontend, run on localhost [ASSUMPTION: single-user local runtime, no auth].

### 6.2 Out of Scope for MVP
- Interest Scoring and Urgency Signals (v2; core value-add, but engine must exist first).
- Self-tuning filter and stop signal (v2, same feedback loop).
- Browser notifications / real-time push (v1.5; polling covers the sweep; notification click must open the Listing detail with the Mark-as-applied action — one-click loop spec carries into the v1.5 stub).
- LLM-based parsing (v2; rule-based pipeline first).
- Analytics dashboards (v2).
- Social-traffic and viral-product engines (later; engine capabilities left unexercised).
- Application note field (v1.5). `[NOTE FOR PM: emotionally load-bearing — one-click apply record without notes may feel thin; revisit if timeline permits.]`

## 7. Success Metrics
- **SM-1**: Akram uses the tool for at least 3 weeks without returning to the manual multi-site routine for new-post sweeps (validates FR-1–FR-5).
- **SM-2**: The morning sweep — checking and triaging new postings — fits in one session under 15 minutes (validates FR-3, FR-4).
- **SM-C1** (counter-metric): Do not optimize for raw listing volume — a bigger list that buries quality is failure; the goal is curation, not coverage.

## 8. Open Questions
1. **Source adapter form** — config-driven adapter files (YAML) vs. a database-backed registry UI; affects FR-1's "no code changes" promise. Owner: Akram; revisit at architecture step.
2. **Scrape layer** — JobSpy (addendum, Options Considered) is the strongest reuse candidate for LinkedIn/Google sources; confirm wrapping JobSpy vs. bespoke Scrapy/Playwright scrapers. Owner: Akram; revisit at architecture step.
- *Resolved:* LinkedIn source deferred to v1.5 (ban risk); Google Jobs approach confirmed as JSON-LD parse; Facebook groups via SERP workaround.

## 9. Assumptions Index
- §2.3: v1 default sort is recency.
- §2.3 / §4.1: Sources are added via config-driven adapters, not code edits.
- §4.1: Polling interval 30 minutes, configurable.
- §4.1: Dedup key is normalized title + company (+ URL host); cross-platform cross-posting rules land with Urgency Signals in v2.
- §4.2: v1 filters are keyword-based; ranking lands with Interest Scoring.
- §4.2: 25 listings per page.
- §4.3: Application note field deferred to v1.5.
- §4.4: v2 profile is hand-maintained; sanity checks are rule-based heuristics, LLM parsing deferred; score range 0–100.
- §6.1: Launch sources are Google Jobs, ouedkniss jobs, and Facebook developer groups; LinkedIn deferred to v1.5.
- §6.1: Local runtime for a single user, no auth.
- §8: v1 Keyword Set is the manual-process list (full stack, backend, python, nextjs, django); additions are change requests.