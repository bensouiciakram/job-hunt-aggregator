# Addendum — Job Hunt Aggregator PRD

*Supporting depth for the PRD. Not part of the PRD's main narrative.*

## Options Considered: Existing Tools (landscape research, 2026-08-18)

- **JobSpy** (`speedyapply/JobSpy`) — de-facto standard Python library; scrapes LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter, Bayt, Naukri concurrently into a DataFrame; proxy rotation built in. Candidate to wrap for the LinkedIn/Google Sources instead of bespoke scrapers.
- **JobWise** (starbringer) — self-hosted AI assistant; fetches Greenhouse/Lever/JSearch/JobSpy, LLM scores jobs vs. profile, pipeline tracking.
- **JobSentinel** (cboyd0319) — local-first Tauri app; source taxonomy, ghost-job/freshness signals, local embeddings + BM25 + reranker matching.
- **mr-jobs** (humancto) — self-hosted command center; ATS APIs, HN Who's Hiring, JobSpy; AI scoring vs. resume; auto-apply via Playwright.
- **freehire** (strelov1) — crawls company ATS pages (Workday, Greenhouse, Lever), Meilisearch full-text search, deterministic CV↔job scoring.

Verdict: none match the personal-use + Algerian-context + judgment-scoring combination; building locally remains right. JobSpy is the strongest reuse candidate for v1 LinkedIn/Google sources.

## Hard-Source Failure Points (research)

- **LinkedIn** — auth wall + JS rendering defeats requests-based scrapers (~95% block); headless browsers detected ~45%; **account ban is the distinctive risk** (unofficial APIs ban accounts in 3–7 days, permanent, near-zero appeal); concurrency (not volume) rate-limits; ~1,000 result cap per query; robots.txt disallows all. → Open Question 1.
- **Facebook groups** — login wall; private groups need auth; Meta fingerprinting flags datacenter IPs; bans account-level, temporary; practical workaround: discover post URLs via Google SERP and scrape direct post URLs.
- **Google Jobs** — no official API (shut down 2021); JS-rendered; obfuscated class names rot within hours — parse embedded JSON-LD instead; CAPTCHA/IP bans; silent failures (empty results, not errors). → Open Question 2.

## Matching Approaches Observed

- Hybrid lexical + semantic (BM25/TF-IDF + embedding cosine, ~60/40) with hard-requirement gates and cross-encoder rerank (JobSentinel et al.).
- LLM scoring 0–100 vs. resume with match reasons (mr-jobs, JobWise) — more explainable, more expensive.

Relevance: Interest Scoring (FR-6) can start rule-based (post sanity heuristics) and adopt hybrid matching later; LLM scoring deferred per Eliminate decision.

## Technical Direction (from brainstorming session)

- Stack: Django (API + scrapers) + Next.js (frontend), localhost single user.
- Scraping: Scrapy + Playwright; reuse Fiverr-era multi-phase pipeline: raw → extraction → cleaning → normalization → deduplication → validation (adapted from the ouedkniss real-estate platform, which also proves Algerian-source experience).
- Extensibility principle: engine starts simple, designed to be extended — Source Registry is the extension path.
- Real-time: v1 = polling (30 min); websockets push later.
- Reuse candidates from prior projects: dz-leads-finder scraping patterns, real-estate analytics pipeline.