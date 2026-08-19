"""Story 1.2 API tests: register / list / test-fetch with the AD-10 envelope.

Covers every matrix row (REGISTER_*, UNKNOWN_ADAPTER, TESTFETCH_*) with a
stub adapter and a stubbed fetcher — no network in these tests.
"""

import json
from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse

from collector import GoogleJobsStub
from collector.registry import clear, get_adapter, register
from listings.models import Source


class StubApiAdapter:
    """Test adapter implementing SourcePort (fetch/parse)."""

    def fetch(self, keywords):
        return []

    def parse(self, raw_items):
        return []


VALID_CONFIG = {
    'url_pattern': 'https://x/{keywords}',
    'listing_selector': 'div.job',
    'keywords': ['python'],
}


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def post_json(client, url, payload):
    return client.post(
        url,
        data=json.dumps(payload),
        content_type='application/json',
    )


class ApiTestCase(TestCase):
    """Registers the stub adapters per test so registry state never leaks.

    No `clear()`: the ouedkniss-jobs row is registered at import time
    (Story 1.5) and must survive for the collector full-stack tests; stub
    registrations are idempotent (re-registering a key overwrites it).
    """

    def setUp(self):
        register('stub-api-adapter')(StubApiAdapter)
        register('google-jobs')(GoogleJobsStub)


class RegisterSourceTests(ApiTestCase):
    def test_register_ok_returns_201_envelope(self):
        response = post_json(
            self.client,
            reverse('sources'),
            {
                'name': 'Demo',
                'adapter_key': 'stub-api-adapter',
                'config': VALID_CONFIG,
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(set(payload['data'].keys()), {'id', 'name', 'adapter_key', 'config'})
        self.assertEqual(payload['data']['name'], 'Demo')
        self.assertEqual(payload['data']['adapter_key'], 'stub-api-adapter')
        self.assertEqual(payload['data']['config'], VALID_CONFIG)
        self.assertEqual(Source.objects.filter(name='Demo').count(), 1)

    def test_register_google_jobs_placeholder_returns_201(self):
        response = post_json(
            self.client,
            reverse('sources'),
            {
                'name': 'Demo',
                'adapter_key': 'google-jobs',
                'config': VALID_CONFIG,
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['data']['adapter_key'], 'google-jobs')
        self.assertEqual(Source.objects.filter(adapter_key='google-jobs').count(), 1)

    def test_register_duplicate_name_returns_400_and_no_row(self):
        Source.objects.create(name='Demo', adapter_key='stub-api-adapter', config=VALID_CONFIG)
        response = post_json(
            self.client,
            reverse('sources'),
            {
                'name': 'Demo',
                'adapter_key': 'stub-api-adapter',
                'config': VALID_CONFIG,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {'ok': False, 'error': 'name already exists'})
        self.assertEqual(Source.objects.count(), 1)

    def test_register_missing_keywords_placeholder_returns_field_error(self):
        config = dict(VALID_CONFIG, url_pattern='https://x/{kw}')
        response = post_json(
            self.client,
            reverse('sources'),
            {'name': 'Demo', 'adapter_key': 'stub-api-adapter', 'config': config},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload['ok'])
        self.assertEqual(
            payload['error'],
            {'url_pattern': 'must contain the {keywords} placeholder'},
        )
        self.assertEqual(Source.objects.count(), 0)

    def test_register_empty_listing_selector_returns_field_error(self):
        config = dict(VALID_CONFIG, listing_selector='')
        response = post_json(
            self.client,
            reverse('sources'),
            {'name': 'Demo', 'adapter_key': 'stub-api-adapter', 'config': config},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['error'],
            {'listing_selector': 'required'},
        )
        self.assertEqual(Source.objects.count(), 0)

    def test_register_keywords_as_string_returns_field_error(self):
        config = dict(VALID_CONFIG, keywords='python')
        response = post_json(
            self.client,
            reverse('sources'),
            {'name': 'Demo', 'adapter_key': 'stub-api-adapter', 'config': config},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['error'],
            {'keywords': 'must be a non-empty list'},
        )
        self.assertEqual(Source.objects.count(), 0)

    def test_register_empty_keywords_list_returns_field_error(self):
        config = dict(VALID_CONFIG, keywords=[])
        response = post_json(
            self.client,
            reverse('sources'),
            {'name': 'Demo', 'adapter_key': 'stub-api-adapter', 'config': config},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['error'],
            {'keywords': 'must be a non-empty list'},
        )
        self.assertEqual(Source.objects.count(), 0)

    def test_register_blank_keyword_returns_field_error(self):
        config = dict(VALID_CONFIG, keywords=['python', ' '])
        response = post_json(
            self.client,
            reverse('sources'),
            {'name': 'Demo', 'adapter_key': 'stub-api-adapter', 'config': config},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['error'],
            {'keywords': 'must be a list of non-empty strings'},
        )
        self.assertEqual(Source.objects.count(), 0)

    def test_register_name_too_long_returns_field_error(self):
        response = post_json(
            self.client,
            reverse('sources'),
            {
                'name': 'x' * 256,
                'adapter_key': 'stub-api-adapter',
                'config': VALID_CONFIG,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['error'],
            {'name': 'must be 255 characters or fewer'},
        )
        self.assertEqual(Source.objects.count(), 0)

    def test_register_adapter_key_too_long_returns_field_error(self):
        response = post_json(
            self.client,
            reverse('sources'),
            {
                'name': 'Demo',
                'adapter_key': 'x' * 256,
                'config': VALID_CONFIG,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['error'],
            {'adapter_key': 'must be 255 characters or fewer'},
        )
        self.assertEqual(Source.objects.count(), 0)

    def test_register_missing_name_returns_field_error(self):
        response = post_json(
            self.client,
            reverse('sources'),
            {'adapter_key': 'stub-api-adapter', 'config': VALID_CONFIG},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], {'name': 'required'})
        self.assertEqual(Source.objects.count(), 0)

    def test_register_missing_adapter_key_returns_field_error(self):
        response = post_json(
            self.client,
            reverse('sources'),
            {'name': 'Demo', 'config': VALID_CONFIG},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], {'adapter_key': 'required'})
        self.assertEqual(Source.objects.count(), 0)

    def test_register_non_dict_config_returns_field_error(self):
        response = post_json(
            self.client,
            reverse('sources'),
            {'name': 'Demo', 'adapter_key': 'stub-api-adapter', 'config': 'nope'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], {'config': 'must be a JSON object'})
        self.assertEqual(Source.objects.count(), 0)

    def test_register_unknown_adapter_returns_400(self):
        response = post_json(
            self.client,
            reverse('sources'),
            {'name': 'Demo', 'adapter_key': 'no-such-adapter', 'config': VALID_CONFIG},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {'ok': False, 'error': 'unknown adapter key: no-such-adapter'},
        )
        self.assertEqual(Source.objects.count(), 0)

    def test_register_invalid_json_returns_400(self):
        response = self.client.post(
            reverse('sources'),
            data='{not json',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {'ok': False, 'error': 'invalid JSON body'})


class ListSourcesTests(ApiTestCase):
    def test_empty_table_returns_empty_list(self):
        response = self.client.get(reverse('sources'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True, 'data': []})

    def test_lists_registered_sources(self):
        Source.objects.create(name='Demo', adapter_key='stub-api-adapter', config=VALID_CONFIG)
        response = self.client.get(reverse('sources'))

        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(len(payload['data']), 1)
        self.assertEqual(
            set(payload['data'][0].keys()),
            {'id', 'name', 'adapter_key', 'config'},
        )
        self.assertEqual(payload['data'][0]['name'], 'Demo')


class RegistryResolutionTests(ApiTestCase):
    def test_google_jobs_placeholder_resolves(self):
        self.assertIs(get_adapter('google-jobs'), GoogleJobsStub)


class TestFetchApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.source = Source.objects.create(
            name='Demo', adapter_key='stub-api-adapter', config=VALID_CONFIG
        )

    def test_fetch_ok_returns_sample_and_snapshot(self):
        with patch(
            'collector.test_fetch.requests.get',
            return_value=FakeResponse('<html><div class="job">Job A</div></html>'),
        ):
            response = self.client.post(reverse('test-fetch', args=[self.source.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(
            payload['data'],
            {
                'sample': [{'html': '<div class="job">Job A</div>'}],
                'raw_snapshot': '<html><div class="job">Job A</div></html>',
            },
        )

    def test_fetch_mismatch_returns_notice(self):
        with patch(
            'collector.test_fetch.requests.get',
            return_value=FakeResponse('<html><div class="other">Job A</div></html>'),
        ):
            response = self.client.post(reverse('test-fetch', args=[self.source.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['data']['sample'], [])
        self.assertEqual(payload['data']['notice'], 'selector-mismatch')
        self.assertEqual(
            payload['data']['raw_snapshot'],
            '<html><div class="other">Job A</div></html>',
        )

    def test_fetch_error_returns_error_envelope(self):
        def raise_connection_error(url, **kwargs):
            raise ConnectionError('connection refused')

        with patch('collector.test_fetch.requests.get', side_effect=raise_connection_error):
            response = self.client.post(reverse('test-fetch', args=[self.source.id]))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {'ok': False, 'error': 'fetch failed: connection refused'},
        )

    def test_unknown_adapter_returns_400(self):
        source = Source.objects.create(
            name='Broken', adapter_key='no-such-adapter', config=VALID_CONFIG
        )
        with patch('collector.test_fetch.requests.get', return_value=FakeResponse('<html/>')):
            response = self.client.post(reverse('test-fetch', args=[source.id]))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {'ok': False, 'error': 'unknown adapter key: no-such-adapter'},
        )

    def test_missing_source_returns_404(self):
        response = self.client.post(reverse('test-fetch', args=[9999]))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {'ok': False, 'error': 'source not found'})

    def test_get_on_test_fetch_returns_405(self):
        response = self.client.get(reverse('test-fetch', args=[self.source.id]))

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json(), {'ok': False, 'error': 'method not allowed'})

    def test_wrong_method_on_sources_returns_405_envelope(self):
        response = self.client.put(reverse('sources'))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json(), {'ok': False, 'error': 'method not allowed'})