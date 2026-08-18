"""Generic test-fetch service (FR-1 test-fetch path).

Keyword-substituted URL template + CSS/XPath selector evaluated with
parsel — the same selector syntax the Scrapy adapters (Story 1.5+) use.
No FetchLog writes here; collection owns them (Story 1.3).
"""

from urllib.parse import quote

import requests
from parsel import Selector

# Keep API responses bounded: the raw snapshot is truncated to this size.
MAX_RAW_SNAPSHOT = 2048
# Keep the sample list bounded: never return more than this many raw items.
MAX_SAMPLE = 50

# Fetch hardening: the generic path talks to arbitrary sites, so give
# requests a timeout and a browser-ish User-Agent.
FETCH_TIMEOUT = 30
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
)


class TestFetchError(Exception):
    """Fetch/selector failure surfaced as an error envelope, never a crash."""


def build_url(url_pattern: str, keywords: list[str]) -> str:
    """Substitute the keyword list into the `{keywords}` placeholder.

    Each keyword is URL-encoded individually, so a literal `+` in a keyword
    (e.g. "c++") becomes %2B and cannot be confused with the `+` separator
    between keywords. Only the `{keywords}` placeholder is replaced, so
    other braces in the pattern never crash.
    """
    encoded = '+'.join(quote(keyword) for keyword in keywords)
    return url_pattern.replace('{keywords}', encoded)


def run_test_fetch(source, fetch=None):
    """Fetch a source's URL template and evaluate its listing selector.

    `source` is duck-typed on `.config` (the registry stays DB-free, AD-1).
    `fetch` defaults to `requests.get` at call time (patchable in tests).

    Returns `{'sample': [...raw items...], 'raw_snapshot': <html>}` or, when
    nothing matches, `{'sample': [], 'notice': 'selector-mismatch',
    'raw_snapshot': <html>}` so the selector can be tuned against the page.
    """
    if fetch is None:
        fetch = requests.get
    config = source.config
    if not isinstance(config, dict):
        raise TestFetchError('invalid config: config must be a JSON object')
    url_pattern = config.get('url_pattern', '')
    listing_selector = config.get('listing_selector', '')
    keywords = config.get('keywords') or []

    if not isinstance(url_pattern, str) or '{keywords}' not in url_pattern:
        raise TestFetchError(
            'invalid config: url_pattern must contain the {keywords} placeholder'
        )
    if not isinstance(listing_selector, str) or not listing_selector.strip():
        raise TestFetchError('invalid config: listing_selector is required')
    if not isinstance(keywords, list) or not keywords:
        raise TestFetchError('invalid config: keywords must be a non-empty list')
    if not all(isinstance(k, str) and k.strip() for k in keywords):
        raise TestFetchError(
            'invalid config: keywords must be a list of non-empty strings'
        )

    url = build_url(url_pattern, keywords)
    try:
        response = fetch(
            url, timeout=FETCH_TIMEOUT, headers={'User-Agent': USER_AGENT}
        )
        response.raise_for_status()
        # response.text lives inside the guard: a non-requests response
        # missing `.text` surfaces as TestFetchError, never AttributeError.
        html = response.text or ''
    except TestFetchError:
        raise
    except Exception as exc:
        raise TestFetchError(f'fetch failed: {exc}') from exc

    try:
        selector = Selector(text=html)
        # XPath convention (Scrapy-style): a stripped selector starting with
        # `/` (covers `//...` and absolute `/html/body/...`) is XPath;
        # everything else is a CSS selector.
        if listing_selector.strip().startswith('/'):
            matched = selector.xpath(listing_selector)
        else:
            matched = selector.css(listing_selector)
    except Exception as exc:
        raise TestFetchError(f'selector evaluation failed: {exc}') from exc

    raw_snapshot = html[:MAX_RAW_SNAPSHOT]
    sample = [{'html': item.get()} for item in matched[:MAX_SAMPLE]]
    if not sample:
        return {
            'sample': [],
            'notice': 'selector-mismatch',
            'raw_snapshot': raw_snapshot,
        }
    return {'sample': sample, 'raw_snapshot': raw_snapshot}