# Epic 3 Context: Judge and pace the hunt (v2)

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Epic 3 turns the tracker into a judge: every listing earns a worth-my-time score (FR-6), urgency and churn signals surface from engine history (FR-7), and outcomes steer collection while telling Akram when to rest (FR-8). It covers FR-6/FR-7/FR-8 and depends on Epic 2's `Application.outcome` (nullable, created in Story 2.1 for this epic) and the AD-4 service pattern. This is the v2 pass — the core sweep (Epics 1–2) is already live; these stories add judgment on top of data the engine already persists.

## Stories

- Story 3.1: Interest scoring
- Story 3.2: Urgency signals
- Story 3.3: Outcome feedback and pacing

## Requirements & Constraints

- Every Listing receives an **Interest Score 0–100** (FR-6, AD-4 data only), computed against a hand-maintained profile of Akram's stack and project types.
- Scoring weights **problem-domain overlap and post sanity over tech-stack overlap** (brainstorm decision, PRD §4.4); posts with absurd requirement stacks (nodejs+python+go+java in one backend role) score low via rule-based sanity heuristics.
- The score appears in the listings API payload and the UI detail view; scoring never mutates `status`, `seen_sources`, or the dedup fingerprint (AD-4).
- Urgency signals derive from **engine history alone** (seen_sources sets, fetch history, deletion events — AD-8): a role on N sources → cross-posting footprint (dire-need); a normalized title+text reappearing after deletion → churn-possible; a company posting a cluster of new related roles → growth-possible. Works on sparse platforms with limited metadata.
- Outcomes (response/interview/silence) are entered manually against Applications; outcome entry never duplicates Applications (AD-5); collection weighting adjusts toward responding postings; a stop signal appears on sustained high-quality activity ("10 great matches applied this week — rest").

## Technical Decisions

- **Profile is hand-maintained config, not a DB table:** Django settings constant (`INTEREST_PROFILE`) — tech_stack, domains, project_types lists; scoring is a pure function `score(listing, profile) -> 0..100` in a new `backend/judge/` app module, computed at read time (no schema change, profile edits re-score instantly, AD-4 untouched).
- **Sanity is rule-based:** count distinct known-stack terms in the title text (keywords are user search terms — identical across listings — so they cannot carry posting requirements); > N stack terms in one posting title → penalty.
- **Score lives in the payload, not the store:** `interest_score` added by the listings API (raw_snapshot stays excluded); the row UI renders it as a chip. No migration.
- **Urgency signals (Story 3.2)** are derived flags: cross-posting footprint = `len(seen_sources) >= 2` (dire-need), churn-possible = listing reappeared with a new id after a delete (history from the deletion audit trail Story 1.1 left room for), growth-possible = company with N recent listings. Served as a `signals` object in the listings payload.
- **Pacing (Story 3.3):** outcome update endpoint on the Application (POST with `outcome`), collection weight = function of per-source response rate (recency-weighted), stop signal computed from last-7-day applied counts — surfaced in the API as `pacing` metadata and rendered in the UI header. AD-5 idempotence preserved (outcome update never creates rows).
- Verification: backend tests per story + the established E2E smoke rhythm; frozen collection code is NOT touched by 3.1/3.2 (read-side only); 3.3's collection weighting is the only story that may touch collector code (via a service the worker consults, not the frozen pipeline files).

## UX & Interaction Patterns

- **Score chip** on each listing row (and the detail view's analog): color-coded (green ≥ 70, zinc 40–69, red < 40), always present, updates on refresh (score is computed live).
- **Signal chips** on rows that earn them: "cross-posted", "churn?", "growth?" — small, dismissive, never blocking.
- **Outcome entry:** on applied listings, a small response/interview/silence picker under the Applied badge; choosing one updates the badge to show the outcome.
- **Stop signal:** a quiet line in the page header when pacing says rest ("10 great matches applied this week — rest") — advisory only.

## Cross-Story Dependencies

- 3.1 depends on 1.1–1.3 (persisted listings with title/keywords), 1.8 (payload + UI), and the AD-4 discipline (1.3's update_fields patch).
- 3.2 depends on 1.3's seen_sources append-only (AD-8) and the deletion history Story 1.1 anticipated; 3.1's payload pattern (score) is the template for `signals`.
- 3.3 depends on 2.1's Application + nullable outcome (created there for this epic) and the apply service pattern; the pacing read is built on 2.2's applied-state UI.
- All three are independent of each other except payload/UI plumbing order (3.1 first = the chip pattern the others reuse).