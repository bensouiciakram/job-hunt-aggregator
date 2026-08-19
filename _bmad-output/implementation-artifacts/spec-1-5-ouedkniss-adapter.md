---
title: 'Story 1.5: Adapter ouedkniss-jobs (GraphQL API)'
type: 'feature'
created: '2026-08-18'
status: 'done'
review_loop_iteration: 0
context:
  - _bmad-output/implementation-artifacts/epic-1-context.md
  - _bmad-output/implementation-artifacts/spec-1-3-collection-pipeline.md
  - _bmad-output/implementation-artifacts/spec-1-4-collector-worker.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Only a stub google-jobs adapter exists; the ouedkniss-jobs Source registered in Story 1.2 collects nothing. Users cannot see Algerian job postings from Ouedkniss.

**Approach:** Implement the `ouedkniss-jobs` adapter over the **public ouedkniss GraphQL API** (`https://api.ouedkniss.com/graphql`) — the same endpoint the site's own SPA consumes. **Deviation from the planning-time "Scrapy" tool choice, recorded here because it is fact:** ouedkniss.com is a client-rendered SPA (verified 2026-08-18: the server HTML is an empty `#app` shell; data is fetched client-side via GraphQL). An HTML/Scrapy scraper would harvest an empty page; the GraphQL API returns the SPA's own structured JSON. No HTML parsing is needed (JSON only, `requests` already installed). Scrapy remains reserved for any future server-rendered target.

## Boundaries & Constraints

**Always:**
- SourcePort contract (AD-1, frozen Story 1.2): `fetch(keywords) -> raw items`, `parse(raw) -> canonical dicts` with keys `title, company, url, published_at, keywords, raw_snapshot` (the Story 1.3 repository contract, exactly six keys). `fetch` raises on API failure; never returns partial garbage silently.
- Discovery ground truth (public scraper project, verified 2026-08-18): `SearchQuery` operation posts `{operationName:"SearchQuery", variables:{q, filter:{categorySlug, origin:null, connected:false, delivery:null, regionIds:[], cityIds:[], priceRange:[null,null], exchange:null, hasPictures:false, hasPrice:false, priceUnit:null, fields:[], page, orderByField:{field:"REFRESHED_AT"}, count}}, query:...}` → `search.announcements.data[].id` + `paginatorInfo`. Per-item details via `AnnouncementGet` (`announcementDetails(id)`: `reference, title, description, pricePreview, priceUnit, createdAt: refreshedAt, specs, cities{name}, user{displayName}, store{name}, slug`).
- **Search results must be enriched with detail fields in the SearchQuery itself** (id, title, slug, refreshedAt/createdAt, user/store, cities) — the implementer MUST verify the exact response shape with ONE live probe (network is available during development) and record it as a hermetic test fixture in `backend/collector/tests/fixtures/`. If the search response genuinely lacks detail fields, fall back to per-id `AnnouncementGet` (mini shape) for each collected id — bounded by the sample cap.
- One `SearchQuery` per keyword (Keyword Set honored), `q=<keyword>`; results deduplicated by id across keywords.
- Hard sample cap: at most 50 items per fetch (same convention as `test_fetch`); `count: 50` in the query.
- `categorySlug: "emploi"` fixed (jobs section). `orderByField: {field: "REFRESHED_AT"}`.
- HTTP: `requests.post`, timeout=30, realistic browser-ish User-Agent (same convention as test_fetch). Host is fixed `api.ouedkniss.com` (no user-supplied URL → no SSRF surface).
- Canonical mapping: `title` ← title; `company` ← user.displayName or store.name, empty string if absent; `url` ← absolute listing URL constructed from response fields (exact format verified live at implement time, e.g. `https://www.ouedkniss.com/{slug}` or `/{category-slug}/{id}` — pin whichever the SPA's Show route uses, and document it in the adapter docstring); `published_at` ← createdAt/refreshedAt ISO string (pipeline normalizes; absent → None); `keywords` ← the keyword that produced the item; `raw_snapshot` ← the raw item dict (pipeline caps at 2048).
- Adapter is pure-ish: no DB access, no Django models (AD-1).

**Ask First:** (none)

**Never:**
- No HTML scraping of the SPA shell, no Scrapy dependency, no headless browser for ouedkniss (Playwright is reserved for facebook-groups, Story 1.7).
- No changes to `collect_source`, the pipeline, or the repository (frozen Stories 1.3).
- No live network calls in tests — all tests hermetic against fixtures.
- No removal or modification of the google-jobs stub (Story 1.6 replaces it).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| OK_SEARCH | fixture search response with detail fields | parse yields canonical items with all six keys | n/a |
| KEYWORD_MULTI | config keywords = [k1, k2] | exactly two SearchQuery calls, q=k1 then q=k2; id-deduped across keywords | per-keyword failure logged via raised AdapterError (whole fetch fails — collect_source logs stage 'fetch') |
| SAMPLE_CAP | >50 unique ids across keywords | fetch returns at most 50 items | truncation is silent (documented), never a partial error |
| NO_COMPANY | item without user/store | company = '' | n/a |
| API_ERROR | HTTP 500 / network error / non-JSON / GraphQL errors key | adapter raises (SourcePort contract) | collect_source FetchLog stage 'fetch', ok=False |
| N1_FALLBACK | search response lacks detail fields | per-id AnnouncementGet (mini) for each id, bounded by cap | a failed detail call skips that id silently (raw item logged) |
| URL_SHAPE | response has slug vs category+id | url pinned to the live-verified format, absolute https | missing slug/id → item skipped |
| PUBLISHED_ABSENT | no createdAt/refreshedAt | published_at = None (pipeline lenient) | n/a |

</frozen-after-approval>

## Code Map

- `backend/collector/ports.py` -- `SourcePort` abstract contract (fetch/parse), frozen Story 1.2.
- `backend/collector/__init__.py` -- registry; google-jobs stub lives here (untouched until Story 1.6).
- `backend/collector/test_fetch.py` -- the 2048 `MAX_RAW_SNAPSHOT`, UA/timeout conventions to mirror.
- `backend/collector/collect.py`, `pipeline/*.py`, `repository.py` -- frozen; the adapter plugs into them.
- New: `backend/collector/adapters/__init__.py`, `backend/collector/adapters/ouedkniss_jobs.py`, `backend/collector/tests/fixtures/` (hermetic fixture JSON).

## Tasks & Acceptance

**Execution:**
- [ ] `backend/collector/adapters/ouedkniss_jobs.py` -- `OuedknissJobsAdapter(SourcePort)`: `fetch(keywords)` (one SearchQuery per keyword, count 50, page 1, REFRESHED_AT, 'emploi', enrich-with-details query verified live; id-dedupe; cap 50; raise on API/HTTP/JSON/GraphQL-errors; UA + timeout 30) and `parse(raw)` (canonical six-key mapping per the matrix; URL format pinned from live verification and documented) -- AD-1 contract, sample cap, keyword-set honoring
- [ ] `backend/collector/adapters/__init__.py` -- package init; adapter imported (no side effects at import beyond class availability)
- [ ] `backend/collector/__init__.py` -- `register_adapter('ouedkniss-jobs', OuedknissJobsAdapter)` alongside the google-jobs stub -- registry wiring (stub untouched)
- [ ] `backend/collector/tests/fixtures/search_response.json` (+ `detail_response.json` if the N1 fallback is needed) -- recorded from the ONE live probe, not hand-invented -- hermetic ground truth
- [ ] `backend/collector/tests.py` (extend) -- OK_SEARCH, KEYWORD_MULTI (call count + dedupe), SAMPLE_CAP, NO_COMPANY, API_ERROR (500 / network / GraphQL errors key → raises), N1_FALLBACK (if applicable), URL_SHAPE, PUBLISHED_ABSENT, parse-key completeness (exactly six keys), and a full-stack test: registered source + collect_source with a mocked adapter fetch → FetchLog ok=True and Listings stored -- matrix audit + AD-1 end-to-end

**Acceptance Criteria:**
- Given a registered ouedkniss-jobs Source, when the collector polls it, then postings from the ouedkniss jobs section are stored.
- And search results land in the listing store with job title, company, posting URL, posted date, and raw snapshot.

## Spec Change Log

(Append-only; empty until first review loopback.)

### 2026-08-19 — implement-time ratifications (review loopback, human-approved)

- **(a) categorySlug:** the spec-era `emploi` slug returns 0 results (verified live); the working jobs slug is `offres_demandes_emploi` ("عروض و طلبات العمل", mega-menu category id 765). Pinned in `CATEGORY_SLUG`.
- **(b) N1_FALLBACK:** N/A — the live probe proved SearchQuery carries the detail fields (id, title, slug, refreshedAt, user/store, cities); no per-id `AnnouncementGet` fallback is needed (matrix row retired).
- **(c) URL format:** pinned from the SPA Show route (verified live): `https://www.ouedkniss.com/{slug}-d{id}`.
- **(d) Cap semantics:** one SearchQuery per keyword ALWAYS — the 50-item cap never short-circuits the keyword loop; the final output is truncated to 50 items, keeping first-occurrence order.
- **(e) NO_COMPANY:** items with `company=''` are dropped by the frozen validate stage ('company is required') — accepted, documented here.

## Suggested Review Order

**Adapter contract** — fetch/parse, failure classes, cap semantics, dedupe, guards
- [`ouedkniss_jobs.py:1`](../../backend/collector/adapters/ouedkniss_jobs.py#L1)

**Registry wiring** — production registration row
- [`__init__.py:1`](../../backend/collector/__init__.py#L1)

**Ground truth** — recorded probe fixture
- [`search_response.json:1`](../../backend/collector/tests/fixtures/search_response.json#L1)

**Tests** — hermetic transport, full-stack AC, error classes, cap boundaries, keyword edges, Arabic/hostile-keyword round-trips
  [`tests.py:1`](../../backend/collector/tests.py#L1)

## Design Notes

- **Scrapy superseded by fact:** ouedkniss is a client-rendered SPA; its own data plane is `api.ouedkniss.com/graphql`. The adapter targets that public endpoint with the site's own query shape (grounded in the public `abdelhak-k/OuedKniss-Scraper` project and verified live at implement time). Recorded deviation from the planning-time tool note "ouedkniss-jobs adapter (Scrapy)" — the AD-1 contract (fetch→raw, parse→canonical) is unchanged.
- **Enrich search, avoid N+1:** the SPA's search grid renders title/date/location from the search response itself, so SearchQuery should carry the detail fields. N+1 `AnnouncementGet` calls are the fallback only if the probe proves search results are id-only.
- **Company semantics:** ouedkniss sellers are individuals (user.displayName) or stores (store.name) — either becomes `company`; absent → '' (never 'None' strings; pipeline normalize handles the rest).
- **Freshness:** `refreshedAt` is the site's recency signal; mapped to `published_at` (ISO). If the probe shows it's an epoch or relative string, map accordingly and pin in the fixture.
- **Silent truncation at the cap is intentional** (same convention as test_fetch); drift in site shape is caught by the worker's stale-count/backfill signals over time (deferred-work entry).

## Verification

**Commands:**
- `uv run python manage.py check` -- expected: 0 issues
- `uv run python manage.py test` -- expected: all pass
- `uv run python manage.py makemigrations --check --dry-run` -- expected: "No changes detected"
- Fixture audit: `backend/collector/tests/fixtures/search_response.json` was recorded from a live probe (note the probe date in the fixture as a comment field `"_probe_date": "2026-08-18"`), not synthesized

**Manual checks (if no CLI):**
- No test imports `requests` against the live host (grep for `requests.post` in tests → only in adapter module).
- `collector/adapters/ouedkniss_jobs.py` contains no Django imports (AD-1 purity).