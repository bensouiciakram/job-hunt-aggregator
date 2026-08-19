---
title: 'Story 1.7: Adapter facebook-groups (Playwright)'
type: 'feature'
created: '2026-08-19'
status: 'done'
review_loop_iteration: 0
context:
  - _bmad-output/implementation-artifacts/epic-1-context.md
  - _bmad-output/implementation-artifacts/spec-1-3-collection-pipeline.md
  - _bmad-output/implementation-artifacts/spec-1-5-ouedkniss-adapter.md
  - _bmad-output/implementation-artifacts/spec-1-6-google-jobs-adapter.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The third source type — job postings shared inside Algerian Facebook groups — collects nothing; no adapter exists for it.

**Approach:** Implement the `facebook-groups` adapter with **Playwright (sync API)**, the tool the architecture already reserved for this target (the other two targets are JSON/requests; Facebook's DOM requires a real browser). The adapter browses configured **public** group URLs, extracts recent post cards (text, author, permalink), filters them by the Keyword Set locally (client-side — logged-out Facebook search is not reliable), and emits canonical items. Browser lifecycle is per-fetch (launch → browse → close in `finally`); headless Chromium; pinned CSS selectors as constants (Facebook changes DOM often — documented drift risk).

## Boundaries & Constraints

**Always:**
- SourcePort contract (AD-1): `fetch(keywords) -> raw items`, `parse(raw) -> canonical six-key dicts` (`title, company, url, published_at, keywords, raw_snapshot`).
- Config shape: `config['groups']` = list of group URLs (required, non-empty, validated in the adapter — invalid/missing → labelled error), `config['keywords']` = the Keyword Set (pipeline already validates the Source config; adapter stays permissive like the other adapters).
- Browser: Playwright **sync API**; chromium headless; one browser instance per `fetch`, one context per fetch, closed in `finally` (no leaked browser processes — Playwright's sync API + try/finally is the contract); UA default; `timeout=30s` per navigation action.
- Extraction: for each group URL — `goto`, wait for the feed (`wait_for_selector` on the pinned feed container selector), extract post cards via the pinned selectors, capture text/author/permalink. Posts without a permalink are skipped. If a **login wall** is detected (pinned marker selector or URL/heading marker), raise a labelled error ('login required') — silently returning [] would mask the real failure.
- Keyword filter: post text matched case-insensitively against each keyword (substring); a post is kept if ANY keyword matches. Matching happens in `parse` (raw keeps everything found).
- Canonical mapping: `title` ← first non-blank line of the post text, truncated to 500 (validate's cap — truncate HERE so validate never sees an overlong title); `company` ← author name ('' if absent); `url` ← post permalink; `published_at` ← None always (Facebook renders relative dates like "2 h" — parseable ISO is not available logged-out; lenient pipeline stores None; deferred: relative-date parsing); `keywords` ← `[keyword]` (the matching keyword(s)); `raw_snapshot` ← `{'text': <full text>, 'author': ..., 'permalink': ...}` dict (JSON-safe, pipeline caps at 2048).
- Dedupe across groups by str-normalized permalink; hard cap 50, first-occurrence; ALL groups always visited (cap never short-circuits the loop — the ratified semantics from Stories 1.5/1.6).
- Failure contract: browser launch failure, navigation timeout, login wall, selector-structure collapse → labelled adapter error (group URL context); collect_source logs stage 'fetch' ok=False. A group with ZERO posts is a valid empty result (not an error) — but only when the feed rendered.
- Hermetic tests: `sync_playwright` monkeypatched at the adapter module level with fake browser/context/page objects; fixture HTML derived from the pinned selectors' structure (documented as of 2026-08-19; a live probe is OPTIONAL — Facebook heavily gates logged-out traffic; do not burn more than one probe attempt).

**Ask First:** (none)

**Never:**
- No login/credentials/secret handling in the adapter — logged-out browsing only; private groups are out of scope (deferred entry: manual-login user-data-dir is a future option).
- No changes to `collect_source`, the pipeline, the repository, or the other two adapters (frozen).
- No live network in tests; no Playwright browser in tests (the fake-page pattern must keep the suite hermetic and fast).
- No screenshot/PDF generation, no mouse automation, no infinite scrolling (one viewport height + one scroll, bounded) — no aggressive anti-bot evasion; rate-limit-aware single pass per poll.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| OK_GROUP | fixture feed HTML with 3 post cards | fetch yields 3 raw items; parse yields canonical six-key dicts (keyword-filtered) | n/a |
| KEYWORD_FILTER | post text containing kw1, post without any kw | kw1 post kept (keywords=[kw1]), non-matching post dropped in parse | n/a |
| MULTI_GROUP | config groups [g1, g2] | both visited (call order pinned); permalink dedupe across; cap 50 first-occurrence | per-group failure → whole fetch fails (labelled, group context) |
| NO_POSTS | group feed renders with zero posts | raw [] for that group (valid) | n/a |
| LOGIN_WALL | page shows login-wall marker | labelled error ('login required') | collect_source stage 'fetch', ok=False |
| NAV_TIMEOUT | goto/wait times out | labelled error (group context) | ditto |
| BROWSER_FAIL | sync_playwright launch raises | labelled error | ditto |
| NO_PERMALINK | post card lacks link | item skipped | silent (documented) |
| MISSING_AUTHOR | card without author | company = '' | n/a |
| LONG_TEXT | post text > 500 chars first line | title truncated to 500 in the ADAPTER (validate never sees overlong) | n/a |
| CAP_BOUNDARY | 51 unique permalinks across groups | 50 returned; all groups visited | silent truncation (convention) |
| CONFIG_BAD | groups missing/empty | labelled error at fetch start | stage 'fetch' |

</frozen-after-approval>

## Code Map

- `backend/collector/ports.py` -- SourcePort (frozen).
- `backend/collector/adapters/` -- ouedkniss + google adapters (frozen) + new `facebook_groups.py`.
- `backend/collector/__init__.py` -- registration row added (`register('facebook-groups')`).
- `backend/requirements.txt` -- `playwright` pinned.
- `backend/collector/tests/fixtures/` -- optional probe artifacts; primary fixture: `facebook_feed.html` (built from the pinned selector structure).
- `backend/README.md` -- note the third adapter + the browser-download setup step (`uv run playwright install chromium`).

## Tasks & Acceptance

**Execution:**
- [ ] `uv pip install playwright` in `backend\` + `uv run playwright install chromium` (if the browser download fails, note it — the suite is hermetic and never needs the browser); pin `playwright` in `backend/requirements.txt` -- dependency
- [ ] `backend/collector/adapters/facebook_groups.py` -- `FacebookGroupsAdapter(SourcePort)`: `fetch(keywords)` (config groups validation; per-fetch browser lifecycle with try/finally close; per-group: goto → wait feed → extract cards via pinned selectors → raw items; login-wall detection; labelled errors with group context) and `parse(raw)` (keyword substring filter, six-key canonical mapping, title truncation at 500, keywords=[matching kw]) -- AD-1 contract, browser lifecycle, drift-aware selectors
- [ ] `backend/collector/__init__.py` -- `register('facebook-groups')(FacebookGroupsAdapter)` -- registry
- [ ] `backend/collector/tests/fixtures/facebook_feed.html` -- fixture DOM matching the pinned selectors (documented date) -- hermetic ground truth
- [ ] `backend/collector/tests.py` (extend) -- OK_GROUP, KEYWORD_FILTER, MULTI_GROUP (order + dedupe + cap), NO_POSTS, LOGIN_WALL, NAV_TIMEOUT, BROWSER_FAIL, NO_PERMALINK, MISSING_AUTHOR, LONG_TEXT truncation, CAP_BOUNDARY, CONFIG_BAD, production registration test, full-stack AC test (Source adapter_key='facebook-groups' → collect_source → FetchLog ok=True + Listings stored + source FK + raw_snapshot) -- matrix audit + AC; the fake-page pattern must not touch the real Playwright API
- [ ] `backend/README.md` -- third adapter + `playwright install chromium` setup step -- operator handoff
- [ ] `_bmad-output/implementation-artifacts/deferred-work.md` -- append TWO entries: (1) FB relative-date parsing (published_at always None logged-out — "2 h"/"hier" parsing is a future pipeline enhancement), (2) private-group login (user-data-dir manual login is a future option; out of scope now)

**Acceptance Criteria:**
- Given a registered facebook-groups Source, when the collector polls it, then job postings from configured public Facebook groups are stored.
- And post text is filtered by the Keyword Set before storing (only matching posts land in the listing store).

## Spec Change Log

(First review loopback, 2026-08-19 — ratified by code review.)

- **Config channel (ratified):** `collect_source` now instantiates adapters as
  `get_adapter(source.adapter_key)(config=<source.config, dict-guarded>)`; every
  adapter constructor takes `(self, config=None)` and the facebook-groups
  adapter reads `config['groups']` from this channel. This touches the frozen
  Story 1.3 file `collect.py` — a frozen-file exception for a mechanism fix:
  without the channel every facebook poll fails (review-proven: the adapter
  cannot know its groups otherwise).
- **Login-wall detection (ratified):** the wall check is a compound check —
  visible marker (`wait_for_selector(LOGIN_WALL_SELECTOR, timeout=3s,
  state='visible')`) OR `'/login' in page.url`. On a feed-wait timeout the
  wall is re-probed before labelling NAV_TIMEOUT: gated groups are reported as
  'login required', slow public groups never false-positive.
- **Fixture (ratified):** `facebook_feed.html` now includes a nested comment
  article inside a post card (no permalink -> skipped; plain body div so it
  never pollutes the parent post text), a sidebar/suggested-group article
  OUTSIDE the feed container (excluded by the scoped extraction selector), a
  multi-paragraph card (multiple dir="auto" blocks joined with '\n'), and
  permalink variants (trailing slash + `?comment_id=` query) pinning the
  (netloc, path) dedupe identity.
- **ouedkniss constructor (ratified):** `OuedknissJobsAdapter.__init__` gains
  the optional `config=None` parameter (accepted-but-unused) so every adapter
  conforms to the config-channel constructor contract.

## Suggested Review Order

**Config channel** — collect.py passes Source.config (dict-guarded) to adapter constructors
- [`collect.py:83`](../../backend/collector/collect.py#L83)

**Adapter** — browser lifecycle, compound wall check, scoped extraction, dedupe keys, parse purity
- [`facebook_groups.py:1`](../../backend/collector/adapters/facebook_groups.py#L1)

**Fixture** — decoys, multi-paragraph, URL variants
- [`facebook_feed.html:1`](../../backend/collector/tests/fixtures/facebook_feed.html#L1)

**Tests** — fake fidelity, lifecycle rows, real-fetch full-stack AC, wall co-presence
  [`tests.py:1`](../../backend/collector/tests.py#L1)

## Design Notes

- **Playwright, the reserved tool:** Facebook's post DOM is rendered client-side and login-gated; the architecture reserved Playwright for exactly this target. Sync API keeps the adapter linear (the worker is a plain process; no asyncio entanglement).
- **Logged-out reality:** many groups are partially gated. The adapter's contract is explicit: rendered-feed → extract; login-wall → labelled failure. Silent empty results are forbidden (they would masquerade as "no jobs found").
- **Selectors are constants, drift is expected:** Facebook ships DOM changes weekly; the pinned selector set is the adapter's single point of maintenance, and the login-wall marker is deliberately separate from the feed selectors.
- **Keyword filter lives in parse:** fetch stores what it sees; parse applies the Keyword Set — matching the SourcePort separation and keeping fetch re-usable.
- **Bounded browsing:** one viewport + one additional scroll per group, single pass. Anti-evasion measures are out of scope by design (personal tool, low cadence).

## Verification

**Commands:**
- `uv run python manage.py check` -- expected: 0 issues
- `uv run python manage.py test` -- expected: all pass (168 + new)
- `uv run python manage.py makemigrations --check --dry-run` -- expected: "No changes detected"
- `uv run python playwright install chromium` -- expected: installs or reports the network issue

**Manual checks (if no CLI):**
- No test imports or drives the real Playwright API (grep `playwright` in tests → only the module-level patch).
- `collector/adapters/facebook_groups.py` has no Django imports (AD-1 purity).
- The adapter contains no credentials/login code (grep for password/login handling → only the wall-detection marker).