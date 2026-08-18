"""Story 1.2 tests: SourcePort contract, registry, generic test-fetch service.

Covers the matrix rows TESTFETCH_OK / TESTFETCH_MISMATCH /
TESTFETCH_FETCH_ERROR and the registry half of UNKNOWN_ADAPTER with a
stub fetcher — no network in these tests.
"""

import types
from unittest.mock import Mock

import requests
from django.test import SimpleTestCase

from .ports import AdapterNotFound
from .registry import clear, get_adapter, register
from .test_fetch import MAX_SAMPLE, TestFetchError, build_url, run_test_fetch

HTML_WITH_JOBS = (
    '<html><body>'
    '<div class="job">Job A</div>'
    '<div class="job">Job B</div>'
    '</body></html>'
)


def make_source(config):
    return types.SimpleNamespace(config=config)


def make_valid_source():
    return make_source(
        {
            'url_pattern': 'https://x/{keywords}',
            'listing_selector': 'div.job',
            'keywords': ['python'],
        }
    )


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f'{self.status_code} Server Error', response=self
            )


class RegistryTests(SimpleTestCase):
    """FR-1 code-first registry: one module + registry row per site type."""

    def setUp(self):
        clear()

    def test_register_and_get_resolve_class(self):
        @register('test-registry-key')
        class StubAdapter:
            def fetch(self, keywords):
                return []

            def parse(self, raw_items):
                return []

        self.assertIs(get_adapter('test-registry-key'), StubAdapter)

    def test_unknown_key_raises_adapter_not_found(self):
        with self.assertRaisesMessage(
            AdapterNotFound, 'unknown adapter key: no-such-adapter'
        ):
            get_adapter('no-such-adapter')

    def test_non_string_key_raises_adapter_not_found(self):
        with self.assertRaisesMessage(AdapterNotFound, 'unknown adapter key: None'):
            get_adapter(None)
        with self.assertRaises(AdapterNotFound):
            get_adapter(42)

    def test_register_rejects_class_without_sourceport(self):
        with self.assertRaisesMessage(TypeError, 'must implement SourcePort'):

            @register('not-an-adapter')
            class NotAnAdapter:
                pass

    def test_google_jobs_placeholder_resolves(self):
        from collector import GoogleJobsStub

        register('google-jobs')(GoogleJobsStub)
        self.assertIs(get_adapter('google-jobs'), GoogleJobsStub)


class BuildUrlTests(SimpleTestCase):
    def test_keywords_substituted_into_placeholder(self):
        self.assertEqual(
            build_url('https://x/{keywords}', ['python', 'django']),
            'https://x/python+django',
        )

    def test_plus_in_keyword_is_percent_encoded(self):
        self.assertEqual(build_url('https://x/{keywords}', ['c++']), 'https://x/c%2B%2B')

    def test_space_in_keyword_is_percent_encoded(self):
        self.assertEqual(
            build_url('https://x/{keywords}', ['machine learning']),
            'https://x/machine%20learning',
        )

    def test_ampersand_in_keyword_is_percent_encoded(self):
        self.assertEqual(build_url('https://x/{keywords}', ['c&c']), 'https://x/c%26c')

    def test_non_ascii_keyword_is_percent_encoded(self):
        self.assertEqual(
            build_url('https://x/{keywords}', ['développeur']),
            'https://x/d%C3%A9veloppeur',
        )

    def test_other_braces_in_pattern_do_not_crash(self):
        self.assertEqual(
            build_url('https://x/{kw}/{keywords}', ['python']),
            'https://x/{kw}/python',
        )


class TestFetchTests(SimpleTestCase):
    def test_ok_returns_sample_and_raw_snapshot(self):
        calls = []

        def fetch(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse(HTML_WITH_JOBS)

        source = make_valid_source()
        result = run_test_fetch(source, fetch=fetch)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'https://x/python')
        self.assertEqual(calls[0][1]['timeout'], 30)
        self.assertIn('User-Agent', calls[0][1]['headers'])
        self.assertEqual(
            result['sample'],
            [
                {'html': '<div class="job">Job A</div>'},
                {'html': '<div class="job">Job B</div>'},
            ],
        )
        self.assertEqual(result['raw_snapshot'], HTML_WITH_JOBS)
        self.assertNotIn('notice', result)

    def test_xpath_selector_supported(self):
        source = make_source(
            {
                'url_pattern': 'https://x/{keywords}',
                'listing_selector': '//div[@class="job"]',
                'keywords': ['python'],
            }
        )
        result = run_test_fetch(
            source, fetch=Mock(return_value=FakeResponse(HTML_WITH_JOBS))
        )

        self.assertEqual(
            result['sample'],
            [
                {'html': '<div class="job">Job A</div>'},
                {'html': '<div class="job">Job B</div>'},
            ],
        )
        self.assertEqual(result['raw_snapshot'], HTML_WITH_JOBS)

    def test_absolute_xpath_selector_supported(self):
        source = make_source(
            {
                'url_pattern': 'https://x/{keywords}',
                'listing_selector': '/html/body/div[@class="job"]',
                'keywords': ['python'],
            }
        )
        result = run_test_fetch(
            source, fetch=Mock(return_value=FakeResponse(HTML_WITH_JOBS))
        )

        self.assertEqual(len(result['sample']), 2)
        self.assertEqual(result['sample'][0], {'html': '<div class="job">Job A</div>'})

    def test_mismatch_returns_notice_with_raw_snapshot(self):
        source = make_source(
            {
                'url_pattern': 'https://x/{keywords}',
                'listing_selector': 'div.no-such-class',
                'keywords': ['python'],
            }
        )
        result = run_test_fetch(source, fetch=Mock(return_value=FakeResponse(HTML_WITH_JOBS)))

        self.assertEqual(result['sample'], [])
        self.assertEqual(result['notice'], 'selector-mismatch')
        self.assertEqual(result['raw_snapshot'], HTML_WITH_JOBS)

    def test_fetch_connection_error_raises_test_fetch_error(self):
        def fetch(url, **kwargs):
            raise ConnectionError('connection refused')

        source = make_valid_source()
        with self.assertRaisesMessage(TestFetchError, 'fetch failed: connection refused'):
            run_test_fetch(source, fetch=fetch)

    def test_http_error_raises_test_fetch_error(self):
        source = make_valid_source()
        with self.assertRaisesMessage(TestFetchError, 'fetch failed: 500 Server Error'):
            run_test_fetch(
                source, fetch=Mock(return_value=FakeResponse('oops', status_code=500))
            )

    def test_fetch_response_without_text_raises_test_fetch_error(self):
        class NoTextResponse:
            def raise_for_status(self):
                pass

        source = make_valid_source()
        with self.assertRaisesMessage(TestFetchError, 'fetch failed:'):
            run_test_fetch(source, fetch=Mock(return_value=NoTextResponse()))

    def test_raw_snapshot_truncated_to_2048(self):
        long_html = '<div class="job">' + 'x' * 5000 + '</div>'
        source = make_valid_source()
        result = run_test_fetch(source, fetch=Mock(return_value=FakeResponse(long_html)))

        self.assertEqual(len(result['raw_snapshot']), 2048)
        self.assertEqual(result['raw_snapshot'], long_html[:2048])

    def test_sample_capped_at_max_sample(self):
        html = '<div class="job">x</div>' * 60
        source = make_valid_source()
        result = run_test_fetch(source, fetch=Mock(return_value=FakeResponse(html)))

        self.assertEqual(len(result['sample']), MAX_SAMPLE)

    def test_empty_keywords_raises_test_fetch_error(self):
        source = make_source(
            {
                'url_pattern': 'https://x/{keywords}',
                'listing_selector': 'div.job',
                'keywords': [],
            }
        )
        with self.assertRaisesMessage(
            TestFetchError, 'invalid config: keywords must be a non-empty list'
        ):
            run_test_fetch(source, fetch=Mock())

    def test_blank_keyword_raises_test_fetch_error(self):
        source = make_source(
            {
                'url_pattern': 'https://x/{keywords}',
                'listing_selector': 'div.job',
                'keywords': ['python', ' '],
            }
        )
        with self.assertRaisesMessage(
            TestFetchError, 'invalid config: keywords must be a list of non-empty strings'
        ):
            run_test_fetch(source, fetch=Mock())

    def test_non_dict_config_raises_test_fetch_error(self):
        with self.assertRaisesMessage(
            TestFetchError, 'invalid config: config must be a JSON object'
        ):
            run_test_fetch(make_source('not a dict'), fetch=Mock())

    def test_invalid_config_raises_test_fetch_error(self):
        source = make_source({'url_pattern': 'https://x/{kw}', 'listing_selector': 'div'})
        with self.assertRaisesMessage(
            TestFetchError, 'invalid config: url_pattern must contain the {keywords} placeholder'
        ):
            run_test_fetch(source, fetch=Mock())

        source = make_source({'url_pattern': 'https://x/{keywords}', 'listing_selector': ''})
        with self.assertRaisesMessage(TestFetchError, 'invalid config: listing_selector is required'):
            run_test_fetch(source, fetch=Mock())