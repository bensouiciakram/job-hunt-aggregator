"""Pure stage: AD-4 identity — compute_fingerprint + per-item assignment.

The hash is computed once at ingestion and is independent of DB state,
so it is trivially testable and stable across collection passes.
`|` separators prevent collisions like "a|b" + "c" == "a" + "b|c".
"""

import hashlib

from .normalize import url_host


def _norm(value):
    """Normalize one identity part: string, lowercase, stripped.

    `%` is escaped before `|` so both 'a%7Cb' and 'a|b' hash without
    ambiguity, and 'a|b' + 'c' can never collide with 'a' + 'b|c'.
    """
    if value is None:
        return ''
    return str(value).strip().lower().replace('%', '%25').replace('|', '%7C')


def compute_fingerprint(title, company, url):
    """sha256 hex of `normalized title | normalized company | url host`.

    Lowercased + stripped before hashing, so casing variants of the
    same listing produce an identical fingerprint (FINGERPRINT_STABLE).
    """
    payload = '|'.join((_norm(title), _norm(company), url_host(url)))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def dedupe_item(item):
    """Assign `dedup_fingerprint` to one item (in place on a copy)."""
    item = dict(item)
    item['dedup_fingerprint'] = compute_fingerprint(
        item.get('title'), item.get('company'), item.get('url')
    )
    return item


def dedupe(items):
    """Apply dedupe_item to every item (pure, list-preserving)."""
    return [dedupe_item(item) for item in items]