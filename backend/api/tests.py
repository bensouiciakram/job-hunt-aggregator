"""Story 1.2 API tests: register / list / test-fetch with the AD-10 envelope.

Covers every matrix row (REGISTER_*, UNKNOWN_ADAPTER, TESTFETCH_*) with a
stub adapter and a stubbed fetcher — no network in these tests.
"""

import json
from datetime import timedelta
from unittest.mock import Mock, patch

from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from collector.adapters.google_jobs import GoogleJobsAdapter
from collector.pipeline import compute_fingerprint
from collector.registry import clear, get_adapter, register
from judge.scoring import score, score_text
from listings.models import FetchLog, Listing, Source


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

    No `clear()`: the ouedkniss-jobs and google-jobs rows are registered
    at import time (Story 1.5/1.6) and must survive for the collector
    full-stack tests; stub registrations are idempotent (re-registering
    a key overwrites it).
    """

    def setUp(self):
        register('stub-api-adapter')(StubApiAdapter)


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

    def test_register_google_jobs_returns_201(self):
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
    def test_google_jobs_resolves_to_registered_adapter(self):
        self.assertIs(get_adapter('google-jobs'), GoogleJobsAdapter)


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


class ListingsApiTests(ApiTestCase):
    """Story 1.8 GET /api/listings/ tests: AD-9 sort/paging/last_sweep_at + AD-10 envelope."""

    def _listing(self, **overrides):
        defaults = {
            'title': 'Job',
            'company': 'Acme',
            'url': 'https://example.com/job',
            'published_at': timezone.now(),
        }
        defaults.update(overrides)
        defaults['dedup_fingerprint'] = compute_fingerprint(
            defaults['title'], defaults['company'], defaults['url']
        )
        return Listing.objects.create(**defaults)

    def test_list_default_sorted_and_envelope(self):
        base = timezone.now()
        for i in range(25):
            self._listing(
                title=f'Job {i}',
                url=f'https://example.com/{i}',
                published_at=base - timedelta(days=i),
            )
        tie_a = self._listing(title='Tie A', published_at=base)
        tie_b = self._listing(title='Tie B', published_at=base)

        response = self.client.get(reverse('listings'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertIsNone(payload['error'])
        self.assertEqual(set(payload.keys()), {'ok', 'data', 'error'})
        data = payload['data']
        self.assertEqual(
            set(data.keys()), {'items', 'page', 'has_next', 'total', 'last_sweep_at'}
        )
        self.assertEqual(data['page'], 1)
        self.assertEqual(len(data['items']), 25)
        self.assertTrue(data['has_next'])
        self.assertEqual(data['total'], 27)
        titles = [item['title'] for item in data['items']]
        self.assertEqual(titles[:3], ['Tie B', 'Tie A', 'Job 0'])
        self.assertEqual(titles[-1], 'Job 22')

    def test_item_shape_excludes_raw_snapshot(self):
        source = Source.objects.create(
            name='Demo', adapter_key='stub-api-adapter', config=VALID_CONFIG
        )
        self._listing(
            title='Python Dev',
            company='Acme',
            url='https://example.com/1',
            keywords=['python'],
            source=source,
            raw_snapshot={'secret': 'not-for-the-list'},
        )

        item = self.client.get(reverse('listings')).json()['data']['items'][0]

        self.assertEqual(
            set(item.keys()),
            {'id', 'title', 'company', 'url', 'published_at', 'source', 'status',
             'keywords', 'interest_score'},
        )
        self.assertEqual(item['source'], {'name': 'Demo', 'adapter_key': 'stub-api-adapter'})
        self.assertEqual(item['status'], 'new')
        self.assertEqual(item['keywords'], ['python'])
        self.assertNotIn('raw_snapshot', item)

    def test_null_source_rendered_null(self):
        self._listing(source=None)
        item = self.client.get(reverse('listings')).json()['data']['items'][0]
        self.assertIsNone(item['source'])

    def test_page_2_returns_items_26_50(self):
        base = timezone.now()
        for i in range(50):
            self._listing(
                title=f'Job {i:02d}',
                published_at=base - timedelta(days=i),
            )

        data = self.client.get(reverse('listings'), {'page': 2}).json()['data']

        self.assertEqual(len(data['items']), 25)
        self.assertFalse(data['has_next'])
        self.assertEqual(data['total'], 50)
        titles = [item['title'] for item in data['items']]
        self.assertEqual(titles[0], 'Job 25')
        self.assertEqual(titles[-1], 'Job 49')

    def test_page_out_of_range_clamped_to_last_page(self):
        self._listing(title='Only')

        response = self.client.get(reverse('listings'), {'page': 999})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertIsNone(payload['error'])
        self.assertEqual(payload['data']['page'], 1)
        self.assertEqual([item['title'] for item in payload['data']['items']], ['Only'])
        self.assertFalse(payload['data']['has_next'])
        self.assertEqual(payload['data']['total'], 1)

    def test_page_huge_clamped(self):
        response = self.client.get(reverse('listings'), {'page': 10**18})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertIsNone(payload['error'])
        self.assertEqual(payload['data']['items'], [])
        self.assertEqual(payload['data']['page'], 1)
        self.assertEqual(payload['data']['total'], 0)

    def test_invalid_page_non_int_returns_envelope_error(self):
        response = self.client.get(reverse('listings'), {'page': 'abc'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {'ok': False, 'error': 'invalid page'})

    def test_invalid_page_zero_returns_envelope_error(self):
        response = self.client.get(reverse('listings'), {'page': 0})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {'ok': False, 'error': 'invalid page'})

    def test_keyword_matches_title_or_company_icontains(self):
        self._listing(title='Python Developer', company='Acme')
        self._listing(title='Backend Dev', company='PythonWorks')
        self._listing(title='Dev', company='Acme')

        data = self.client.get(reverse('listings'), {'keyword': 'pytHon'}).json()['data']

        titles = {item['title'] for item in data['items']}
        self.assertEqual(titles, {'Python Developer', 'Backend Dev'})
        self.assertEqual(data['total'], 2)

    def test_keyword_no_match_returns_empty_ok(self):
        self._listing(title='Dev', company='Acme')
        data = self.client.get(reverse('listings'), {'keyword': 'zigzag'}).json()['data']
        self.assertEqual(data['items'], [])
        self.assertEqual(data['total'], 0)
        self.assertFalse(data['has_next'])

    def test_null_published_at_sorts_last(self):
        self._listing(title='Newest', published_at=timezone.now())
        self._listing(title='Older', published_at=timezone.now() - timedelta(days=1))
        null_row = self._listing(title='No Date', published_at=None)

        items = self.client.get(reverse('listings')).json()['data']['items']

        self.assertEqual([item['title'] for item in items], ['Newest', 'Older', 'No Date'])
        self.assertIsNone(items[-1]['published_at'])

    def test_last_sweep_at_from_latest_ok_pass_row(self):
        FetchLog.objects.create(stage='fail', ok=True)
        FetchLog.objects.create(stage='pass', ok=False)
        old_stamp = timezone.now() - timedelta(hours=2)
        old = FetchLog.objects.create(stage='pass', ok=True)
        FetchLog.objects.filter(pk=old.pk).update(created_at=old_stamp)
        latest_stamp = timezone.now()
        latest = FetchLog.objects.create(stage='pass', ok=True)
        FetchLog.objects.filter(pk=latest.pk).update(created_at=latest_stamp)

        data = self.client.get(reverse('listings')).json()['data']

        self.assertEqual(data['last_sweep_at'], json.loads(DjangoJSONEncoder().encode(latest_stamp)))

    def test_last_sweep_at_null_when_no_ok_pass(self):
        FetchLog.objects.create(stage='pass', ok=False)
        FetchLog.objects.create(stage='fail', ok=True)

        data = self.client.get(reverse('listings')).json()['data']

        self.assertIsNone(data['last_sweep_at'])

    def test_wrong_method_returns_405_envelope(self):
        response = self.client.post(reverse('listings'))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json(), {'ok': False, 'error': 'method not allowed'})


class CorsTests(TestCase):
    """Story 1.8 CORS: allowed dev origins echoed, disallowed origins get nothing."""

    def test_allowed_origin_localhost_echoed(self):
        response = self.client.get(
            reverse('listings'), HTTP_ORIGIN='http://localhost:3000'
        )
        self.assertEqual(
            response.headers.get('Access-Control-Allow-Origin'), 'http://localhost:3000'
        )

    def test_allowed_origin_127_echoed(self):
        response = self.client.get(
            reverse('listings'), HTTP_ORIGIN='http://127.0.0.1:3000'
        )
        self.assertEqual(
            response.headers.get('Access-Control-Allow-Origin'), 'http://127.0.0.1:3000'
        )

    def test_disallowed_origin_gets_no_header(self):
        response = self.client.get(reverse('listings'), HTTP_ORIGIN='http://evil.example')
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)

    def test_preflight_allowed_origin(self):
        response = self.client.options(
            reverse('listings'),
            HTTP_ORIGIN='http://localhost:3000',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='GET',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get('Access-Control-Allow-Origin'), 'http://localhost:3000'
        )

    def test_preflight_disallowed_origin_gets_no_header(self):
        response = self.client.options(
            reverse('listings'),
            HTTP_ORIGIN='https://evil.example',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='GET',
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)


class ApplyCorsTests(TestCase):
    """Story 2.1: the apply POST is cross-origin from :3000 (Story 2.2 seam)."""

    def test_preflight_apply_post_allowed_origin(self):
        response = self.client.options(
            reverse('apply', args=[1]),
            HTTP_ORIGIN='http://localhost:3000',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get('Access-Control-Allow-Origin'), 'http://localhost:3000'
        )
        self.assertIn('POST', response.headers.get('Access-Control-Allow-Methods', ''))

    def test_apply_with_origin_echoed(self):
        from listings.models import Listing

        listing = Listing.objects.create(
            title='Job',
            company='Acme',
            url='https://example.com/job',
            published_at=timezone.now(),
            dedup_fingerprint=compute_fingerprint('Job', 'Acme', 'https://example.com/job'),
        )
        response = self.client.post(
            reverse('apply', args=[listing.id]),
            data=json.dumps({}),
            content_type='application/json',
            HTTP_ORIGIN='http://localhost:3000',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get('Access-Control-Allow-Origin'), 'http://localhost:3000'
        )

    def test_preflight_apply_post_disallowed_origin_gets_no_header(self):
        response = self.client.options(
            reverse('apply', args=[1]),
            HTTP_ORIGIN='https://evil.example',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)


class ApplicationApiTests(TestCase):
    """Story 2.1 POST /api/listings/<id>/apply/ — FR-4/FR-5, AD-4/AD-5/AD-10."""

    def _listing(self, **overrides):
        defaults = {
            'title': 'Job',
            'company': 'Acme',
            'url': 'https://example.com/job',
            'published_at': timezone.now(),
        }
        defaults.update(overrides)
        defaults['dedup_fingerprint'] = compute_fingerprint(
            defaults['title'], defaults['company'], defaults['url']
        )
        return Listing.objects.create(**defaults)

    def test_apply_creates_record_and_flips_status(self):
        listing = self._listing()

        response = self.client.post(reverse('apply', args=[listing.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(payload.keys()), {'ok', 'data', 'error'})
        self.assertTrue(payload['ok'])
        self.assertIsNone(payload['error'])
        application = payload['data']['application']
        self.assertEqual(
            set(application.keys()), {'id', 'listing', 'created_at', 'outcome'}
        )
        self.assertEqual(application['listing'], listing.id)
        self.assertIsNone(application['outcome'])
        self.assertEqual(payload['data']['status'], 'applied')
        listing.refresh_from_db()
        self.assertEqual(listing.status, 'applied')
        self.assertEqual(listing.application.listing_id, listing.id)

    def test_reapply_is_idempotent_same_record_no_duplicate(self):
        listing = self._listing()
        first = self.client.post(reverse('apply', args=[listing.id])).json()['data']
        second = self.client.post(reverse('apply', args=[listing.id])).json()['data']

        self.assertEqual(first, second)
        self.assertEqual(first['application']['id'], second['application']['id'])
        self.assertEqual(
            first['application']['created_at'], second['application']['created_at']
        )
        self.assertEqual(second['status'], 'applied')
        listing.refresh_from_db()
        self.assertEqual(listing.status, 'applied')

    def test_reapply_does_not_downgrade_status(self):
        listing = self._listing()
        self.client.post(reverse('apply', args=[listing.id]))
        listing.status = 'applied'
        listing.save(update_fields=['status'])

        payload = self.client.post(reverse('apply', args=[listing.id])).json()
        self.assertEqual(payload['data']['status'], 'applied')
        self.assertEqual(listing.application.outcome, None)

    def test_apply_unknown_listing_returns_404_envelope(self):
        response = self.client.post(reverse('apply', args=[999999]))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(), {'ok': False, 'error': 'listing not found'}
        )

    def test_apply_huge_pk_returns_404_envelope_not_500(self):
        response = self.client.post(reverse('apply', args=[10**20]))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(), {'ok': False, 'error': 'listing not found'}
        )

    def test_apply_wrong_method_returns_405(self):
        listing = self._listing()
        response = self.client.get(reverse('apply', args=[listing.id]))
        self.assertEqual(response.status_code, 405)

    def test_db_level_unique_constraint_on_listing(self):
        from django.db import IntegrityError

        from listings.models import Application

        listing = self._listing()
        Application.objects.create(listing=listing)
        with self.assertRaises(IntegrityError):
            Application.objects.create(listing=listing)


class BucketApiTests(TestCase):
    """Story 2.1 GET /api/listings/?bucket= — the 'new since last visit' bucket."""

    def _listing(self, **overrides):
        defaults = {
            'title': 'Job',
            'company': 'Acme',
            'url': 'https://example.com/job',
            'published_at': timezone.now(),
        }
        defaults.update(overrides)
        defaults['dedup_fingerprint'] = compute_fingerprint(
            defaults['title'], defaults['company'], defaults['url']
        )
        return Listing.objects.create(**defaults)

    def test_new_bucket_returns_fresh_unapplied_only(self):
        self._listing(title='Fresh New', url='https://example.com/1')
        fresh_applied = self._listing(
            title='Fresh Applied', url='https://example.com/2'
        )
        fresh_applied.status = 'applied'
        fresh_applied.save(update_fields=['status'])
        self._listing(
            title='Old New',
            url='https://example.com/3',
            published_at=timezone.now() - timedelta(days=3),
        )

        response = self.client.get(reverse('listings'), {'bucket': 'new'})
        payload = response.json()
        self.assertEqual(set(payload.keys()), {'ok', 'data', 'error'})
        self.assertTrue(payload['ok'])
        self.assertIsNone(payload['error'])
        data = payload['data']
        titles = [item['title'] for item in data['items']]
        self.assertEqual(titles, ['Fresh New'])
        self.assertEqual(data['total'], 1)

    def test_new_bucket_combined_with_keyword(self):
        self._listing(title='Python Dev Fresh', url='https://example.com/1')
        self._listing(title='Python Dev Old', url='https://example.com/2',
                      published_at=timezone.now() - timedelta(days=3))
        self._listing(title='Rust Fresh', url='https://example.com/3')

        data = self.client.get(
            reverse('listings'), {'bucket': 'new', 'keyword': 'python'}
        ).json()['data']

        titles = [item['title'] for item in data['items']]
        self.assertEqual(titles, ['Python Dev Fresh'])
        self.assertEqual(data['total'], 1)

    def test_new_bucket_pages_within_the_filtered_set(self):
        base = timezone.now()
        for i in range(30):
            self._listing(
                title=f'Fresh {i:02d}',
                url=f'https://example.com/{i}',
                published_at=base - timedelta(minutes=i),
            )
        self._listing(
            title='Old', url='https://example.com/old',
            published_at=base - timedelta(days=3),
        )

        data = self.client.get(
            reverse('listings'), {'bucket': 'new', 'page': 2}
        ).json()['data']

        self.assertEqual(data['total'], 30)
        self.assertFalse(data['has_next'])
        self.assertEqual(data['page'], 2)
        self.assertEqual(len(data['items']), 5)

    def test_new_bucket_excludes_null_published_at(self):
        null_listing = self._listing(
            title='No Date', url='https://example.com/null', published_at=None
        )
        self._listing(title='Fresh', url='https://example.com/fresh')

        new_titles = [
            item['title']
            for item in self.client.get(reverse('listings'), {'bucket': 'new'}).json()['data']['items']
        ]
        self.assertEqual(new_titles, ['Fresh'])
        all_titles = {
            item['title']
            for item in self.client.get(reverse('listings'), {'bucket': 'all'}).json()['data']['items']
        }
        self.assertIn('No Date', all_titles)
        self.assertEqual(null_listing.status, 'new')

    def test_all_bucket_returns_everything_including_applied(self):
        self._listing(title='Fresh New', url='https://example.com/1')
        fresh_applied = self._listing(
            title='Fresh Applied', url='https://example.com/2'
        )
        fresh_applied.status = 'applied'
        fresh_applied.save(update_fields=['status'])
        self._listing(
            title='Old New',
            url='https://example.com/3',
            published_at=timezone.now() - timedelta(days=3),
        )

        data = self.client.get(reverse('listings'), {'bucket': 'all'}).json()['data']

        titles = {item['title'] for item in data['items']}
        self.assertEqual(titles, {'Fresh New', 'Fresh Applied', 'Old New'})
        self.assertEqual(data['total'], 3)

    def test_bucket_absent_unchanged_default_behavior(self):
        self._listing(title='Fresh New', url='https://example.com/1')
        data = self.client.get(reverse('listings')).json()['data']
        self.assertEqual(data['total'], 1)

    def test_invalid_bucket_returns_422_envelope(self):
        response = self.client.get(reverse('listings'), {'bucket': 'weird'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {'ok': False, 'error': 'invalid bucket'})


class ScoringTests(TestCase):
    """Story 3.1 pure interest scoring: weighting, sanity, purity, payload."""

    PROFILE = {
        'tech_stack': ['python', 'django', 'react', 'nodejs'],
        'domains': ['web scraping', 'api', 'backend'],
        'project_types': ['remote', 'freelance'],
    }

    def test_domain_outscores_stack_alone(self):
        domain_only = score_text(
            'Web Scraping API Developer',
            ['python', 'remote'],
            self.PROFILE,
        )
        stack_only = score_text(
            'Python React Developer',
            ['python'],
            self.PROFILE,
        )
        self.assertGreater(domain_only, stack_only)

    def test_domain_matches_weigh_more_than_stack_matches(self):
        self.assertEqual(score_text('Web Scraping Engineer', [], self.PROFILE), 58)
        self.assertEqual(score_text('Python Engineer', [], self.PROFILE), 54)

    def test_absurd_stack_penalized(self):
        title = 'Full-stack NodeJS Python Golang Java Engineer'
        profile = {**self.PROFILE, 'tech_stack': self.PROFILE['tech_stack'] + ['golang', 'java']}
        self.assertEqual(score_text(title, [], profile), 26)

    def test_empty_title_penalized(self):
        self.assertEqual(score_text('', [], self.PROFILE), 35)
        self.assertEqual(score_text('  ', [], self.PROFILE), 35)
        self.assertEqual(score_text('Dev', [], self.PROFILE), 35)

    def test_no_match_neutral_baseline(self):
        self.assertEqual(score_text('Cashier Wanted', [], self.PROFILE), 50)

    def test_clamp_high_and_low(self):
        many = {'tech_stack': ['alpha', 'bravo', 'charlie'],
                'domains': ['xray', 'yacht', 'zebra', 'lima', 'mike', 'november', 'oscar'],
                'project_types': []}
        self.assertEqual(
            score_text('xray yacht zebra lima mike november oscar', [], many), 100
        )
        self.assertEqual(score_text('', [], many), 35)

    def test_api_does_not_match_inside_scraping(self):
        self.assertEqual(score_text('Scraping Engineer', [], self.PROFILE), 50)
        self.assertEqual(score_text('API Engineer', [], self.PROFILE), 58)

    def test_multiword_term_requires_adjacency(self):
        self.assertEqual(score_text('Web Content Scraping', [], self.PROFILE), 50)
        self.assertEqual(score_text('Web Scraping Engineer', [], self.PROFILE), 58)

    def test_nextjs_style_term_matches_punctuated_title(self):
        profile = {'tech_stack': ['next.js'], 'domains': [], 'project_types': []}
        self.assertEqual(score_text('Next.js Developer', [], profile), 54)

    def test_spelling_variants_collapse_to_one_match(self):
        profile = {'domains': ['full-stack', 'fullstack'], 'tech_stack': [], 'project_types': []}
        self.assertEqual(score_text('Full-stack Fullstack Engineer', [], profile), 58)

    def test_bad_keywords_and_profile_shapes_do_not_crash(self):
        self.assertEqual(score_text('Python Dev', 'not-a-list', self.PROFILE), 54)
        self.assertEqual(score_text('Python Dev', [42, None], self.PROFILE), 54)
        self.assertEqual(score_text('Python Dev', ['python'], {'tech_stack': 'nope'}), 50)
        self.assertEqual(score_text('Python Dev', ['python'], {'tech_stack': [7]}), 50)
        self.assertEqual(score_text('Python Dev', ['python'], None), 50)

    def test_punctuation_only_title_penalized(self):
        self.assertEqual(score_text('....', [], self.PROFILE), 35)

    def test_term_in_both_lists_counts_once(self):
        profile = {'tech_stack': ['api'], 'domains': ['api'], 'project_types': []}
        self.assertEqual(score_text('API Engineer', [], profile), 58)

    def test_real_profile_pins_concrete_scores(self):
        from django.conf import settings

        real = settings.INTEREST_PROFILE
        self.assertEqual(score_text('Python Django React Node.js Developer', [], real), 26)
        self.assertEqual(score_text('Web Scraping API Developer', [], real), 66)

    def test_real_profile_is_structurally_sound(self):
        from django.conf import settings

        real = settings.INTEREST_PROFILE
        for key in ('tech_stack', 'domains', 'project_types'):
            self.assertIn(key, real)
            self.assertIsInstance(real[key], list)
            self.assertTrue(real[key])
            self.assertTrue(all(isinstance(t, str) and t.strip() for t in real[key]))
        self.assertEqual(len(real['tech_stack']), len(set(real['tech_stack'])))
        self.assertEqual(len(real['domains']), len(set(real['domains'])))
        self.assertEqual(len(real['project_types']), len(set(real['project_types'])))

    def test_keyword_duplicate_collapsed(self):
        one = score_text('Python Backend', ['python', 'backend'], self.PROFILE)
        two = score_text('Python Backend', ['backend'], self.PROFILE)
        self.assertEqual(one, two)

    def test_purity_no_mutation(self):
        listing = Listing.objects.create(
            title='Python Developer',
            company='Acme',
            url='https://example.com/job',
            dedup_fingerprint='fp-1',
            status='new',
            seen_sources=['ouedkniss'],
            raw_snapshot={'a': 1},
        )
        before = (
            listing.title,
            listing.company,
            listing.status,
            listing.dedup_fingerprint,
            listing.seen_sources,
            listing.raw_snapshot,
        )
        score(listing, self.PROFILE)
        listing.refresh_from_db()
        after = (
            listing.title,
            listing.company,
            listing.status,
            listing.dedup_fingerprint,
            listing.seen_sources,
            listing.raw_snapshot,
        )
        self.assertEqual(before, after)

    def test_payload_includes_interest_score(self):
        from django.conf import settings

        listing = Listing.objects.create(
            title='Web Scraping API Developer',
            company='Acme',
            url='https://example.com/job',
            dedup_fingerprint='fp-2',
        )
        item = self.client.get(reverse('listings')).json()['data']['items'][0]
        self.assertEqual(item['interest_score'], score(listing, settings.INTEREST_PROFILE))
        self.assertIsInstance(item['interest_score'], int)
        self.assertTrue(0 <= item['interest_score'] <= 100)