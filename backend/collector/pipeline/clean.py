"""Pure stage: canonical text hygiene.

Strip/collapse whitespace in title/company/url; drop empty string
fields (the key is removed so validation sees a missing field, never
a whitespace-only string).
"""

_TEXT_KEYS = ('title', 'company', 'url')


def clean_item(item):
    """Clean one item: collapse whitespace, drop empty string fields."""
    item = dict(item)
    for key in _TEXT_KEYS:
        value = item.get(key)
        if isinstance(value, str):
            cleaned = ' '.join(value.split())
            if cleaned:
                item[key] = cleaned
            else:
                item.pop(key, None)
    return item


def clean(items):
    """Apply clean_item to every item (pure, list-preserving)."""
    return [clean_item(item) for item in items]