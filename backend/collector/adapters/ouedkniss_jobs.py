"""OuedknissJobsAdapter — the `ouedkniss-jobs` SourcePort adapter.

Target: the public ouedkniss GraphQL API (`https://api.ouedkniss.com/graphql`),
the same endpoint the ouedkniss.com SPA consumes. The site is a
client-rendered SPA (empty `#app` shell server-side), so there is no HTML to
scrape; this adapter speaks the SPA's own data plane. JSON only.

Live-verified shape (probe 2026-08-18, recorded in
`collector/tests/fixtures/search_response.json`):
- One `SearchQuery` per keyword (`q=<keyword>`); the search response carries
  the detail fields directly — `id, title, slug, refreshedAt,
  user{displayName}, store{name}, cities{name}` — so no N+1 `AnnouncementGet`
  fallback is needed.
- The jobs category slug is `offres_demandes_emploi` ("عروض و طلبات العمل",
  mega-menu category id 765). The spec-era `emploi` slug returns zero results
  (verified live); this adapter pins the working slug.
- Listing URL format pinned to the SPA Show route (verified live via the SPA
  route table `^/[^/]+-d\d+$` -> Show bundle and by rendering a detail page):
  `https://www.ouedkniss.com/{slug}-d{id}`.
- `store` is frequently `null` for individual sellers; `cities` can be an
  empty list. `refreshedAt` is ISO-8601 with milliseconds and a Z suffix.

AD-1: pure-ish adapter — no DB access, no Django imports. `fetch` raises
`OuedknissAdapterError` on any API/HTTP/JSON/GraphQL failure with the
keyword stage named in the message; `parse` is pure.
"""

import json

import requests

from ..ports import SourcePort

API_URL = 'https://api.ouedkniss.com/graphql'
# Live-verified jobs category slug (mega-menu "عروض و طلبات العمل").
CATEGORY_SLUG = 'offres_demandes_emploi'
# Hard sample cap: same convention as collector/test_fetch.py.
MAX_SAMPLE = 50
# Fetch hardening: same convention as collector/test_fetch.py.
FETCH_TIMEOUT = 30
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
)

_FILTER = {
    'categorySlug': CATEGORY_SLUG,
    'origin': None,
    'connected': False,
    'delivery': None,
    'regionIds': [],
    'cityIds': [],
    'priceRange': [None, None],
    'exchange': None,
    'hasPictures': False,
    'hasPrice': False,
    'priceUnit': None,
    'fields': [],
    'page': 1,
    'orderByField': {'field': 'REFRESHED_AT'},
    'count': MAX_SAMPLE,
}

_SEARCH_QUERY = (
    'query SearchQuery($q: String, $filter: SearchFilterInput) {'
    ' search(q: $q, filter: $filter) {'
    '  announcements {'
    '   data {'
    '    id title slug refreshedAt'
    '    user { displayName }'
    '    store { name }'
    # cities { name }: future location-key intent — do not drop the field.
    '    cities { name }'
    '   }'
    '   paginatorInfo { lastPage hasMorePages total }'
    '  }'
    ' }'
    '}'
)


class OuedknissAdapterError(Exception):
    """Ouedkniss API failure with the stage context in the message.

    `collect_source` catches everything (AD-6) and logs the message with
    stage 'fetch'; the keyword + failure kind make the log actionable.
    """


class OuedknissJobsAdapter(SourcePort):
    """Fetch ouedkniss jobs postings via the site's own GraphQL endpoint."""

    def __init__(self, config=None):
        # Config channel (Story 1.7 review loopback, ratified): every
        # adapter constructor takes the optional dict; ouedkniss has no
        # per-source options yet, so config is accepted-but-unused.
        pass

    def fetch(self, keywords: list[str]) -> list[dict]:
        """One SearchQuery per keyword (q=<keyword>), id-deduped, capped.

        Each raw item is wrapped as `{'keyword': <keyword that produced the
        item>, 'item': <site item dict>}` so parse() can tag the canonical
        `keywords` field per item. Every keyword is always queried (the
        50-item output cap never short-circuits the keyword loop); items
        keep first-occurrence order and the output is truncated silently at
        50 (same convention as test_fetch); never a partial error.
        """
        seen_ids = set()
        raw_items = []
        for keyword in keywords:
            items = self._search(keyword)
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_id = item.get('id')
                if item_id is None:
                    continue
                key = str(item_id)
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                raw_items.append({'keyword': keyword, 'item': item})
        return raw_items[:MAX_SAMPLE]

    def parse(self, raw_items: list[dict]) -> list[dict]:
        """Canonical six-key mapping per the Story 1.5 matrix.

        Exactly six keys: title, company, url, published_at, keywords,
        raw_snapshot. Items without a truthy id or a string slug/title are
        skipped (no URL can be pinned); `keywords` is a single-element list
        (normalize_keywords would split a bare string on commas);
        `company` is user.displayName or store.name or ''.
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
            item_id = item.get('id')
            slug = item.get('slug')
            if not item_id or not isinstance(slug, str) or not slug:
                continue
            if not isinstance(title, str):
                continue
            user = item.get('user')
            store = item.get('store')
            company = ''
            if isinstance(user, dict) and user.get('displayName'):
                company = user['displayName']
            elif isinstance(store, dict) and store.get('name'):
                company = store['name']
            parsed.append({
                'title': title,
                'company': company,
                'url': f'https://www.ouedkniss.com/{slug}-d{item_id}',
                'published_at': item.get('refreshedAt'),
                'keywords': [keyword],
                'raw_snapshot': item,
            })
        return parsed

    def _search(self, keyword: str) -> list[dict]:
        """POST one SearchQuery; raise OuedknissAdapterError with context."""
        payload = {
            'operationName': 'SearchQuery',
            'variables': {'q': keyword, 'filter': dict(_FILTER)},
            'query': _SEARCH_QUERY,
        }
        try:
            response = requests.post(
                API_URL,
                json=payload,
                headers={'User-Agent': USER_AGENT},
                timeout=FETCH_TIMEOUT,
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise OuedknissAdapterError(
                f'ouedkniss SearchQuery failed for keyword {keyword!r}: {exc}'
            ) from exc
        if not isinstance(body, dict):
            raise OuedknissAdapterError(
                f'ouedkniss SearchQuery returned non-object JSON for keyword {keyword!r}'
            )
        if body.get('errors'):
            raise OuedknissAdapterError(
                f'ouedkniss SearchQuery returned GraphQL errors for keyword '
                f'{keyword!r}: {json.dumps(body["errors"], ensure_ascii=False)[:200]}'
            )
        try:
            data = body['data']
            if data is None:
                return []
            search = data['search'] or {}
            announcements = search.get('announcements') or {}
            return announcements.get('data') or []
        except (KeyError, TypeError, AttributeError) as exc:
            raise OuedknissAdapterError(
                f'ouedkniss SearchQuery returned an unexpected shape for '
                f'keyword {keyword!r}: {exc}'
            ) from exc