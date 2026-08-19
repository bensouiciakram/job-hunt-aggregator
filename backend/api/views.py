"""AD-10 JSON API: register / list / test-fetch Sources.

Plain JsonResponse views (no DRF): the {ok, data|error} envelope is the
contract; `error` is a string for simple errors (e.g. "name already exists")
or a dict of per-field validation errors (e.g. {'url_pattern': ...}).
csrf_exempt because the Next.js frontend (Story 1.8) posts from an
origin-less localhost context; admin stays CSRF-protected.
"""

import json
from datetime import timedelta

from django.db import IntegrityError
from django.db.models import Q
from django.http import JsonResponse
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from collector.ports import AdapterNotFound
from collector.registry import get_adapter
from collector.test_fetch import TestFetchError, run_test_fetch
from judge.scoring import score as score_listing
from listings.models import FetchLog, Listing, Source
from listings.services import apply_to_listing


def _ok(data, status=200):
    return JsonResponse({'ok': True, 'data': data}, status=status)


def _err(error, status=400):
    return JsonResponse({'ok': False, 'error': error}, status=status)


def validate_config(config):
    """Config contract: url_pattern with {keywords}, listing_selector, keywords."""
    if not isinstance(config, dict):
        return {'config': 'must be a JSON object'}
    errors = {}
    url_pattern = config.get('url_pattern')
    if not isinstance(url_pattern, str) or not url_pattern.strip():
        errors['url_pattern'] = 'required'
    elif '{keywords}' not in url_pattern:
        errors['url_pattern'] = 'must contain the {keywords} placeholder'
    listing_selector = config.get('listing_selector')
    if not isinstance(listing_selector, str) or not listing_selector.strip():
        errors['listing_selector'] = 'required'
    keywords = config.get('keywords')
    if not isinstance(keywords, list) or not keywords:
        errors['keywords'] = 'must be a non-empty list'
    elif not all(isinstance(k, str) and k.strip() for k in keywords):
        errors['keywords'] = 'must be a list of non-empty strings'
    return errors


def _source_payload(source):
    return {
        'id': source.id,
        'name': source.name,
        'adapter_key': source.adapter_key,
        'config': source.config,
    }


@csrf_exempt
def sources(request):
    """POST /api/sources/ (register) and GET /api/sources/ (list)."""
    if request.method == 'POST':
        return register_source(request)
    if request.method == 'GET':
        return list_sources(request)
    return _err('method not allowed', status=405)


def register_source(request):
    """Create a Source (validated name/adapter/config)."""
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return _err('invalid JSON body')
    if not isinstance(payload, dict):
        return _err('request body must be a JSON object')

    name = payload.get('name')
    adapter_key = payload.get('adapter_key')
    config = payload.get('config', {})
    if not isinstance(name, str) or not name.strip():
        return _err({'name': 'required'})
    if len(name) > 255:
        return _err({'name': 'must be 255 characters or fewer'})
    if not isinstance(adapter_key, str) or not adapter_key.strip():
        return _err({'adapter_key': 'required'})
    if len(adapter_key) > 255:
        return _err({'adapter_key': 'must be 255 characters or fewer'})

    try:
        get_adapter(adapter_key)
    except AdapterNotFound:
        return _err(f'unknown adapter key: {adapter_key}')

    errors = validate_config(config)
    if errors:
        return _err(errors)

    if Source.objects.filter(name=name).exists():
        return _err('name already exists')
    try:
        source = Source.objects.create(
            name=name, adapter_key=adapter_key, config=config
        )
    except IntegrityError:
        return _err('name already exists')
    return _ok(_source_payload(source), status=201)


def list_sources(request):
    """List all registered sources."""
    return _ok([_source_payload(s) for s in Source.objects.all()])


@csrf_exempt
def test_fetch(request, pk):
    """POST /api/sources/<pk>/test-fetch/ — generic FR-1 test-fetch."""
    if request.method != 'POST':
        return _err('method not allowed', status=405)
    try:
        source = Source.objects.get(pk=pk)
    except Source.DoesNotExist:
        return _err('source not found', status=404)
    try:
        get_adapter(source.adapter_key)
    except AdapterNotFound:
        return _err(f'unknown adapter key: {source.adapter_key}')
    try:
        result = run_test_fetch(source)
    except TestFetchError as exc:
        return _err(str(exc))
    return _ok(result)


PER_PAGE = 25


def _listing_payload(listing):
    return {
        'id': listing.id,
        'title': listing.title,
        'company': listing.company,
        'url': listing.url,
        'published_at': listing.published_at,
        'source': (
            {
                'name': listing.source.name,
                'adapter_key': listing.source.adapter_key,
            }
            if listing.source
            else None
        ),
        'status': listing.status,
        'keywords': listing.keywords,
        'interest_score': score_listing(listing, settings.INTEREST_PROFILE),
    }


def _application_payload(application):
    return {
        'id': application.id,
        'listing': application.listing_id,
        'created_at': application.created_at,
        'outcome': application.outcome,
    }


def _last_sweep_at():
    """created_at of the latest ok=True 'pass' FetchLog, else None (AD-9)."""
    row = (
        FetchLog.objects.filter(stage='pass', ok=True)
        .order_by('-created_at', '-id')
        .first()
    )
    return row.created_at if row else None


@csrf_exempt
def apply(request, pk):
    """POST /api/listings/<pk>/apply/ — record an application (FR-4/FR-5).

    Idempotent: the second call for the same listing returns the existing
    Application with 200 — no duplicate, no error (AD-5/AD-10).
    """
    if request.method != 'POST':
        return _err('method not allowed', status=405)
    try:
        listing = Listing.objects.select_related('source').get(pk=pk)
    except (Listing.DoesNotExist, OverflowError):
        # OverflowError: a pk beyond SQLite's 64-bit range (e.g. 10**20)
        # raises instead of matching — keep the envelope contract.
        return _err('listing not found', status=404)
    application, _created = apply_to_listing(listing)
    data = {
        'application': _application_payload(application),
        'status': listing.status,
    }
    return JsonResponse({'ok': True, 'data': data, 'error': None}, status=200)


@csrf_exempt
def listings(request):
    """GET /api/listings/ — AD-9 paged list, AD-10 envelope.

    Sort: published_at DESC, id DESC (SQLite sorts NULLs last in DESC —
    pinned by test). per_page fixed at PER_PAGE. `page` out of range is
    an empty ok result, not an error; invalid `page` (non-int, <1) is a
    422-style envelope error.

    `bucket` (Epic 2): `new` = the "new since last visit" bucket —
    published_at within the AD-7 freshness window (now - 24h) AND status
    != 'applied'; absent or `all` = the full list. Invalid value → 422.
    """
    if request.method != 'GET':
        return _err('method not allowed', status=405)

    raw_page = request.GET.get('page', '1')
    try:
        page = int(raw_page)
    except (TypeError, ValueError):
        return _err('invalid page', status=422)
    if page < 1:
        return _err('invalid page', status=422)

    bucket = (request.GET.get('bucket') or '').strip()
    if 'bucket' in request.GET and bucket not in ('new', 'all'):
        return _err('invalid bucket', status=422)

    queryset = Listing.objects.select_related('source').order_by('-published_at', '-id')
    keyword = (request.GET.get('keyword') or '').strip()
    if keyword:
        queryset = queryset.filter(
            Q(title__icontains=keyword) | Q(company__icontains=keyword)
        )
    if bucket == 'new':
        queryset = queryset.filter(published_at__gte=now() - timedelta(hours=24)).exclude(
            status=Listing.Status.APPLIED
        )

    total = queryset.count()
    # Clamp after total is known, before the slice: an out-of-range page
    # (e.g. page=10**18) must not overflow SQLite's 64-bit OFFSET — it lands
    # on the last page instead of raising.
    page = min(page, max(1, (total + PER_PAGE - 1) // PER_PAGE))
    start = (page - 1) * PER_PAGE
    items = queryset[start : start + PER_PAGE]

    data = {
        'items': [_listing_payload(l) for l in items],
        'page': page,
        'has_next': start + PER_PAGE < total,
        'total': total,
        'last_sweep_at': _last_sweep_at(),
    }
    return JsonResponse(
        {'ok': True, 'data': data, 'error': None}, status=200
    )