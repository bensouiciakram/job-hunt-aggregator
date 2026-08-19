---
title: 'Story 1.6: Adapter google-jobs (JobSpy)'
type: 'feature'
created: '2026-08-19'
status: 'done'
review_loop_iteration: 0
context:
  - _bmad-output/implementation-artifacts/epic-1-context.md
  - _bmad-output/implementation-artifacts/spec-1-3-collection-pipeline.md
  - _bmad-output/implementation-artifacts/spec-1-5-ouedkniss-adapter.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The `google-jobs` Source registered in Story 1.2 resolves to a placeholder stub that raises `AdapterNotFound`-style "not implemented" at fetch time — the primary job source collects nothing.

**Approach:** Replace the stub with a real `google-jobs` adapter over the **JobSpy** package (`site='google'`, sync `jobspy.jobs` API — Google Jobs is served via JobSpy's requests-based Google Jobs endpoints; no API key, no browser). One call per Keyword-Set entry, merged + deduped by job URL, hard sample cap 50 (same convention as test_fetch/ouedkniss). The stub class in `collector/__init__.py` is deleted; the adapter lives in `collector/adapters/google_jobs.py` and is registered as `google-jobs` alongside `ouedkniss-jobs`.

## Boundaries & Constraints

**Always:**
- SourcePort contract (AD-1): `fetch(keywords) -> raw items` (here: list of row dicts), `parse(raw) -> canonical six-key dicts` (`title, company, url, published_at, keywords, raw_snapshot`).
- JobSpy call shape (implementer verifies exact signature against the installed version): `jobspy.jobs(site='google', search_term=kw, location=<config or 'Algeria'>, results_wanted=<min(50, ...)>, hours_old=<24 or config>, country_indeed=<'algeria'> if required by the installed version)` — the google path supports `results_wanted` up to 50 per call; `hours_old` keeps the pass tight (freshness discipline, AD-7). If the installed JobSpy's google path ignores/unsupported params, drop them and record the fact in the Spec Change Log.
- JobSpy returns a **pandas DataFrame**. The adapter converts rows to plain dicts immediately — pandas types (Timestamp, NaT, NaN, numpy scalars) MUST be sanitized in `fetch` (Timestamp → ISO string or None; NaT/NaN → None; numpy int/float → python int/float/None) so `parse` and the pipeline only ever see JSON-safe values. `raw_snapshot` must be JSON-serializable (the frozen normalize stage json.dumps it).
- Canonical mapping: `title` ← `title`; `company` ← `company` (None → ''); `url` ← `job_url`; `published_at` ← `listed_time` or `posting_date` (ISO; None if absent/NaT); `keywords` ← `[keyword]` (list — the comma-split pitfall from Story 1.5 applies); `raw_snapshot` ← the sanitized row dict.
- Dedupe across keywords by `job_url` (str-normalized like Story 1.5's id dedupe); cap 50 output, first-occurrence order; ALL keywords always searched (Story 1.5 cap semantics ratified).
- Failure contract: network/API/JobSpy errors raise a labelled adapter error (keyword context) so collect_source logs stage 'fetch' ok=False; an empty DataFrame is a valid empty result, NOT an error.
- Hermetic tests: `jobspy.jobs` monkeypatched at the adapter module level; fixture DataFrame(s) built from the documented JobSpy schema (column names verified at implement time — at minimum `title, company, location, description, job_url, job_id, listed_time, posting_date`). One live probe of `jobspy.jobs(site='google', ...)` is allowed during development to pin the real output shape; if Google blocks it, say so and build the fixture from the documented schema instead (recorded in the Change Log).
- `jobspy` pinned in `backend/requirements.txt` (`jobspy>=0.5,<1` or the current stable line — implementer pins what they install).

**Ask First:** (none)

**Never:**
- No changes to `collect_source`, the pipeline, the repository, or the ouedkniss adapter (frozen).
- No headless browser in the adapter (JobSpy's google path is requests-based; if the installed JobSpy version routes google through a browser anyway, STOP and report — do not ship a browser-based adapter silently).
- No live network in tests.
- No removal of the `ouedkniss-jobs` registration.
- No API keys/secrets anywhere (JobSpy google needs none; if it demanded one, that would be a spec violation — report it).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| OK_ROWS | fixture df with 3 rows | fetch yields 3 sanitized row dicts; parse yields canonical six-key dicts | n/a |
| KEYWORD_MULTI | keywords [k1, k2] | two jobspy calls (search_term k1, k2); job_url dedupe across; cap 50 first-occurrence | per-keyword failure → labelled raise (whole fetch fails; collect_source logs) |
| EMPTY_RESULT | df with 0 rows (valid) | fetch returns [] (not an error) | n/a |
| API_ERROR | jobspy raises / HTTP error | labelled adapter error with keyword context | collect_source stage 'fetch', ok=False |
| TIMESTAMP_SANITIZE | listed_time Timestamp; posting_date NaT; NaN in company/url; numpy ints | ISO string / None; NaT/NaN → None; JSON-safe types only | n/a |
| NO_COMPANY | company None/NaN | company = '' | n/a |
| CAP_BOUNDARY | 51 unique urls across keywords | 50 returned, all keywords searched, first-occurrence wins | silent truncation (documented convention) |
| BLANK_KEYWORD | '' in keyword list | sent as search_term (upstream collect_source already rejects blanks — adapter stays permissive like ouedkniss) | n/a |

</frozen-after-approval>

## Code Map

- `backend/collector/ports.py` -- SourcePort contract (frozen).
- `backend/collector/__init__.py` -- the google-jobs STUB lives here (Story 1.2); it is deleted in this story and replaced by registration of the real adapter.
- `backend/collector/adapters/` -- ouedkniss adapter (frozen) + new `google_jobs.py`.
- `backend/requirements.txt` -- `jobspy` pinned.
- `backend/collector/tests/fixtures/` -- optional recorded probe output (CSV/JSON) if the live probe succeeds.

## Tasks & Acceptance

**Execution:**
- [ ] `uv pip install jobspy` in `backend\`; pin in `backend/requirements.txt` -- dependency
- [ ] `backend/collector/adapters/google_jobs.py` -- `GoogleJobsAdapter(SourcePort)`: `fetch(keywords)` (one `jobspy.jobs` call per keyword, `site='google'`, config `location` default 'Algeria', `hours_old` from config (default 24) or omitted if unsupported, `results_wanted` bounded; DataFrame → sanitized row-dict list; job_url dedupe; cap 50; labelled raise on failures, empty-df → []) and `parse(raw)` (six-key canonical mapping per matrix) -- AD-1 contract, stub replacement
- [ ] `backend/collector/__init__.py` -- delete the stub class and its registration; `register('google-jobs')(GoogleJobsAdapter)` -- the replacement
- [ ] `backend/collector/tests.py` (extend) -- OK_ROWS, KEYWORD_MULTI (call count + dedupe + cap), EMPTY_RESULT, API_ERROR (jobspy raise → labelled), TIMESTAMP_SANITIZE (Timestamp/NaT/NaN/numpy → JSON-safe), NO_COMPANY, CAP_BOUNDARY (51 → 50, all keywords searched), production registration test (`get_adapter('google-jobs') is GoogleJobsAdapter` without clear()), and one full-stack AC test (Source row adapter_key='google-jobs', fetch mocked → collect_source → FetchLog ok=True + Listings with source FK + raw_snapshot) -- matrix audit + AC
- [ ] `backend/README.md` -- note the google-jobs adapter is now live (JobSpy) -- operator-facing

**Acceptance Criteria:**
- Given a registered google-jobs Source, when the collector polls it, then Google Jobs postings are stored.
- And the placeholder stub is replaced with a working adapter (stub deleted, real registration in place).

## Suggested Review Order

**Adapter seam** — fetch/parse, sanitizer, labelled failures, hours_old guard, lazy import
- [`google_jobs.py:1`](../../backend/collector/adapters/google_jobs.py#L1)

**Registry** — stub deleted, production registration
- [`__init__.py:1`](../../backend/collector/__init__.py#L1)

**Fixture** — schema-grounded probe metadata, date-only date_posted
- [`google_jobs_probe.json:1`](../../backend/collector/tests/fixtures/google_jobs_probe.json#L1)

**Tests** — matrix rows, sanitizer zoo, JSON-serializability invariant, full-stack AC
  [`tests.py:1`](../../backend/collector/tests.py#L1)

## Spec Change Log

(Append-only; empty until first review loopback.)

### 2026-08-19 — implement-time ratifications (review loopback, human-approved)

- **(a) Probe outcome → fixture:** the live probe (`développeur`, Algeria, 5 wanted, 24h) succeeded but returned an empty DataFrame — Google served nothing for the window — so `google_jobs_probe.json` is built from the verified JobSpy 1.1.82 schema (`desired_order`, 34 columns) instead of recorded output.
- **(b) Package name:** the PyPI package is `python-jobspy` (import name `jobspy`); the bare `jobspy` name is an unrelated package. Pinned in `requirements.txt` as `python-jobspy>=1.1.82,<2`.
- **(c) API shape:** the installed version exposes `scrape_jobs(site_name='google', search_term, location, results_wanted, hours_old, ...)`, not the spec-era `jobspy.jobs(...)`.
- **(d) Posting-date column:** adopted column is `date_posted` (a `datetime.date` for Google); the spec-era `listed_time`/`posting_date` names do not exist in this version and are kept only as drift fallbacks.
- **(e) country_indeed:** omitted — the Google path never reads it, and this version's Country enum has no 'algeria' entry (passing one would raise ValueError before scraping).
- **(f) results_wanted cap:** JobSpy's google path caps `results_wanted` at 900; our 50 is the self-imposed MAX_SAMPLE convention (same as test_fetch/ouedkniss), not a JobSpy limit.

## Design Notes

- **JobSpy, not hand-rolled:** Google Jobs has no public API; JobSpy maintains the reverse-engineered requests path and a documented schema — the pragmatic choice the architecture already made (epic context: "google-jobs adapter (JobSpy)"). It is pinned in requirements.txt.
- **Sanitize at the seam:** pandas/numpy types must never cross into `parse` or the pipeline (JSON serialization in raw_snapshot would break on Timestamp/NaN). Sanitization happens in `fetch` so `parse` sees plain JSON-safe dicts — same seam discipline as ouedkniss.
- **hours_old for freshness:** Google Jobs lets us window the last 24h — this is the only adapter where time-windowing is native; it reinforces AD-7's freshness intent. Configurable per Source (default 24).
- **Stub deletion is the AC:** the Story 1.2 stub existed so the registry contract could be tested without a real adapter; Story 1.5's suite now proves the real-adapter pattern (hermetic transport, production registration test), so the stub can die.

## Verification

**Commands:**
- `uv run python manage.py check` -- expected: 0 issues
- `uv run python manage.py test` -- expected: all pass (148 + new)
- `uv run python manage.py makemigrations --check --dry-run` -- expected: "No changes detected"

**Manual checks (if no CLI):**
- No test calls live network (grep `jobspy` in tests → only the adapter module is patched).
- `collector/adapters/google_jobs.py` has no Django imports (AD-1 purity).
- The stub class name no longer exists anywhere in `backend/` (grep).