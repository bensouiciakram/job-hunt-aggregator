"""AD-10 JSON API: register / list / test-fetch Sources.

Plain JsonResponse views (no DRF): the {ok, data|error} envelope is the
contract; `error` is a string for simple errors (e.g. "name already exists")
or a dict of per-field validation errors (e.g. {'url_pattern': ...}).
csrf_exempt because the Next.js frontend (Story 1.8) posts from an
origin-less localhost context; admin stays CSRF-protected.
"""

import json

from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from collector.ports import AdapterNotFound
from collector.registry import get_adapter
from collector.test_fetch import TestFetchError, run_test_fetch
from listings.models import Source


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