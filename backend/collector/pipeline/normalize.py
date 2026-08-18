"""Pure stage: AD-1 harmonization — published_at, keywords, url host,
raw_snapshot bounding.

Value harmonization lives HERE, not in adapters: any adapter output
converges on the canonical field set (published_at as ISO-8601 UTC
string or None, keywords as list[str]).
"""

import json
from datetime import datetime, timezone
from urllib.parse import urlparse

# Bound the persisted snapshot (convention from test_fetch).
MAX_RAW_SNAPSHOT = 2048


def normalize_published_at(value):
    """Lenient: any parseable ISO-8601 value -> ISO-8601 UTC string.

    Unparseable/absent values -> None (lenient per spec: a bad date
    never fails the item). Naive datetimes are assumed to be UTC.
    """
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        if not isinstance(value, str):
            value = str(value)
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def normalize_keywords(value):
    """Coerce keywords to a list of non-empty stripped strings.

    A comma-separated string ('python, django') is split first; list
    elements that are None, dicts, or lists/tuples are dropped; scalar
    elements (str/int/float/bool/...) are stringified and stripped;
    anything else at the top level (a number, ...) -> [].
    """
    if value is None:
        return []
    if isinstance(value, str):
        parts = [part for part in value.split(',')]
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        return []
    keywords = []
    for part in parts:
        if part is None or isinstance(part, (dict, list, tuple)):
            continue
        cleaned = str(part).strip()
        if cleaned:
            keywords.append(cleaned)
    return keywords


def url_host(url):
    """Extract the host (no port) of a url, lowercased.

    Unparseable or absent values -> '' (fingerprint-safe: a missing
    host still hashes deterministically).
    """
    if not isinstance(url, str) or not url.strip():
        return ''
    try:
        host = urlparse(url).hostname
    except ValueError:
        return ''
    return (host or '').lower()


def _cap_raw_snapshot(value):
    """Bound the persisted snapshot: JSON must fit MAX_RAW_SNAPSHOT chars.

    String values are truncated longest-first until the whole snapshot
    fits; the result is always a valid JSON object. Non-dict snapshots
    pass through untouched.
    """
    if not isinstance(value, dict):
        return value
    if len(json.dumps(value, ensure_ascii=False)) <= MAX_RAW_SNAPSHOT:
        return value
    candidate = dict(value)
    strings = [k for k, v in candidate.items() if isinstance(v, str)]
    for key in sorted(strings, key=lambda k: len(candidate[k]), reverse=True):
        while len(candidate[key]) > 1:
            candidate[key] = candidate[key][: len(candidate[key]) // 2]
            if len(json.dumps(candidate, ensure_ascii=False)) <= MAX_RAW_SNAPSHOT:
                return candidate
    return candidate


def normalize_item(item):
    """Normalize one item: published_at + keywords + bounded raw_snapshot."""
    item = dict(item)
    item['published_at'] = normalize_published_at(item.get('published_at'))
    item['keywords'] = normalize_keywords(item.get('keywords'))
    item['raw_snapshot'] = _cap_raw_snapshot(item.get('raw_snapshot'))
    return item


def normalize(items):
    """Apply normalize_item to every item (pure, list-preserving)."""
    return [normalize_item(item) for item in items]