"""Pure stage: coerce raw items to dicts, pick canonical keys.

The raw item itself becomes `raw_snapshot`, so every persisted Listing
keeps its raw snapshot (AD-1). Extra keys in a raw item are tolerated:
they are never picked into the canonical shape, and never crash the
stage.
"""

# AD-1 canonical field set (except raw_snapshot, which is derived).
CANONICAL_KEYS = ('title', 'company', 'url', 'published_at', 'keywords')


def extract_item(raw_item):
    """Coerce one raw item to the canonical dict shape.

    Raises TypeError for non-dict raw items (a structural contract
    violation, not a data-quality quirk — those surface at validate).
    """
    if not isinstance(raw_item, dict):
        raise TypeError(
            f'raw item must be a dict, got {type(raw_item).__name__}'
        )
    item = {key: raw_item.get(key) for key in CANONICAL_KEYS}
    item['raw_snapshot'] = dict(raw_item)
    return item


def extract(raw_items):
    """Apply extract_item to every raw item (pure, list-preserving)."""
    return [extract_item(item) for item in raw_items]