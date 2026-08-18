"""FR-2 collection loop: resolve adapter -> fetch -> parse -> pure stages
-> repository.

AD-6 failure isolation: every failure (config, fetch, parse, stage,
repository) writes a FetchLog {source, stage, ok, error} and
collect_source never raises; one bad source never stops others. The
ok=True row is written ONLY when the pass had no failures at all —
zero items with zero errors still counts as a successful pass.
"""

from listings.models import FetchLog

from .pipeline import clean_item, dedupe_item, extract_item, normalize_item, validate
from .registry import get_adapter
from .repository import ListingRepository

# Pipeline stage names for FetchLog (free-form strings, Design Notes).
_ITEM_STAGES = (
    (extract_item, 'extract'),
    (clean_item, 'clean'),
    (normalize_item, 'normalize'),
    (dedupe_item, 'dedupe'),
)


def _log(source, stage, ok, error=''):
    """Write a FetchLog row; must itself never raise (AD-6)."""
    try:
        FetchLog.objects.create(source=source, stage=stage, ok=ok, error=error)
    except Exception:
        pass


def _validated_keywords(source):
    """Validate the Keyword Set in source.config; None + message on violation."""
    config = source.config if isinstance(source.config, dict) else {}
    keywords = config.get('keywords')
    if not isinstance(keywords, list) or not keywords:
        return None, 'keywords must be a non-empty list'
    if not all(isinstance(k, str) and k.strip() for k in keywords):
        return None, 'keywords must be a list of non-blank strings'
    return keywords, None


def _item_context(index, item):
    """Item context for FetchLog error text: `item <index> (<title>)`."""
    if isinstance(item, dict):
        title = item.get('title')
        if isinstance(title, str) and title.strip():
            return f'item {index} ({title.strip()})'
    return f'item {index}'


def collect_source(source):
    """Collect one Source end-to-end; never raises (AD-6).

    Returns the number of Listings created on this pass (idempotent
    re-collection returns 0). An ok=True FetchLog row is written only
    when the pass completed without any failure (config/fetch/parse/
    stage/validate/persist); a pass with zero items and zero errors
    still counts as successful.
    """
    state = {'stage': 'fetch'}
    try:
        return _collect(source, state)
    except Exception as exc:  # last-resort guard: labelled with the stage in flight
        _log(source, state['stage'], False, str(exc))
        return 0


def _collect(source, state):
    repository = ListingRepository()
    failed = False

    state['stage'] = 'config'
    keywords, error = _validated_keywords(source)
    if keywords is None:
        _log(source, 'config', False, error)
        return 0

    state['stage'] = 'fetch'
    try:
        adapter = get_adapter(source.adapter_key)()
        raw = adapter.fetch(keywords)
        if raw is None:
            raise TypeError('adapter.fetch returned None')
        raw_items = list(raw)
    except Exception as exc:
        _log(source, 'fetch', False, f'fetch failed: {exc}')
        return 0

    state['stage'] = 'parse'
    try:
        parsed = adapter.parse(raw_items)
        if parsed is None:
            raise TypeError('adapter.parse returned None')
        items = list(parsed)
    except Exception as exc:
        _log(source, 'parse', False, f'parse failed: {exc}')
        return 0

    # Pure stages, item-by-item: one bad item is skipped with its own
    # FetchLog entry; valid items still flow on (item-level isolation).
    pipeline_items = []
    for index, raw_item in enumerate(items):
        item = raw_item
        for stage_fn, stage_name in _ITEM_STAGES:
            state['stage'] = stage_name
            try:
                item = stage_fn(item)
            except Exception as exc:
                failed = True
                _log(
                    source,
                    stage_name,
                    False,
                    f'{_item_context(index, item)}: {exc}',
                )
                item = None
                break
        if item is not None:
            pipeline_items.append(item)

    state['stage'] = 'validate'
    valid, errors = validate(pipeline_items)
    for index, _item, message in errors:
        failed = True
        _log(source, 'validate', False, f'{_item_context(index, _item)}: {message}')

    state['stage'] = 'persist'
    created = 0
    for index, item in enumerate(valid):
        try:
            _listing, was_created = repository.upsert(item, source)
            created += int(was_created)
        except Exception as exc:
            failed = True
            _log(
                source,
                'persist',
                False,
                f'{_item_context(index, item)}: {exc}',
            )

    if not failed:
        _log(source, 'persist', True, '')
    return created