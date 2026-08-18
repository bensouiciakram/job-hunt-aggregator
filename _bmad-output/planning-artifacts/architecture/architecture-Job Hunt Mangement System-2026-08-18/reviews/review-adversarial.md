# Adversarial Review — Job Hunt Aggregator Architecture Spine

- **Reviewed:** `ARCHITECTURE-SPINE.md` (draft, 164 lines, 2026-08-18)
- **Method:** red team. For each hole, construct two concrete one-level-down units that each obey every AD to the letter, then show the collision.
- **Date:** 2026-08-18

## Verdict

**FAIL — do not build against this spine as-is.** The spine's two headline invariants (AD-2 single ownership, AD-4 idempotent upsert) are stated as principles but not encoded as mechanisms: no uniqueness constraint backs the dedup key, the upsert's field set and ownership are unbounded, and the API contract the frontend is forced through (AD-2) is never defined. Three collisions are CRITICAL — two owners of `Listing.status`, a check-then-insert dedup race, and a self-mutating dedup key — and four more are HIGH/MEDIUM. Seven holes total; each needs a new or tightened AD before FR-2/FR-3/FR-5 units start. The spine is fixable with ~4 new/tightened ADs, not a redesign.

---

## Collision Catalogue

### C1 — CRITICAL: Two owners of `Listing.status` (Worker-upsert × API-apply)

**Units:** `collector/pipeline/dedupe.py::upsert` (worker process) × `api/views.py::apply` (API process).

**ADs obeyed (quoted):**
- AD-4: "Canonical `Listing` entity (title, company, url, source, published_at, keywords, raw_snapshot, status). … Upsert is idempotent: re-fetching an existing key updates fields, never inserts."
- AD-5: "One `Application` per `Listing` …; marking applied is idempotent."
- AD-2: "The Django app is the only writer to SQLite" — both units are Django code, so both legitimately write.

**Collision:** AD-4 names `status` in the canonical field set and says the upsert "updates fields" with no exclusions. Unit A runs its AD-7 30-minute poll, re-fetches an *applied* listing, and updates "fields" — if `status` is in the set it clobbers "applied" back to "new". If Unit A instead excludes `status`, it has silently narrowed "updates fields", leaving AD-4 with two legal readings and Unit B unable to trust `Listing.status` vs deriving from `Application`. Either way the applied state has two owners and the frontend (AD-2, API-only) cannot disambiguate.

Same AD-4 field-set hole collides with AD-8: `seen_sources` "per Listing" — if the upsert overwrites it, the cross-source footprint (the entire "urgency signals for free" v2 bet) resets to one source on every poll and FR-7 degrades to noise.

**Hole:** AD-4 names a field set but no ownership or update policy per field.

**Fix (tighten AD-4):** split the canonical entity into upsert-owned fields (url, raw_snapshot, published_at, keywords, source, seen_sources) and API-owned/derived fields (status). `status` derived from Application existence or explicitly API-owned; `seen_sources` upsert semantics = union/merge, never overwrite.

---

### C2 — CRITICAL: Dedup race — two concurrent passes both insert (idempotency is serial-only)

**Units:** `worker.py` poll pass (30-min tick) × `worker.py` backfill pass ("After downtime, the next pass backfills missed polls").

**ADs obeyed (quoted):**
- AD-4: "Upsert is idempotent: re-fetching an existing key updates fields, never inserts."
- AD-7: "A collector worker polls all Sources every 30 minutes via APScheduler. After downtime, the next pass backfills missed polls…"
- AD-2: both write only via ORM.

**Collision:** nothing serializes the two passes. APScheduler misfire/coalescing policy is unspecified, and a slow facebook-groups Playwright fetch can exceed 30 minutes, so a backfill pass can start while a poll pass is still running. Both passes run dedupe on the same absent key: check → not found → insert. Two rows. AD-4's idempotency holds only under serial execution, which no AD guarantees. The headline invariant of the spine silently fails under load.

**Hole:** AD-4 never demands a uniqueness mechanism — compare AD-5, which *does* say "DB unique constraint on listing_id". The spine knew how to make idempotency real for Applications and didn't for Listings.

**Fix (tighten AD-4 + AD-7):** dedup key backed by a DB unique constraint; upsert implemented as create-with-IntegrityError-catch → update (or `INSERT … ON CONFLICT`); AD-7 adds a single-flight rule: one pass per Source at a time.

---

### C3 — HIGH: Adapter-parse × pipeline-normalize — two definitions of "normalized field set"

**Units:** `collector/adapters/google.py` (wraps JobSpy) × `collector/adapters/ouedkniss.py` (Scrapy).

**ADs obeyed (quoted):**
- AD-1: "Every Source is an adapter implementing `SourcePort: fetch(keywords) → raw items; parse() → normalized field set`" — no schema given.
- AD-3: "Extraction, cleaning, and normalization are pure transforms (raw item → normalized fields)" — no schema given.
- Conventions: "salary/location normalization per pipeline".

**Collision:** "normalized" is defined in two places with no shared schema, so each adapter author makes a locally-reasonable choice: Unit A (JobSpy) emits `published_at` as an epoch int and `salary` as a flat string; Unit B emits ISO-8601 strings and `salary` as `{min, max, currency}`. Both obey AD-1 to the letter. The pipeline's `normalize.py` — written against one shape because it cannot be written against both — crashes or mangles the other. Worse, AD-4's dedup key begins with `normalized(title)`; if the two adapters normalize differently ("Sr. Software Engineer" vs "Software Engineer, Sr."), the same role posted on both sites yields two keys and AD-8's cross-source footprint silently reports one source. v2's urgency bet dies quietly.

**Hole:** AD-1 names the seam but not the wire format; AD-3 names the transform but not the envelope it produces and consumes.

**Fix (new AD):** one versioned `NormalizedItem` envelope — exact field names, types, units, timestamp format (UTC datetime, parsed *in the adapter*, not the pipeline), salary shape, null policy — that `parse()` must emit and the pipeline must consume; pipeline normalize only fills gaps and cleans.

---

### C4 — HIGH: The frontend cannot be built compatibly — the API contract is unbound

**Units:** `frontend/` (Next.js) × `backend/api/` (JSON API).

**ADs obeyed (quoted):**
- AD-2: "The Next.js app reads and issues commands only via the JSON API."
- Conventions: "error envelope `{source, stage, ok, error}` in FetchLog"; "`listing_id` UUID".

**Collision:** AD-2 makes the API the *only* channel but never defines it: no endpoint list, no request/response shapes, no pagination, no status codes. Four concrete split interpretations, each fully AD-compliant:
1. **List:** Unit A expects DRF-style `{results: [...], next: null}`; Unit B returns a bare array → list page breaks.
2. **Apply:** Unit A POSTs `{listing_id}` in the body; Unit B reads a path parameter → 400/404.
3. **Re-apply:** both readings of AD-5's "marking applied is idempotent" are legal — Unit A treats 200-with-body as success; Unit B returns 409 → frontend renders an error for a legitimate repeat click; or Unit A treats 409 as "already applied" while Unit B returns 200 with the existing record.
4. **Detail:** does the payload nest the `application` object? Unspecified → the "Applied?" badge is wrong under one of the two readings.

**Hole:** AD-2 constrains the channel, not the contract.

**Fix (new AD):** an explicit API contract — endpoint list, request/response envelopes, pagination shape, status-code semantics including idempotent re-apply, and whether Application is nested in Listing detail. Cheap to write now; this is exactly the seam where two units build incompatibly.

---

### C5 — HIGH: Self-mutating dedup key — an idempotency hole with no concurrency at all

**Units:** `collector/pipeline/dedupe.py::upsert` × `api/views.py::apply` (same entity as C1, different failure mode).

**ADs obeyed (quoted):**
- AD-4: "Dedup key = normalized(title) + company + url host. Upsert is idempotent: re-fetching an existing key updates fields, never inserts."

**Collision:** the key is composed of three mutable, upsert-updated fields. Two failure modes:
1. A site re-posts with a tweaked title ("Software Engineer" → "Software Engineer (Remote)"): the key changes → the re-fetch *inserts* a new row instead of updating. Idempotency breaks with zero concurrency involved.
2. Two genuinely different listings — same title, same company, same host, different job ids (site reposted the role) — collapse to one key: the upsert overwrites row A's fields with row B's data and one real job (plus its applications) vanishes. And if "updates fields" includes `url` — itself a key input — the key mutates after update, so the *next* fetch computes yet another key and inserts a duplicate of the already-updated row.

**Hole:** AD-4 doesn't say which fields the upsert may overwrite (title? company? url — all are key inputs), nor how same-key collisions are resolved.

**Fix (tighten AD-4):** freeze key inputs — store the dedup key as an immutable hash column set at insert, never recomputed; upsert never overwrites key-input fields; define same-key-different-url resolution explicitly (most-recent-wins + history per AD-8, or widen the key with the site's job id).

---

### C6 — MEDIUM: Two processes, one SQLite file — a writer race the spine doesn't govern

**Units:** `worker.py` (collector process) × `api/` (Django server process).

**ADs obeyed (quoted):**
- AD-2: "The Django app is the only writer to SQLite; all writes go through Django ORM/services."
- Deferred: "deployment envelope = one Windows machine, two processes (Django server + collector worker)."

**Collision:** both units are Django code, so both are AD-2-compliant writers. The worker's upsert and the API's apply can hit the same Listing row simultaneously. SQLite grants one writer; nothing in the spine sets WAL mode, `busy_timeout`, or a retry policy, so the API's transaction fails with "database is locked" under a concurrent upsert, or the worker's batch transaction holds the lock while the frontend's apply times out. AD-2's "single owner" answers *who* writes, not *how writes are serialized* — and the word "single" will be read as sufficient, so no mechanism will be built.

**Fix (new AD):** write-concurrency policy — WAL mode, busy_timeout, short per-row transactions in the worker (no long batch transaction spanning many listings), retry-on-lock, optionally serializing the worker write phase via a per-source lock or single write queue.

---

### C7 — MEDIUM: Timestamp and FetchLog shape drift breaks freshness and "last fetch" state

**Units:** `collector/adapters/facebook_groups.py` (Playwright, SERP workaround — flakiest source) × `worker.py` freshness marking + `api/` fetch-status endpoint.

**ADs obeyed (quoted):**
- AD-7: "marks Listings older than 24 hours with a freshness flag" — no definition of how age is computed.
- AD-6: "malformed or empty fetches are logged as `FetchLog` entries" — no shape beyond the conventions row: "error envelope `{source, stage, ok, error}`"; "Timestamps UTC ISO-8601".

**Collision:** the convention says UTC ISO-8601 but raw items arrive site-native ("3 days ago", epoch ints, timezone-less strings); if `parse()` emits those raw (C3's hole again), the 24-hour comparison mis-orders or crashes on mixed formats. And the FetchLog envelope leaves `stage` free-form and `source` undefined (adapter key? registry name?). The frontend needs a deterministic "last fetch per source": if FetchLog is append-only, "last" is an order-by over a string timestamp column that may hold two different ISO renderings; if it's upserted-per-fetch, the success-row shape is unspecified. Two readings, both AD-compliant, one broken UI.

**Fix (fold into C3's envelope + tighten AD-6):** `published_at` coerced to UTC datetime inside the adapter's `parse()` (not the pipeline); FetchLog = one row per fetch attempt per source (success *and* failure), `source` = adapter key, `stage` from a fixed enum, ordering by auto-increment id, not timestamp string.

---

## Collision → AD change summary

| # | Severity | Unit pair | Change |
|---|---|---|---|
| C1 | CRITICAL | dedupe.upsert × api.apply | AD-4: split upsert-owned vs API-owned fields; status derived or API-owned; seen_sources = merge, never overwrite |
| C2 | CRITICAL | worker poll × worker backfill | AD-4: DB unique constraint on dedup key + IntegrityError-as-update; AD-7: single-flight per Source |
| C3 | HIGH | google adapter × ouedkniss adapter | New AD: versioned NormalizedItem envelope (fields, types, timestamp, salary shape, null policy) |
| C4 | HIGH | frontend × backend/api | New AD: API contract (endpoints, envelopes, pagination, codes, nested Application) |
| C5 | HIGH | dedupe.upsert × api.apply | AD-4: immutable key hash; key inputs frozen; same-key collision policy |
| C6 | MEDIUM | worker process × API process | New AD: SQLite WAL / busy_timeout / short transactions / retry-on-lock |
| C7 | MEDIUM | facebook adapter × worker/api | C3 envelope + AD-6: FetchLog one-row-per-attempt, stage enum, id-based ordering |

## What survives

AD-1's "adapters may not import each other or touch the DB" boundary and AD-6's per-source error isolation are sound. AD-2's direction (only Django writes) is right — it just lacks mechanism. AD-5 shows the spine can demand uniqueness when it wants to; AD-4 should borrow that rigor. All seven holes close with targeted AD edits, no redesign.