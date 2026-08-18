---
title: 'Story 1.2: Source registry with SourcePort'
type: 'feature'
created: '2026-08-18'
status: 'done'
baseline_commit: 23f442ccd0401fe1ea6cae96b446e7e0ced38087
review_loop_iteration: 0
context:
  - _bmad-output/implementation-artifacts/epic-1-context.md
  - _bmad-output/implementation-artifacts/spec-1-1-backend-foundation.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Sources can be stored (Story 1.1) but there is no contract for adapters, no way to resolve an adapter key to code, and no API to register sources or test whether a site's selector actually matches.

**Approach:** Define the `SourcePort` protocol (`fetch(keywords) → raw items; parse() → canonical field set`) and a code-first adapter registry in `backend/collector/`, plus a JSON API (`backend/api/`) exposing register / list / test-fetch for Sources with the AD-10 envelope. Test-fetch uses the generic FR-1 path — keyword-substituted URL template + CSS/XPath selector evaluated with parsel — returning a sample of raw items with the raw snapshot, or a selector-mismatch notice with the raw HTML when nothing matches.

## Boundaries & Constraints

**Always:**
- AD-1: adapters implement the SourcePort protocol and never touch the database; value harmonization stays in the pipeline (later story), not adapters.
- AD-10: every endpoint returns the envelope `{ok: true, data: ...}` or `{ok: false, error: ...}` as JSON; timestamps ISO-8601 UTC where present.
- Code-first adapter registry: `adapter_key` resolves to a Python adapter class via a registry; adding a site = one adapter module + registry row; reusing a registered adapter = registry row only, no code change (FR-1).
- `Source` model is NOT modified in this story (fields name/adapter_key/config already cover FR-1); config validated in the API/service layer.
- Config contract for the generic path: `url_pattern` containing the `{keywords}` placeholder, `listing_selector`, and a `keywords` list.
- Test-fetch failures (connection, HTTP error) return an error envelope and never crash the request (AD-6 spirit); no FetchLog writes in this story (collection owns them, Story 1.3).
- No real site adapters (ouedkniss/google/facebook) in this story — they land in 1.5–1.7. The registry, contract, and endpoints are verified with stub adapters and a stub fetcher in tests.

**Ask First:**
- Adding dependencies `requests` and `parsel` to the backend venv (required for the generic test-fetch path; parsel is Scrapy-compatible so Story 1.5 reuses it).

**Never:**
- No Listing writes, no collection scheduling, no worker, no auth, no pagination of the source list (tiny local dataset).
- No DRF dependency — the AD-10 envelope is the contract; plain `JsonResponse` views suffice for three endpoints.
- No schema migrations.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| REGISTER_OK | POST /api/sources/ {name, adapter_key, config} | 201 `{ok: true, data: {id, name, adapter_key, config}}` | n/a |
| REGISTER_DUP_NAME | POST with existing name | `{ok: false, error: "name already exists"}` 400 | validation error surfaced, no row created |
| REGISTER_BAD_CONFIG | url_pattern missing `{keywords}` placeholder or empty listing_selector | `{ok: false, error: ...}` 400 | per-field error message |
| UNKNOWN_ADAPTER | register/test-fetch with unregistered adapter_key | `{ok: false, error: "unknown adapter key: X"}` 400 | registry raises AdapterNotFound → mapped to envelope |
| TESTFETCH_OK | Source with valid selector; stub fetcher returns HTML with matches | `{ok: true, data: {sample: [...raw items...], raw_snapshot: <html>}}` | n/a |
| TESTFETCH_MISMATCH | selector matches nothing | `{ok: true, data: {sample: [], raw_snapshot: <html>, notice: "selector-mismatch"}}` | FR-1: raw HTML returned for tuning, HTTP 200 |
| TESTFETCH_FETCH_ERROR | stub fetcher raises ConnectionError | `{ok: false, error: "fetch failed: ..."}` | request completes without crash |

</frozen-after-approval>

## Code Map

- `backend/listings/models.py` -- `Source` (name unique, adapter_key, config JSON) exists from Story 1.1; READ-ONLY here.
- `backend/listings/apps.py` -- WAL signal; untouched this story.
- `backend/job_hunt_aggregator/urls.py` -- project root URLconf; add `path('api/', include('api.urls'))`.
- `backend/job_hunt_aggregator/settings.py` -- INSTALLED_APPS gains `api` (alphabetical placement: after `django.contrib.*`, before `listings`).
- `backend/collector/` -- NEW package (Structural Seed: `collector/ports.py`). Contains `ports.py` (SourcePort protocol + AdapterNotFound), `registry.py` (code-first key→class registry), `test_fetch.py` (generic fetch+selector service).
- `backend/api/` -- NEW Django app: `views.py` (register/list/test-fetch views), `urls.py` (`/sources/`, `/sources/<int:pk>/test-fetch/`).
- `_bmad-output/implementation-artifacts/spec-1-1-backend-foundation.md` -- continuity: model shapes, AD-2 pragmas, envelope conventions; its Code Map/Design Notes are the foundation this story builds on.
- Continuity from Story 1.1: `Source` model fields already match FR-1; Story 1.1's tests establish the test conventions (TestCase, `manage.py test`).

## Tasks & Acceptance

**Execution:**
- [x] `backend/collector/__init__.py` + `backend/collector/ports.py` -- `SourcePort` Protocol: `fetch(keywords: list[str]) -> RawItems`, `parse(raw_items) -> CanonicalFields`; `AdapterNotFound` exception -- AD-1 contract, FR-1 adapter reuse story
- [x] `backend/collector/registry.py` -- code-first registry: `register(key)` decorator + `get_adapter(key)`; unknown key raises `AdapterNotFound` -- FR-1 "new site type = one module + registry row"
- [x] `backend/collector/test_fetch.py` -- `run_test_fetch(source, fetch=requests_get)` service: substitute keywords into `config.url_pattern`, fetch HTML, evaluate `config.listing_selector` via parsel, return `{sample, raw_snapshot}` or `{sample: [], notice: "selector-mismatch", raw_snapshot}`; fetch exceptions → `TestFetchError` -- FR-1 test-fetch + selector-mismatch ACs; injectable fetch for tests
- [x] `backend/api/` app scaffold (apps.py, __init__.py) + `backend/api/views.py` -- `register_source` (validate name unique, adapter_key known, config contract; csrf_exempt JSON views), `list_sources`, `test_fetch` (2048-safe raw snapshot); all AD-10 envelope -- FR-1 register/list/test-fetch ACs
- [x] `backend/api/urls.py` -- `POST /sources/`, `GET /sources/`, `POST /sources/<int:pk>/test-fetch/` -- AD-10 endpoints
- [x] `backend/job_hunt_aggregator/settings.py` + `backend/job_hunt_aggregator/urls.py` -- add `api` to INSTALLED_APPS; `path('api/', include('api.urls'))` -- routing
- [x] `backend/collector/tests.py` + `backend/api/tests.py` -- cover every matrix row (REGISTER_*, TESTFETCH_*, UNKNOWN_ADAPTER) with stub adapters/fetcher; assert envelope shape exactly -- matrix audit + FR-1 ACs
- [x] `backend/` -- `uv pip install requests parsel` -- dependency for generic fetch + selector evaluation

**Acceptance Criteria:**
- Given the backend foundation, when a `SourcePort` protocol is defined (`fetch(keywords) → raw items; parse() → canonical field set`), then adapters implement it and never touch the database.
- And the API exposes register/list/test-fetch endpoints for Sources with the AD-10 envelope.
- And a Source record stores name, adapter key, config (including the Keyword Set).
- And a test fetch on a Source returns a sample of raw items with the raw snapshot visible.
- And an invalid selector returns the raw HTML snapshot with a selector-mismatch notice (FR-1).

## Spec Change Log

(Append-only; empty until first review loopback.)

## Design Notes

- **parsel over BeautifulSoup/lxml:** parsel is Scrapy's selector API — the ouedkniss adapter (Story 1.5) runs on Scrapy, so the generic test-fetch path and the adapter path share selector syntax and gotchas; one library, one mental model.
- **Fetch injection:** `run_test_fetch(source, fetch=...)` defaults to `requests.get` but accepts a stub in tests — the matrix's fetch-error and mismatch rows run without network.
- **Envelope as the only contract:** plain `JsonResponse` views (no DRF). At three endpoints, serializer machinery adds a dependency without adding contract value; the envelope shape is asserted verbatim in tests so AD-10 can't drift.
- **csrf_exempt on API views:** the Next.js frontend (Story 1.8) posts from a different origin-less localhost context; a local single-user tool with no auth (NFR-1) accepts this. Admin stays CSRF-protected.

## Verification

**Commands:**
- `uv run python manage.py check` -- expected: 0 issues
- `uv run python manage.py test` -- expected: all tests pass (Story 1.1's 7 + new collector/api tests)
- `uv run python manage.py makemigrations --check --dry-run` -- expected: "No changes detected" (no schema change this story)
- API probe (server running): `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/sources/ -ContentType 'application/json' -Body '{"name":"demo","adapter_key":"google-jobs","config":{"url_pattern":"https://x/{keywords}","listing_selector":"div.job","keywords":["python"]}}'` -- expected: `{ok: True, data: {...}}`; then `GET /api/sources/` lists it

**Manual checks (if no CLI):**
- `GET /api/sources/` with an empty table returns `{ok: true, data: []}` — envelope shape on the empty path.
- Note: the POST probe is single-run per name — re-running against the same table needs a fresh name (or run after a `flush`).

## Suggested Review Order

**Adapter boundary — design intent (AD-1)**

- SourcePort protocol: fetch/parse contract, adapters never touch the DB
  [`ports.py:21`](../../backend/collector/ports.py#L21)

- Code-first registry: register/get_adapter, SourcePort conformance check, test isolation
  [`registry.py:12`](../../backend/collector/registry.py#L12)

- google-jobs placeholder stub (replaced by the real adapter in Story 1.6)
  [`__init__.py:11`](../../backend/collector/__init__.py#L11)

**Test-fetch service — the FR-1 path**

- Generic fetch: keyword substitution (brace-safe), timeout + UA, bounded sample, selector-mismatch notice
  [`test_fetch.py:27`](../../backend/collector/test_fetch.py#L27)

- Keyword encoding decisions and XPath/CSS dialect detection
  [`test_fetch.py:21`](../../backend/collector/test_fetch.py#L21)

**API — the AD-10 envelope**

- register/list/test-fetch views: envelope shapes, config contract validation, error mapping
  [`views.py:58`](../../backend/api/views.py#L58)

- Single sources/ route dispatching POST/GET
  [`urls.py:5`](../../backend/api/urls.py#L5)

**Tests & wiring**

- Collector tests: matrix rows via stubs, encoding edges, registry isolation
  [`tests.py:1`](../../backend/collector/tests.py#L1)

- API tests: envelope verbatim, 405s, length/type validation, google-jobs e2e
  [`tests.py:1`](../../backend/api/tests.py#L1)

- INSTALLED_APPS + URL wiring
  [`settings.py:33`](../../backend/job_hunt_aggregator/settings.py#L33)