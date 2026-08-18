# PRD Quality Review — Job Hunt Aggregator

## Overall verdict

This is a genuinely good PRD for its stakes: a coherent thesis (judgment over coverage) drives a correctly sequenced scope, every v1 FR carries testable consequences, and the addendum's failure-point research is the kind of honest trade-off surfacing most PRDs lack. The risk concentrates in the v1 collection layer — the launch-source set is asserted in §6.1 while Open Questions 1–2 question those exact sources, and no fallback is defined if both drop; until Akram resolves those two questions, downstream stories for FR-1/FR-2/FR-6 build on unsettled ground. Catch-up behavior after downtime and a handful of undefined detail-view/score specifics round out the gaps; none of them threaten the PRD's overall shape.

## Decision-readiness — adequate

The PRD makes real decisions and names what was given up: the build order is "locked direction from the brainstorming session" (§0), Interest Scoring is "deliberately weighted over tech-stack overlap (decision from brainstorming)" (§4.4), and the one `[NOTE FOR PM]` sits at a genuine tension — the deferred note field is "emotionally load-bearing" (§6.2). The addendum does the heavy lifting well: the LinkedIn/Google failure-point research ("account ban is the distinctive risk", "silent failures (empty results, not errors)") is exactly the honest surfacing the rubric asks for. But the PRD asserts and questions the same scope item in two places, and one question isn't really open.

### Findings
- **[high]** Launch-source set asserted vs. questioned (§6.1 vs. §8 OQ1/OQ2) — §6.1 states "3 sources at launch: LinkedIn Jobs, Google Jobs, one Algerian board" as flat MVP scope while OQ1 asks whether "v1 LinkedIn scraping via a dedicated (non-primary) account, or deferred" and OQ2 asks to "confirm Google is a v1 source at all given fragility." The PRD's own addendum rates LinkedIn at "~95% block" with permanent account bans. A decision-maker cannot reconcile these, and downstream automation will default to the §6.1 assertion — FR-1/FR-2 stories could lock in scrapers for sources the owner hasn't committed to. *Fix:* convert the §6.1 source list into a decision record resolved against OQ1/OQ2, with a named fallback set.
- **[medium]** Scraper implementation choice lives only in the addendum — "JobSpy is the strongest reuse candidate for v1 LinkedIn/Google sources" (addendum, Options Considered) materially shapes FR-1/FR-2 and the architecture work, yet the PRD body's §6.1 stack line (Django API + scrapers, Next.js) never surfaces the scrape-layer decision. *Fix:* add an Open Question or decision line in the body referencing the addendum verdict.
- **[low]** OQ4 is not an open question (§8) — "confirm the v1 Keyword Set is the manual-process list … plus any additions" is a confirmation request with no alternatives attached. *Fix:* state the manual-process list as the v1 default and treat additions as change requests.

## Substance over theater — strong

No persona theater (one named user who drives every decision), no NFR boilerplate (the PRD has no generic "scalable/secure/reliable" section at all), and the Vision is product-specific: "the three-stop manual search routine (job boards → Google with time filters → Facebook groups + LinkedIn)". The one smell is an echo of a productized narrative in the out-of-scope list.

### Findings
- **[low]** "Social-traffic and viral-product engines (later; proof the engine is generic)" (§6.2) — for a single-user local tool, "proof the engine is generic" is a rationale that belongs to a different product. The only line that reads as template furniture. *Fix:* drop it or reword to "engine capabilities left unexercised."

## Strategic coherence — strong

The thesis — "The tool's edge is judgment" (§1) — is carried through the scope: engine first (FR-1/FR-2), application loop as the memory seed (FR-5), judgment and feedback deferred "so architecture accommodates them" (§4.4). Prioritization follows the thesis, not convenience: Interest Scoring is out of MVP because "the engine must exist first" (§6.2). SM-C1 is a genuine counter-metric ("a bigger list that buries quality is failure; the goal is curation, not coverage") — not a DAU-style activity metric. Two minor disconnects between the journeys and their specs.

### Findings
- **[low]** UJ-1 promises a sweep view the FRs don't spec — the journey opens with "every new posting since yesterday," but §4.2 defines the main screen as "a paged full list of Listings, newest first" and the "new" bucket appears only inside an FR-3 consequence. The JTBD ("Never miss the 24-hour window", §2.1) has no view dedicated to it. *Fix:* state whether the new-bucket is a default filter or a distinct view in §4.2.
- **[low]** SM-2 has no measured baseline — "Median morning sweep time drops from multi-site rounds to one session under 15 minutes" (§7) implies a before-number that is never taken; "drops" is unverifiable as written. *Fix:* add a one-line baseline measurement step, or restate as an absolute target.

## Done-ness clarity — adequate

Every FR carries testable consequences, and they are mostly crisp: dedup by "normalized title+company [plus URL host]" (FR-2), "re-marking is idempotent" (FR-5), signals "derive from engine history alone" (FR-7). No "gracefully"/"reasonable"/"user-friendly" language. The gaps are at the edges: what happens after downtime, and two underspecified v1/v2 outputs.

### Findings
- **[medium]** Catch-up/backfill after downtime is undefined — JTBD #4 is "Never miss the 24-hour window on a fresh posting" (§2.1) and collection polls every 30 minutes (§4.1), but no consequence covers the machine being off for a day: are missed polls backfilled, and in what order does the "new" list fill in? The core value prop is unsecured by any FR. *Fix:* add an FR-2 consequence or an explicit assumption for backfill/ordering after downtime.
- **[low]** FR-4's detail view content is undefined — "see all stored data" plus "the full record, the signals, and the link to the original posting" (§4.2); "the signals" is a v2 concept (FR-7) that doesn't exist in v1. *Fix:* enumerate the v1 detail-view fields and drop "the signals" until v2.
- **[low]** FR-6's score is unspecified as a quantity — "weighted combination of problem-domain overlap and post sanity" with no range or scale; since v2 is captured "so architecture accommodates them" (§4.4), architecture needs a defined output. *Fix:* pin a score range (e.g., 0–100) in the v2 description.

## Scope honesty — adequate

Non-Goals are real and load-bearing (§5), Out-of-Scope items carry reasons ("LLM-based parsing (v2; rule-based pipeline first)"), and the assumptions are tagged inline and indexed. The honest failure-point research is the strongest part of the document. The weakness is the fallback chain: when the research questions both primary sources, the PRD never states what v1 becomes.

### Findings
- **[medium]** No stated fallback if LinkedIn and Google both drop — OQ1 names "Google Jobs + boards first" as the fallback, then OQ2 doubts Google itself ("confirm Google is a v1 source at all"); the consequence for §6.1's "3 sources at launch" (one Algerian board left) is never discussed. The registry is the extension path, so a shrink may be tolerable — but it should be said, not inferred. *Fix:* define a minimum viable source set (e.g., "v1 launches with ≥1 live source; registry absorbs replacements").
- **[low]** Assumption index drift on dedup — inline §4.1 says "LinkedIn cross-posts may need v1.5 rules" while the index entry (§9) says "cross-platform cross-posting rules land with Urgency Signals"; two different landing points for the same caveat. *Fix:* align the wording in both places.

## Downstream usability — strong

Glossary terms are used consistently across FRs, UJs, and SM definitions; FR-1–FR-8 and UJ-1/2 are contiguous and unique; "Realizes UJ-1/UJ-2" cross-references resolve; both UJs have a named protagonist (Akram); SM-1 explicitly maps to "FR-1–FR-5". Sections read standalone. One lowercase drift and one dangling reference.

### Findings
- **[low]** "the signals" in §4.2 is a Glossary-less lowercase reference to a v2 concept inside a v1 screen description; story creation could add a signals panel to the v1 detail view. *Fix:* replace with "urgency signals (v2)" or remove for v1.
- **[low]** §4.4 cites "decision from brainstorming" without the path that §0 gives for the brainstorming doc (`_bmad-output/brainstorming/brainstorm-job-hunt-aggregator-2026-08-18/brainstorm-intent.md`). *Fix:* repeat the path at first mention in §4.4.

## Shape fit — strong

The shape matches the product: a personal, single-operator tool with a meaningful UX, formalized at exactly the level its downstream (architecture → epics/stories) needs. Two UJs with named protagonists is the right density — not the five-persona theater of a consumer PRD, and not an under-formalized capability list. The addendum's landscape research (build-vs-buy verdict, reuse candidates) is appropriate supporting depth. No findings.

## Mechanical notes

- **Title drift:** front matter says `title: Job Hunt Aggregator` and the H1 adds "*Working title — confirm.*" while the folder and PRD filename say "Job Hunt Mangement System" (including the "Mangement" typo). The unsettled name is acknowledged, but downstream artifacts will inherit one of three spellings. *Fix:* pick the canonical name before story creation.
- **Assumptions roundtrip:** all 10 inline `[ASSUMPTION]` tags appear in the §9 index, and all index entries appear inline. One wording drift (dedup landing point, see §5 finding).
- **ID continuity:** FR-1–FR-8, UJ-1/2, SM-1/2 contiguous and unique; SM-C1's counter-metric ID is nonstandard but harmless; all section references in the index (§2.3, §4.1–§4.4, §6.1) resolve.
- **Required sections:** all present for the stakes (§0–§9 plus addendum). No UX/performance/security section exists, which is correct for a localhost single-user app — absence of NFR theater is a feature here.