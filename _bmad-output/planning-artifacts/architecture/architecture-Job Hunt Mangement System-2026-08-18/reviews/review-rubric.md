# Rubric-Walker Review — Architecture Spine (Job Hunt Aggregator)

- **Reviewer:** rubric-walker (architecture review gate)
- **Reviewed:** `ARCHITECTURE-SPINE.md` (created 2026-08-18, status draft)
- **Source of truth checked against:** final PRD (`prd.md`, 2026-08-18)
- **Date:** 2026-08-18
- **Overall verdict: CONDITIONAL PASS — adequate spine, one critical divergence left open and one dimension silently thin.**

---

## Verdict by Dimension

| # | Dimension | Verdict |
| --- | --- | --- |
| 1 | Divergence-point coverage (feature altitude: epics/stories stay coherent) | **Adequate** — 8 ADs fix most real points; misses FR-3 ordering/new-bucket and leaves FR-1's add-source flow open |
| 2 | AD Rule enforceability (Rule is enforceable and prevents stated divergence) | **Adequate** — most rules structurally testable; AD-1's DB-touch ban is convention-only, AD-7's mechanism unspecified |
| 3 | Deferred-section safety (nothing under Deferred lets two units diverge) | **Thin** — the Adapter-form OQ1 is parked under Deferred while directly contradicting FR-1; a unit could follow the PRD or the spine |
| 4 | Named tech is verified-current | **Adequate** — Django 6.1 / Next.js 16.x / React 19.x / Python 3.13 all current or actively supported; APScheduler needs a `<4` pin |
| 5 | Ratifies rather than contradicts existing reality (FR-1..FR-8 coverage) | **Thin** — FR-2..FR-8 ratified faithfully; FR-1's headline testable consequence is contradicted, not ratified |
| 6 | Altitude dimension completeness (all owned dimensions decided/deferred/OQ — esp. operational envelope) | **Adequate** — deployment envelope is decided; process-boundary/SQLite-concurrency and process supervision unowned |

---

## Findings (severity-ranked)

### F1 — CRITICAL — Deferred "Adapter form" contradicts FR-1's only testable consequence, and the spine passes the divergence down instead of fixing it

PRD FR-1 (testable): *"A Source added through the UI appears in the registry and is included in the next collection pass **without code changes**."* PRD §9 assumption: *"Sources are added via config-driven adapters, **not code edits**."* UJ-2 builds a **form** (site name, URL pattern with keyword placeholder, listing selector) with a test fetch.

The spine's Deferred section resolves the PRD's OQ1 the other way: *"Adapter form (PRD OQ1): registry row + adapter module (YAML-only configs deferred — the **code-first adapter** is the simpler v1 shape). [ASSUMPTION: user approves code-first adapters over config-file-only]"*. AD-1's Rule says *"Adding a site = new adapter + registry row; no core change"* — but a new adapter module **is** a code edit, so "no core change" is wordplay that cannot satisfy "without code changes."

The PRD explicitly deferred OQ1 to the architecture step (*"Owner: Akram; revisit at architecture step"*) — i.e., the spine was supposed to settle it. Instead it settled it **against** the ratified assumption and parked it under Deferred with an unapproved ASSUMPTION. A story team reading the PRD will build a UI-configured source; a team reading the spine will build a code-first adapter. This is precisely the divergence the spine exists to prevent. Fix: resolve OQ1 with the user and bind it in AD-1 before epics/stories are cut.

### F2 — HIGH — FR-3's "new since last visit" bucket and stable paging order have no governing AD (silent dimension)

PRD FR-3 consequences: *"Paging returns stable order (newest first) across page boundaries and days"* and *"Applied Listings … do not reappear in the 'new' bucket."* UJ-1's default view is *"every new posting since yesterday"*; §9 assumption *"v1 default sort is recency."*

No AD owns: what "new since last visit" means (visit timestamp? last-seen marker?), the sort key (published_at vs collected_at vs created_at), the pagination mechanism and tie-breaker, or page size (PRD assumption: 25/page — never ratified in Consistency Conventions). AD-7's *"freshness flag"* is age-based (24 h), not visit-based — a different concept. Two stories (listings API endpoint, list view) can diverge on ordering semantics, and FR-3's two testable consequences are ungoverned. Fix: one AD (or a Consistency Convention row) pinning sort key, bucket definition, page size, and stable-paging rule.

### F3 — MEDIUM — AD-2's "single writer" wording contradicts the two-process envelope; SQLite concurrency and worker supervision unowned

AD-2: *"The Django app is the only writer to SQLite; all writes go through Django ORM/services."* Diagram: *"SQLite (single writer)."* Deferred: *"deployment envelope = one Windows machine, two processes (Django server + collector worker)."* Two OS processes both writing through the ORM to one SQLite file are **two writers** — bulk pipeline upserts (AD-4/AD-6/AD-7) racing the API will hit *database is locked* on Windows unless WAL + busy timeout is pinned. The spine also never names how the worker is run/restarted (manage.py command? Task Scheduler? survives sleep — which matters for AD-7 backfill). The divergence risk: a worker story and an API story make different assumptions about DB locking. Fix: restate AD-2 as "one Django codebase owns schema/writes; two processes share SQLite via WAL/busy_timeout" and name the worker launch mechanism.

### F4 — MEDIUM — AD-1 vs AD-3: who normalizes is ambiguous (internal inconsistency)

AD-1: *"SourcePort: fetch(keywords) → raw items; parse() → **normalized field set**."* AD-3: *"Extraction, cleaning, and **normalization** are pure transforms (raw item → normalized fields)."* If parse() already yields "normalized field set," what does the pipeline's normalize stage do? An adapter author can push normalization into the adapter (and the ouedkniss adapter is described as *"Scrapy, JSON-LD/HTML"* parsing) while the pipeline author owns salary/location normalization (*"salary/location normalization per pipeline"* in Consistency Conventions). The boundary is undefined — a real place two units drift. Fix: AD-1 parse() → *raw field set* (site-shaped), pipeline normalize → canonical fields, or explicitly say adapters only extract.

### F5 — LOW — Tech stack verified current, but two precision notes (APScheduler pin; Python 3.14)

- Django **6.1** (released 2026-08-05 — current; 13 days old at spine date; supports Python 3.12–3.14). ✓
- Next.js **16.x** (16.2.x current), React **19.x** (19.2). ✓
- Python **3.13** — still actively maintained (3.13.15), though 3.14.7 is current stable; acceptable but the newest release exists. ✓ with note.
- APScheduler: stable line is **3.11.3** (2026-06-28); **4.0 is still pre-release** (4.0.0a6). Spine's *"pin at install"* is too vague here — it must be `apscheduler<4`, and AD-7's backfill promise interacts with APScheduler's default `misfire_grace_time` (≈1 s: a sleeping Windows machine skips rather than catches up unless grace time is raised and `coalesce=True`). Pin the constraint and state whether backfill is custom or misfire-based, or AD-7's *"backfills missed polls"* is unenforceable as written.

### F6 — LOW — Minor ratification gaps against PRD assumptions

- AD-7 hard-codes *"every 30 minutes"*; PRD says *"polling interval 30 minutes, **configurable**"* — configurability not ratified.
- Page size 25 (PRD §9) not ratified anywhere (ties to F2).
- FR-7's third consequence (*"A company posting a cluster of new, related roles yields a growth-possible flag"*) has no data hook in AD-8 (footprint + deletion only); AD-8's *"queries over this data"* covers it loosely at best.

---

## Per-Checklist Detail

### 1. Divergence points fixed; none missed (feature altitude)
Fixed well: extension-vs-core-edit (AD-1), two-writer schema drift (AD-2), pipeline coupling (AD-3), duplicate Listings / re-collection (AD-4), double-apply (AD-5), broken-source halting (AD-6), missed polls / 24-h window (AD-7), second v2 pipeline (AD-8). Missed: FR-3 ordering/bucket semantics (F2), FR-1 source-add flow (F1, punted), adapter/pipeline normalization boundary (F4).

### 2. AD Rule enforceability
- AD-4/AD-5: enforceable (dedup key + DB unique constraint on listing_id; idempotent upsert is testable). **Strong.**
- AD-3: enforceable (purity by construction; repository interface named). **Strong.**
- AD-2: enforceable at the API boundary, but "single writer" misstates the two-process reality (F3). **Adequate.**
- AD-1: "may not touch the DB" is convention-enforced (adapters live inside the Django process; nothing structural stops an import) — code-review-only. **Adequate.**
- AD-7: behavior testable, mechanism unspecified, APScheduler misfire defaults work against it (F5). **Adequate.**

### 3. Deferred-section safety
Scoring/notifications/LinkedIn/auth/Postgres/dashboards are all safely deferred (data hooks exist via AD-5 outcome, AD-8 history, AD-4 raw snapshot). **One exception:** Adapter form OQ1 (F1) — parked in Deferred while contradicting FR-1; two units can diverge on it today.

### 4. Named tech verified-current
All verified (see F5): Django 6.1 ✓, Next.js 16.x ✓, React 19.x ✓, Python 3.13 ✓ (3.14 exists), SQLite bundled ✓, JobSpy/Scrapy/Playwright "pin at install" ✓, APScheduler must pin `<4` — not stated.

### 5. Ratification of PRD reality (FR-1..FR-8)
- FR-1 ✗ — contradicted (F1); test-fetch is partially covered via FetchLog + *"raw snapshot for selector repair"* (AD-6).
- FR-2 ✓ — AD-3/AD-4/AD-6/AD-7/AD-8 map to every FR-2 consequence.
- FR-3 ✗ — partially (F2: paging stability and new-bucket unowned).
- FR-4 ✓ — AD-2/AD-5 cover detail view + one-click apply.
- FR-5 ✓ — AD-5 (unique Application, idempotent; *"Applications survive restarts"* covered by SQLite persistence).
- FR-6 ✓ — deferred with data captured (keywords + outcomes).
- FR-7 ✓ — AD-8 (with F6 caveat on growth flag).
- FR-8 ✓ — AD-5 nullable outcome field; *"no migration"* hook.
- PRD source list (Google Jobs JSON-LD, ouedkniss, Facebook SERP workaround), dedup key (title+company+URL host), localhost/no-auth all ratified faithfully.

### 6. Altitude dimension completeness (esp. operational/environmental)
Decided: deployment = one Windows machine, two processes; localhost, no auth, no hosting; SQLite; config = registry rows + settings.py; FetchLog error envelope; UTC ISO-8601; UUID listing_id. **Silent/unowned:** SQLite concurrency across the two processes (F3), worker launch/restart/sleep behavior (F3), visit-based bucket (F2, product dimension). Everything else at this altitude is decided or deferred.

---

## Bottom Line

The spine is compact, unusually good at pre-committing v2 data hooks (AD-5 outcome field, AD-8 history), and ratifies FR-2/4/5/6/8 faithfully. It cannot pass the gate cleanly while (a) FR-1's add-source flow is resolved *against* the ratified PRD and parked as an unapproved assumption (F1, critical), and (b) FR-3's ordering/bucket semantics are a silent dimension (F2, high). Fix F1 and F2 (one user decision + one small AD), tighten AD-2's writer wording and the APScheduler pin (F3/F5), and the spine is strong.