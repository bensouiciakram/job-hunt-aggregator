---
title: 'Story 1.3: Collection pipeline'
type: 'feature'
created: '2026-08-18'
status: 'done'
baseline_commit: 5036b204611cf23d1d144bced46607f27701906e
review_loop_iteration: 0
context:
  - _bmad-output/implementation-artifacts/epic-1-context.md
  - _bmad-output/implementation-artifacts/spec-1-2-source-registry.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Sources can be registered and test-fetched (Story 1.2), but nothing turns a successful fetch into persisted, deduplicated Listings — and a failing fetch has no error trail.

**Approach:** Build the collection pipeline per the Structural Seed (`collector/pipeline/`: extract, clean, normalize, dedupe, validate) plus a `ListingRepository` and a `collect_source(source)` orchestrator: resolve the adapter, fetch with the Keyword Set, run the pure stages, then persist via the repository — atomic idempotent upserts honoring AD-4 (content fields only; status/seen_sources/fingerprint never modified by collection), with every failure written to `FetchLog` (AD-6) so one bad source never stops others.

## Boundaries & Constraints

**Always:**
- Pipeline stages extract/clean/normalize are PURE functions (no DB access, no I/O); dedupe computes the fingerprint; only `ListingRepository` touches the DB (AD-1/AD-3).
- AD-4 upsert semantics, enforced by the repository API: `dedup_fingerprint` is computed once at ingestion (sha256 hex of `normalized title | normalized company | url host`, normalized = lowercase + stripped) and NEVER updated; upsert updates only content fields (title, company, url, published_at, keywords, raw_snapshot); `status` is never modified by collection; `seen_sources` is append-only (append the source key when missing, never replace or dedupe history).
- Short transactions: one atomic block per Listing upsert, not one big batch transaction (adversarial-review guidance on AD-2 write serialization).
- AD-6 failure isolation: any failure (fetch, stage, repository) writes `FetchLog {source, stage, ok: False, error}` and `collect_source` returns without raising; other sources are unaffected. A successful collection writes an `ok: True` FetchLog row.
- Canonical field set (AD-1): title, company, url, published_at (ISO-8601 UTC or None), keywords (list[str]), raw_snapshot.
- Item-level isolation: one invalid item in a batch is skipped with its own FetchLog entry; valid items still persist.
- `validate` requires title, company, and a http(s) url; invalid items fail validation (lenient `published_at`: unparseable → None).

**Ask First:** (none — all decisions below are internal implementation choices)

**Never:**
- No scheduling/worker (Story 1.4), no real adapters (Stories 1.5–1.7), no API/endpoint changes, no frontend.
- No schema migration: `Listing`/`FetchLog`/`Source` from Story 1.1 suffice — if a field is genuinely missing, HALT instead of migrating.
- No `status` transitions to "applied" (Epic 2 owns those) and no scoring (Epic 3).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| COLLECT_OK | stub adapter returns 3 valid raw items | 3 Listings persisted with fingerprints; FetchLog ok=True; content matches canonical fields | n/a |
| COLLECT_DUP | same items collected again | 0 new rows; content fields updated; `seen_sources` gained the key once (no duplicates); `status` untouched | n/a |
| COLLECT_FETCH_FAIL | adapter.fetch raises | FetchLog {ok: False, stage: "fetch", error}; no Listing writes; no exception escapes | isolated per AD-6 |
| COLLECT_BAD_ITEM | 1 invalid + 2 valid items | 2 persisted; FetchLog ok=False for stage "validate" with item error; others proceed | item-level isolation |
| STATUS_PRESERVED | existing Listing with status "applied" | upsert leaves "applied" intact | n/a |
| FINGERPRINT_STABLE | same listing as "Python Dev" vs "python dev", different company casing | identical fingerprint → deduped to one row | normalization before hashing |

</frozen-after-approval>

## Code Map

- `backend/collector/ports.py` -- `SourcePort` protocol + `RawItems`/`CanonicalFields`; adapter.parse already yields canonical-ish dicts.
- `backend/collector/registry.py` -- `get_adapter(key)`; raises `AdapterNotFound`.
- `backend/collector/__init__.py` -- `google-jobs` stub raising NotImplementedError on fetch (perfect natural failure-isolation fixture).
- `backend/listings/models.py` -- `Listing` (unique `dedup_fingerprint` max_length=64 — sha256 hex fits exactly), `FetchLog {source, stage, ok, error}`; READ-ONLY this story.
- `backend/collector/test_fetch.py` -- proves the parsel/requests patterns; the pipeline reuses none of it (pure), but its `TestFetchError` convention carries over.
- Story 1.2 continuity: test conventions (TestCase + stubs, registry `clear()` in setUp), deferred-work items "fingerprint format" + "FetchLog ok/error consistency" get resolved HERE.
- Structural Seed: `backend/collector/pipeline/` with `extract.py  clean.py  normalize.py  dedupe.py  validate.py`.

## Tasks & Acceptance

**Execution:**
- [ ] `backend/collector/pipeline/__init__.py` + `extract.py` -- pure stage: coerce raw items to dicts, pick canonical keys, tolerate extra keys -- AD-1 structure guarantee
- [ ] `backend/collector/pipeline/clean.py` -- pure stage: strip/collapse whitespace in title/company/url; drop empty string fields -- canonical text hygiene
- [ ] `backend/collector/pipeline/normalize.py` -- pure stage: published_at → ISO-8601 UTC or None (lenient); keywords coerced to list[str]; url host extraction helper -- AD-1 harmonization lives here, not adapters
- [ ] `backend/collector/pipeline/dedupe.py` -- `compute_fingerprint(title, company, url)` = sha256 hex of `t | c | host` (lowercased, stripped) + per-item fingerprint assignment -- AD-4 identity rule (resolves deferred "fingerprint format" item)
- [ ] `backend/collector/pipeline/validate.py` -- pure stage: title/company required, url http(s); returns item errors -- canonical completeness
- [ ] `backend/collector/repository.py` -- `ListingRepository.upsert(item)` with `transaction.atomic()` per listing: create (status NEW, seen_sources=[source_key]) or update content fields only + append source_key to seen_sources if missing; repository API cannot touch status/seen_sources/fingerprint -- AD-4 enforcement point
- [ ] `backend/collector/collect.py` -- `collect_source(source)`: get_adapter → fetch(keywords) → pipeline stages → repository upserts; failures → FetchLog (ok flag per result, stage named); never raises -- AD-6 + FR-2 collection loop
- [ ] `backend/collector/tests.py` (extend) -- cover every matrix row with stub adapters; assert seen_sources append-once, status preservation, fingerprint stability, FetchLog isolation, item-level skip -- matrix audit

**Acceptance Criteria:**
- Given a registered Source with a working adapter, when collection runs for that Source, then items pass extract → clean → normalize → dedupe → validate (pure stages) → repository.
- And a canonical field set is produced (title, company, url, published_at ISO-8601 UTC, keywords, raw_snapshot).
- And upsert is atomic: existing `dedup_fingerprint` updates only content fields; `status`, `seen_sources`, and the fingerprint itself are never modified by collection (AD-4).
- And failures are isolated: a malformed fetch writes a FetchLog `{source, stage, ok, error}` and does not stop other Sources (AD-6).

## Spec Change Log

(Append-only; empty until first review loopback.)

## Suggested Review Order

**Orchestration — AD-6 isolation**

- collect_source: never-raises guard, parse invocation, per-stage FetchLogs, ok-row semantics
  [`collect.py:1`](../../backend/collector/collect.py#L1)

**Persistence — AD-4 enforcement**

- ListingRepository.upsert: content-only update_fields, FK on create, published_at preservation, six-key contract
  [`repository.py:1`](../../backend/collector/repository.py#L1)

**Identity — fingerprint**

- dedupe: sha256 of escaped components (| → %7C, % → %25)
  [`dedupe.py:1`](../../backend/collector/pipeline/dedupe.py#L1)

**Pure stages**

- normalize (dates, keywords, raw_snapshot cap) · validate (hostname, lengths) · clean · extract
  [`normalize.py:1`](../../backend/collector/pipeline/normalize.py#L1)

**Tests**

- matrix rows + failure isolation + content convergence
  [`tests.py:1`](../../backend/collector/tests.py#L1)

## Design Notes

- **Why dedupe computes fingerprints, not the repository:** the hash must be stable across collection passes; keeping it in a pure stage makes it trivially testable and independent of DB state. `title | company | host` uses `|` separators so "a|b" + "c" never collides with "a" + "b|c".
- **Repository as the only writer:** views/adapters never import models directly for writes; `ListingRepository` exposes exactly the AD-4-safe surface, so the write-protection is enforced by API shape, not convention.
- **`seen_sources` append semantics:** appends `source_key` (Source.adapter_key — later a source name/id) only when absent, inside the same atomic block; ordering preserved, history never rewritten.
- **FetchLog stage names:** `fetch`, `extract`, `clean`, `normalize`, `dedupe`, `validate`, `persist` — free-form strings (resolves deferred "FetchLog consistency" item: ok=False rows carry error text; ok=True rows carry empty error).

## Verification

**Commands:**
- `uv run python manage.py check` -- expected: 0 issues
- `uv run python manage.py test` -- expected: all pass (Story 1.1 + 1.2 suites + new pipeline/repository/collect tests)
- `uv run python manage.py makemigrations --check --dry-run` -- expected: "No changes detected"
- Shell smoke: `uv run python manage.py shell` — register a stub adapter via the registry, create a Source row, run `collect_source(source)` twice, assert 2nd pass creates 0 new rows and `seen_sources` has the key exactly once

**Manual checks (if no CLI):**
- `collector/pipeline/*.py` contain no `import django` / model imports (purity), except nothing — pure stages import only stdlib + each other.