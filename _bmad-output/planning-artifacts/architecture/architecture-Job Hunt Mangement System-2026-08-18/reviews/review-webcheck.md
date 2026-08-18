# Web-Reality-Check Review — ARCHITECTURE-SPINE.md

- **Reviewer role:** Web-reality-check reviewer (architecture review gate)
- **Artifact reviewed:** `ARCHITECTURE-SPINE.md` (Job Hunt Aggregator, 2026-08-18)
- **Date of check:** 2026-08-18
- **Method:** Every committed technology verified against PyPI, official docs, project homepages, and 2026 dated third-party reviews via web search; no item accepted from training data alone.

---

## Verdict

**PASS with notes.** All nine committed technologies exist, are current (as of 2026-08-18), and fit their described roles. The stack is unusually fresh: Django 6.1 shipped 13 days before this artifact was written. No technology is deprecated, renamed in a breaking way, or mismatched to its role. Five advisory notes below — none blocks build approval.

---

## Per-technology verification

| Stack entry (spine §Stack, line 110–122) | Reality check | Status |
| --- | --- | --- |
| Python 3.13 | Real. Current line 3.13.15 (2026-08-05); 3.13 is in bugfix phase, supported until Oct 2029. Note: 3.14 (3.14.7) is now the latest feature release. Django 6.1 officially supports 3.12–3.14, so 3.13 is fully within the supported matrix. | ✅ current, supported |
| Django 6.1 | Real. Released 2026-08-05 — the current stable branch (6.2 under development). Supports Python 3.12/3.13/3.14. Mainstream support to Apr 2027, extended to Dec 2027. | ✅ current (just shipped) |
| Next.js 16.x | Real. 16.0 stable Oct 2025; current 16.3.1 (2026-08-13). Turbopack default bundler; Node 20+ required. Fits the localhost frontend role. | ✅ current |
| React 19.x | Real. React 19.x is the line Next.js 16 ships against (19.2 in 16.2+). No mismatch. | ✅ current |
| SQLite (bundled with Python) | Real, trivially. Single-writer, localhost scope (AD-2) is a textbook SQLite fit. | ✅ fits |
| JobSpy (`python-jobspy`) | Real. PyPI `python-jobspy` 1.1.82 (verified Jun 2026); requires Python ≥3.10 (compatible with 3.13). Google is a supported `site_name`. **Repo transferred/renamed cullenwatson/JobSpy → speedyapply/JobSpy** (PyPI name unchanged — spine's reference is still correct). See Finding W-2. | ✅ exists; ⚠ fragility (W-1) |
| Scrapy | Real, current. 2.17.0 (2026-07-07); 2.16.0 added official Python 3.14 support; actively maintained by Zyte, Python 3.10+. Correct tool for the ouedkniss HTML/JSON-LD adapter. | ✅ current |
| Playwright | Real, current. Python package 1.62.0 (2026-07-31), maintained by Microsoft. Correct tool for the facebook-groups browser/SERP adapter. | ✅ current |
| APScheduler | Real, current. Stable line 3.11.3 (2026-06-28) — still actively maintained. 4.0 remains pre-release (4.0.0a6, Apr 2025) with an explicit "do NOT use in production" warning. "Pin at install" is exactly right — pin 3.x. See W-4. | ✅ current; pin 3.x |

---

## Specific confirmations requested

### 1. JobSpy actually supports Google Jobs scraping — CONFIRMED, with caveats

- PyPI `python-jobspy` (1.1.82) documents `site_name=["indeed", "linkedin", "zip_recruiter", "google", ...]` with a dedicated `google_search_term` parameter; the project README and multiple 2025–2026 third-party write-ups confirm Google for Jobs is a supported source.
- Caveats, all documented in 2026 sources:
  - There is **no official Google Jobs API** — Google's hosted jobs API was shut down in 2021; JobSpy's google adapter scrapes the Google for Jobs widget out of SERP HTML.
  - The widget is JS-rendered/lazy-loaded, Google changes markup often, and repeated automated traffic gets blocked (Serpent 2026-06 guide; JobSpy review 2026-07: "until it gets blocked"; JobSpy review: "limits are operational rather than functional: blocking at scale").
  - The spine already hedges correctly: AD-6 failure isolation per Source + raw-snapshot persistence for selector repair + FetchLog is precisely the right posture for the most fragile adapter in the system. The `google-jobs` adapter should be treated as highest-fragility and the first candidate for a proxy/SERP-API swap later.

### 2. APScheduler appropriate for an in-process 30-min polling loop — CONFIRMED

- APScheduler's `BackgroundScheduler`/`BlockingScheduler` with an `IntervalTrigger` is the canonical in-process pattern for exactly this shape (official docs; 2026 guides confirm interval triggers for polling).
- Alternative considered and rejected in favor of APScheduler: **Django 6.0+ ships a built-in `django.tasks` framework, but it has no periodic scheduling** (no scheduler equivalent to Celery Beat/cron — confirmed by Django docs and Aug 2026 third-party analysis). APScheduler remains the right tool for a timed poll; the built-in task framework is not a substitute and does not obsolete AD-7.
- Misfire/backfill semantics in AD-7 (coalesce, misfire grace) map directly onto APScheduler's `coalesce`/`misfire_grace_time` options — the design intent and the library capabilities align.

### 3. Scrapy and Playwright still current — CONFIRMED

- Scrapy 2.17.0 (Jul 2026), monthly release cadence, 15+ years of maintenance. Playwright 1.62.0 (Jul 2026), ~3-week release cadence, Microsoft-maintained. Both fit their adapters (Scrapy for static HTML/JSON-LD, Playwright for a JS-heavy/browser-bound source).

---

## Findings

| # | Severity | Finding |
| --- | --- | --- |
| W-1 | **Medium** | JobSpy's Google Jobs source is the system's most fragile component: no official Google API exists (retired 2021), SERP markup changes frequently, and automated traffic is blocked. Spine's AD-6 (per-source failure isolation, raw snapshots, FetchLog) is the correct mitigation, but plan for proxies and a possible SERP-API fallback on `google-jobs`; don't let a Google breakage stall other sources. |
| W-2 | **Low** | JobSpy's GitHub repo was transferred from `cullenwatson/JobSpy` to `speedyapply/JobSpy`; PyPI name `python-jobspy` is unchanged, so the spine's reference remains valid — but pin the exact version at install and re-verify the maintainer identity when sourcing issue docs. |
| W-3 | **Low** | Python 3.13 is fully supported (bugfix phase, EOL Oct 2029) — no action required — but 3.14 is now the latest feature release and Django 6.1 supports it; consider 3.14 for new installs or accept 3.13 deliberately. |
| W-4 | **Info** | APScheduler 4.0 is still alpha (4.0.0a6, 2025) with an explicit "do NOT use in production" warning. The spine's "pin at install" is correct; pin the 3.11.x line (3.11.3, Jun 2026) and don't let a resolver float to 4.0 pre-releases. |
| W-5 | **Info** | Django 6.1 shipped 2026-08-05 — 13 days before the spine. The version numbers in the spine are real and current, not aspirational; the only consequence is that Django 6.1's brand-new `django.tasks` framework (no scheduler) should not be confused with a replacement for the APScheduler worker in AD-7. |

No deprecated, renamed-in-a-breaking-way, or role-mismatched technologies found.

---

## Sources

1. python-jobspy on PyPI (1.1.82) — https://pypi.org/project/python-jobspy/
2. JobSpy repository (speedyapply/JobSpy) — https://github.com/speedyapply/JobSpy
3. "JobSpy review: the Python job scraper tested, and where it breaks" (2026-07-13) — https://jobspipe.dev/blog/jobspy-review
4. "How to Scrape Google for Jobs in 2026 (Python, No API)" (2026-06-08; confirms no official Google Jobs API since 2021, JS-rendered widget, blocking) — https://apiserpent.com/blog/scrape-google-jobs-python
5. Django 6.1 release notes (2026-08-05; Python 3.12/3.13/3.14 support) — https://docs.djangoproject.com/en/6.1/releases/6.1/
6. "Django 6.1 released" weblog (2026-08-05) — https://www.djangoproject.com/weblog/2026/aug/05/django-61-released/
7. Django Tasks framework docs (no worker/execution; no periodic scheduling) — https://docs.djangoproject.com/en/6.0/topics/tasks/ and https://djangoproject.in/blog/django-background-tasks-2026
8. Next.js 16 release (2025-10-21) and Version 16 upgrade guide — https://nextjs.org/blog/next-16, https://nextjs.org/docs/app/guides/upgrading/version-16
9. Next.js versionlog (16.2.7, Jun 2026) and Wikipedia stable release 16.3.1 (2026-08-13); npm `next` 16.3.1 — https://versionlog.com/nextjs/16/, https://www.npmjs.com/package/next
10. Python 3.13 status (bugfix; EOL Oct 2029) and 3.13.15 release — https://devguide.python.org/versions/, https://peps.python.org/pep-0719/, https://www.python.org/downloads/release/python-3130/
11. APScheduler on PyPI (3.11.3, Jun 2026; 4.0.0a6 pre-release) — https://pypi.org/project/APScheduler/; repo README pre-release warning — https://github.com/agronholm/apscheduler
12. Scrapy 2.17.0 (2026-07-07) — https://pypi.org/project/Scrapy/, https://dev.scrapy.org/
13. Playwright Python 1.62.0 (2026-07-31) — https://pypi.org/project/playwright/, https://releasealert.dev/pypi/playwright