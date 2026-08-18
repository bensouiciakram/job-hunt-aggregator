# Reconcile: brainstorm-intent.md vs PRD (+ addendum)

*Source: `_bmad-output/brainstorming/brainstorm-job-hunt-aggregator-2026-08-18/brainstorm-intent.md`*
*Target: `_bmad-output/planning-artifacts/prds/prd-Job Hunt Mangement System-2026-08-18/prd.md` (+ `addendum.md`)*
*Date: 2026-08-18*

## Verdict: CAPTURED — all intent items present; 4 completeness/consistency gaps

## Per-item check

| # | Intent item | Status | Where |
|---|---|---|---|
| 1 | Locked build order (engine skeleton + application loop first; scoring/urgency after) | Captured | §0, §4.4 ("deferred to v2 per the locked build order"), §6.2 |
| 2 | Design principle (engine starts simple, built to extend; jobs = first client of generic engine) | Captured | §0, §4.1 Source Registry, §6.2 (social/viral engines later) |
| 3 | Scoring model (problem-domain + post sanity weighted over tech-stack) | Captured | §1, §4.4, FR-6 (stack still an input, lower weight — matches intent's signal list) |
| 4 | Urgency: cross-posting footprint (same recruiter, multi-site) | Captured | §4.4, FR-7 ("per recruiter-role") |
| 5 | Urgency: repost history churn-vs-growth, sparse platforms | **Partial** | §4.4 description covers both churn + growth, but FR-7 consequences only test churn; "works on sparse platforms" constraint unrecorded → Gap 1 |
| 6 | Application loop: mark-as-applied | Captured | FR-4, FR-5 (idempotent, survives restarts) |
| 7 | Application loop: self-tuning feedback (track outcomes, steer next fetch) | **Partial** | §4.3 names it (v2) but no FRs; outcome taxonomy (response/interview/silence) missing → Gap 2 |
| 8 | Application loop: stop-and-rest (10 great matches/week, anti-burnout) | **Partial** | §4.3 description includes example threshold; no v2 FR; coupling to self-tuning captured ✓ → Gap 2 |
| 9 | Self-tuning filter + stop-signal = one feedback mechanism | Captured | §4.3 ("same feedback loop worn two ways"), intent insight #3 echoed |
| 10 | Tech: pipeline reuse (raw→extraction→cleaning→normalization→dedup→validation) | Captured | §3 Glossary, FR-2, §6.1, addendum Technical Direction |
| 11 | Tech: scrapy + playwright + LLM parsing | Captured | Addendum (Scrapy + Playwright); LLM parsing deferred to v2 (§6.2, FR-6 assumption) |
| 12 | Tech: real-time polling from Django scraper loop | Captured | §4.1 (30-min polling assumption), §6.2 (push → v1.5) |
| 13 | Tech: paged full list | Captured | FR-3 (25/page) |
| 14 | Tech: one-click notification → local detail page, Mark-as-applied next to external link | **Partial** | Deferral recorded (§6.2, v1.5) but the actionable-click spec is dropped, no deferred-requirement stub → Gap 3 |
| 15 | MVP scope (in: listings + add-new-site extensibility; cut: dashboards, tracking, feedback, LLM, notifications) | Captured | §6.1/§6.2 (tracking covered as dashboards/analytics + Application record) |

## Gaps

1. **FR-7 only tests the churn side.** The growth signal ("cluster of new related roles = growth") appears in the §4.4 description but has no testable consequence, and the intent's constraint that urgency derivation "works on sparse platforms" is unrecorded.
   *Fix:* Add a consequence to FR-7: "A cluster of new Listings sharing recruiter/company signature within a rolling window is flagged growth-possible" — and record sparse-platform tolerance as an assumption in §4.4 or §9.

2. **v2 feedback loop is described, not specified.** §4.3 has no FRs for self-tuning or stop-signal (contrast: §4.4 captured FR-6/FR-7 for its v2 features). The intent's outcome taxonomy (response / interview / silence) is missing entirely, and the deferred note field (FR-5, v1.5) is the natural home for outcome recording — that interplay is unaddressed.
   *Fix:* Add v2 FRs: record outcome per Application (response/interview/silence), steer next collection pass from outcome history, and emit stop signal at a configurable applied-great-matches/week threshold. Cross-reference the v1.5 note field as the outcome-input mechanism.

3. **One-click notification behavior dropped at deferral.** Intent specifies the notification's click action (opens local detail page with Mark-as-applied beside the external link); §6.2 defers notifications to v1.5 without preserving that spec anywhere.
   *Fix:* Add a v1.5 requirement stub in §4 (or an Open Question) capturing: notification click opens the local Listing detail with Mark-as-applied adjacent to the external link, per FR-4 layout.

4. **Version label inconsistency.** Glossary labels Interest Score "v1.5+ feature" while §4.4, §6.2, and §9 consistently call scoring v2.
   *Fix:* Change glossary to "v2 feature" for consistency with §4.4/§6.2.

## Non-issues checked
- Intent insight #1 (urgency = queries over persistent engine data) → FR-7 "using only data the engine already persists" ✓
- Intent insight #2 (scoring is the product) → §1 vision, §6.2 ✓
- Intent insight #4 (engine generic, repurposable) → §6.2 ✓
- LinkedIn cross-posting dedup edge → §4.1 assumption ✓