"""GoogleJobsAdapter — the `google-jobs` SourcePort adapter.

Target: Google Jobs served through the **JobSpy** package's requests-based
Google scraper (`python-jobspy` on PyPI, import name `jobspy`; no API key,
no browser — the Google path is a plain requests session). The installed
version (1.1.82) exposes `scrape_jobs(site_name='google', search_term,
location, results_wanted, hours_old, ...) -> pandas DataFrame` — there is
no `jobspy.jobs` alias, and `country_indeed` is omitted because the Google
path never reads it and this version's Country enum has no 'algeria'
entry (passing one would raise ValueError before scraping). `hours_old`
IS honored by the Google path (appended to the query, e.g. "since
yesterday" for <= 24h).

Verified output schema (installed version's `desired_order`; probe
2026-08-19 recorded in `collector/tests/fixtures/google_jobs_probe.json`):
`id, site, job_url, job_url_direct, title, company, location,
date_posted, ...`. The posting-date column is `date_posted` (a
`datetime.date` for Google) — the spec-era `listed_time`/`posting_date`
names do not exist in this version and are kept only as fallbacks.
The live probe (`développeur`, Algeria, 5 wanted, 24h) returned an empty
DataFrame — Google served nothing for the window, so the test fixture is
built from the verified schema instead.

AD-1: pure adapter — no DB access, no Django imports. `fetch` sanitizes
every pandas/numpy value to a JSON-safe python scalar at the seam
(Timestamp -> ISO string; NaT/NaN/NA -> None; numpy scalars -> python
scalars) so `parse` and the pipeline only ever see plain dicts; dedupes
by str-normalized job_url across keywords; caps the output at 50
first-occurrence items while always searching every keyword. `fetch`
raises `GoogleJobsAdapterError` (keyword context) on any JobSpy failure;
an empty DataFrame is a valid empty result, not an error. `parse` is
pure.

`jobspy` is imported lazily inside `fetch` (never at module import
time): pulling pandas + bs4 at package import would cost ~0.7s cold in
every Django process (the collector app is in INSTALLED_APPS). The
module-level `scrape_jobs = None` slot stays patchable — tests patch
`collector.adapters.google_jobs.scrape_jobs`.
"""

from datetime import date, datetime

from ..ports import SourcePort

# Lazy-import slot for jobspy's scrape_jobs (see module docstring);
# bound to the real function on the first fetch() call.
scrape_jobs = None

# Hard sample cap: same convention as collector/test_fetch.py.
MAX_SAMPLE = 50
# Site search defaults. The config channel (Story 1.7 review loopback,
# ratified) passes Source.config to every adapter constructor; these are
# the defaults used when the channel is absent or the keys are missing.
DEFAULT_LOCATION = 'Algeria'
DEFAULT_HOURS_OLD = 24

# published_at column order: verified schema uses `date_posted`; the
# spec-era `listed_time`/`posting_date` names stay as drift fallbacks.
_POSTED_COLUMNS = ('date_posted', 'listed_time', 'posting_date')


class GoogleJobsAdapterError(Exception):
    """JobSpy/Google failure with the keyword context in the message.

    `collect_source` catches everything (AD-6) and logs the message with
    stage 'fetch'; the keyword + failure kind make the log actionable.
    """


def _sanitize_value(value):
    """JSON-safe conversion for a pandas/numpy DataFrame cell.

    Timestamp -> ISO string, NaT/NaN/NA -> None, numpy scalars -> python
    scalars; str/int/float/bool/None pass through unchanged.
    """
    # pandas.NA / numpy.NA singleton: raises TypeError on `==` (ambiguous
    # boolean) and str()s to '<NA>'; duck-typed via type name so pandas
    # is never imported at module time.
    if type(value).__name__ == 'NAType':
        return None
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    try:
        if not (value == value):  # NaN / NaT (pandas and numpy) are not self-equal
            return None
    except Exception:
        pass
    # NaT is a datetime subclass in pandas 2.x, so the self-equality
    # check must run BEFORE the datetime branch (NaT.isoformat() is 'NaT').
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float, str)):
        return value
    item = getattr(value, 'item', None)
    if callable(item):
        return _sanitize_value(item())
    return str(value)


def _sanitize_row(row):
    """Sanitize every cell of one row dict (JSON-safe at the seam)."""
    return {key: _sanitize_value(value) for key, value in row.items()}


def _posted_at(item):
    """First present posting-date column (ISO string or None after fetch)."""
    for key in _POSTED_COLUMNS:
        value = item.get(key)
        if value is not None:
            return value
    return None


class GoogleJobsAdapter(SourcePort):
    """Fetch Google Jobs postings via JobSpy's requests-based scraper."""

    def __init__(self, config=None):
        config = config or {}
        self.location = config.get('location', DEFAULT_LOCATION)
        self.hours_old = config.get('hours_old', DEFAULT_HOURS_OLD)

    def fetch(self, keywords: list[str]) -> list[dict]:
        """One scrape_jobs call per keyword, job_url-deduped, capped.

        Each raw item is wrapped as `{'keyword': <keyword that produced
        the item>, 'item': <sanitized row dict>}` so parse() can tag the
        canonical `keywords` field per item. Every keyword is always
        searched (the 50-item output cap never short-circuits the keyword
        loop); items keep first-occurrence order and the output is
        truncated silently at 50. JobSpy's google path caps
        results_wanted at 900, so 50 is our self-imposed cap (the
        MAX_SAMPLE convention, same as test_fetch/ouedkniss) — not a
        jobspy limit.
        """
        global scrape_jobs
        seen_urls = set()
        raw_items = []
        # 0 is falsy in jobspy's google path (`if self.scraper_input.
        # hours_old:`) and silently disables the freshness window ->
        # unbounded scrape; negatives widen to 'last month'. Both fall
        # back to the default.
        hours_old = (
            self.hours_old
            if (self.hours_old and self.hours_old > 0)
            else DEFAULT_HOURS_OLD
        )
        for keyword in keywords:
            if scrape_jobs is None:
                from jobspy import scrape_jobs
            try:
                frame = scrape_jobs(
                    site_name='google',
                    search_term=keyword,
                    location=self.location,
                    results_wanted=MAX_SAMPLE,
                    hours_old=hours_old,
                )
                # scrape_jobs may return a dict/list on drift; to_dict
                # then raises AttributeError, wrapped with keyword
                # context below instead of surfacing bare.
                rows = frame.to_dict(orient='records') if frame is not None else []
            except Exception as exc:
                raise GoogleJobsAdapterError(
                    f'google-jobs scrape failed for keyword {keyword!r}: {exc}'
                ) from exc
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row = _sanitize_row(row)
                url = row.get('job_url')
                if not isinstance(url, str) or not url.strip():
                    continue
                key = url.strip().lower()
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                raw_items.append({'keyword': keyword, 'item': row})
        return raw_items[:MAX_SAMPLE]

    def parse(self, raw_items: list[dict]) -> list[dict]:
        """Canonical six-key mapping per the Story 1.6 matrix.

        Exactly six keys: title, company, url, published_at, keywords,
        raw_snapshot. Items without a string title or job_url are
        skipped; `keywords` is a single-element list (normalize_keywords
        would split a bare string on commas); `company` is '' when
        missing/blank; `published_at` is the sanitized posting date
        (ISO or None).
        """
        parsed = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            item = raw.get('item')
            keyword = raw.get('keyword')
            if not isinstance(item, dict) or not isinstance(keyword, str):
                continue
            title = item.get('title')
            url = item.get('job_url')
            if not isinstance(title, str) or not title:
                continue
            if not isinstance(url, str) or not url.strip():
                continue
            company = item.get('company')
            if not isinstance(company, str) or not company:
                company = ''
            parsed.append({
                'title': title,
                'company': company,
                'url': url,
                'published_at': _posted_at(item),
                'keywords': [keyword],
                'raw_snapshot': item,
            })
        return parsed
