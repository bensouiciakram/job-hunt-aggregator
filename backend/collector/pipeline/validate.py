"""Pure stage: canonical completeness.

Requires title, company, and a http(s) url with a real host; enforces
model field length limits so a guaranteed DataError can never reach
persist. Returns (valid, errors) instead of raising, so the
orchestrator can skip invalid items while valid ones still persist
(item-level isolation).
"""

from urllib.parse import urlparse

# Model field limits (listings/models.py) — enforced here to fail early.
_MAX_TITLE = 500
_MAX_COMPANY = 255
_MAX_URL = 2048


def _item_error(item):
    """Return an error message for one item, or None when valid."""
    title = item.get('title')
    if not isinstance(title, str) or not title.strip():
        return 'title is required'
    if len(title) > _MAX_TITLE:
        return f'title exceeds {_MAX_TITLE} characters'
    company = item.get('company')
    if not isinstance(company, str) or not company.strip():
        return 'company is required'
    if len(company) > _MAX_COMPANY:
        return f'company exceeds {_MAX_COMPANY} characters'
    url = item.get('url')
    if not isinstance(url, str) or not url.strip():
        return 'url is required'
    if len(url) > _MAX_URL:
        return f'url exceeds {_MAX_URL} characters'
    try:
        parsed = urlparse(url)
    except ValueError:
        return 'url must be a valid http(s) url'
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return 'url must be a valid http(s) url'
    return None


def validate(items):
    """Return `(valid_items, errors)`; errors are (index, item, message).

    `published_at` is lenient by design — normalize already turned
    unparseable dates into None, so no date validation happens here.
    """
    valid = []
    errors = []
    for index, item in enumerate(items):
        message = _item_error(item)
        if message:
            errors.append((index, item, message))
        else:
            valid.append(item)
    return valid, errors