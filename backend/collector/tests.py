"""Story 1.2 + 1.3 tests: SourcePort contract, registry, test-fetch,
pipeline stages, repository, and collect_source orchestration.

Story 1.3 covers every matrix row — COLLECT_OK / COLLECT_DUP /
COLLECT_FETCH_FAIL / COLLECT_BAD_ITEM / STATUS_PRESERVED /
FINGERPRINT_STABLE — with stub adapters; no network in these tests.
"""

import json
import types
from datetime import datetime
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, TestCase

from .collect import collect_source
from .pipeline import (
    clean_item,
    compute_fingerprint,
    dedupe_item,
    extract_item,
    normalize_item,
    normalize_keywords,
    normalize_published_at,
    url_host,
    validate,
)
from .ports import AdapterNotFound
from .registry import clear, get_adapter, register
from .repository import ListingRepository
from .test_fetch import MAX_SAMPLE, TestFetchError, build_url, run_test_fetch
from listings.models import FetchLog, Listing, Source

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


# ---------------------------------------------------------------------------
# Story 1.3: collection pipeline
# ---------------------------------------------------------------------------

# Adapter output used across the matrix rows (parse() already yields
# canonical-ish dicts, per the Story 1.2 Code Map).
RAW_ITEMS = [
    {
        'title': '  Python   Developer  ',
        'company': 'Acme Corp',
        'url': 'https://acme.example/jobs/1',
        'published_at': '2026-08-18T09:30:00+02:00',
        'keywords': ['python', 'django'],
        'extra': 'ignored-key',
    },
    {
        'title': 'Backend Engineer',
        'company': 'Globex',
        'url': 'https://globex.example/jobs/2',
        'published_at': '2026-08-18T10:00:00Z',
        'keywords': ['python'],
    },
    {
        'title': 'DevOps Engineer',
        'company': 'Initech',
        'url': 'https://initech.example/jobs/3',
        'published_at': 'not-a-date',
        'keywords': 'kubernetes, terraform',
    },
]


def register_stub(key='stub-collect', raw_items=None, fetch_error=None):
    """Register a SourcePort-conforming stub adapter for the matrix rows."""

    @register(key)
    class StubCollectAdapter:
        def fetch(self, keywords):
            if fetch_error is not None:
                raise fetch_error
            return raw_items or []

        def parse(self, raw_items):
            return raw_items

    return StubCollectAdapter


class PipelineStageTests(SimpleTestCase):
    """Pure stages: extract -> clean -> normalize -> dedupe -> validate.

    No DB, no I/O: these stages import only stdlib + each other.
    """

    def test_extract_picks_canonical_keys_and_tolerates_extra(self):
        raw = {
            'title': 'T',
            'company': 'C',
            'url': 'https://x.example/',
            'published_at': '2026-01-01',
            'keywords': ['k'],
            'extra': 'ignored',
        }
        item = extract_item(raw)
        self.assertEqual(
            set(item),
            {'title', 'company', 'url', 'published_at', 'keywords', 'raw_snapshot'},
        )
        self.assertEqual(item['raw_snapshot'], raw)
        self.assertNotIn('extra', item)

    def test_extract_rejects_non_dict_item(self):
        with self.assertRaisesMessage(TypeError, 'raw item must be a dict'):
            extract_item('not a dict')

    def test_clean_collapses_whitespace_and_drops_empty_fields(self):
        item = clean_item(
            {
                'title': '  Python   Dev  ',
                'company': '   ',
                'url': ' https://x.example/ ',
            }
        )
        self.assertEqual(item['title'], 'Python Dev')
        self.assertNotIn('company', item)
        self.assertEqual(item['url'], 'https://x.example/')

    def test_normalize_published_at_to_iso_utc(self):
        self.assertEqual(
            normalize_published_at('2026-08-18T09:30:00+02:00'),
            '2026-08-18T07:30:00+00:00',
        )
        self.assertEqual(
            normalize_published_at('2026-08-18T10:00:00Z'),
            '2026-08-18T10:00:00+00:00',
        )
        self.assertEqual(
            normalize_published_at('2026-08-18T10:00:00'),
            '2026-08-18T10:00:00+00:00',
        )

    def test_normalize_published_at_lenient(self):
        self.assertIsNone(normalize_published_at('not-a-date'))
        self.assertIsNone(normalize_published_at(None))
        self.assertIsNone(normalize_published_at(''))

    def test_normalize_keywords_coerces_to_list(self):
        self.assertEqual(
            normalize_keywords('kubernetes, terraform'),
            ['kubernetes', 'terraform'],
        )
        self.assertEqual(normalize_keywords([' python ', '']), ['python'])
        self.assertEqual(normalize_keywords(None), [])
        self.assertEqual(normalize_keywords(42), [])

    def test_normalize_keywords_drops_none_and_containers(self):
        self.assertEqual(
            normalize_keywords([None, {'a': 1}, [1, 2], ('x',), 42, ' python ', True]),
            ['42', 'python', 'True'],
        )

    def test_normalize_caps_raw_snapshot(self):
        item = normalize_item(
            {
                'title': 'T',
                'company': 'C',
                'url': 'https://x.example/',
                'published_at': None,
                'keywords': [],
                'raw_snapshot': {'html': 'x' * 5000},
            }
        )
        self.assertLessEqual(len(json.dumps(item['raw_snapshot'])), 2048)

    def test_normalize_keeps_small_raw_snapshot_untouched(self):
        snapshot = {'html': '<div>job</div>'}
        item = normalize_item(
            {
                'title': 'T',
                'company': 'C',
                'url': 'https://x.example/',
                'published_at': None,
                'keywords': [],
                'raw_snapshot': snapshot,
            }
        )
        self.assertEqual(item['raw_snapshot'], snapshot)

    def test_url_host_helper(self):
        self.assertEqual(url_host('https://Example.COM/jobs'), 'example.com')
        self.assertEqual(url_host('https://x.example.com:8443/jobs'), 'x.example.com')
        self.assertEqual(url_host('not-a-url'), '')
        self.assertEqual(url_host(None), '')

    def test_compute_fingerprint_stable_across_casing(self):
        a = compute_fingerprint(
            'Python Dev', 'Acme Corp', 'https://acme.example/jobs/1'
        )
        b = compute_fingerprint(
            'python dev', 'acme corp', 'https://ACME.EXAMPLE/jobs/1'
        )
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)  # sha256 hex fits max_length=64 exactly

    def test_compute_fingerprint_distinguishes_host(self):
        a = compute_fingerprint(
            'Python Dev', 'Acme Corp', 'https://acme.example/jobs/1'
        )
        b = compute_fingerprint(
            'Python Dev', 'Acme Corp', 'https://other.example/jobs/1'
        )
        self.assertNotEqual(a, b)

    def test_fingerprint_separator_keeps_parts_deterministic(self):
        a = compute_fingerprint('Python Dev', 'Acme Corp', 'https://acme.example/jobs/1')
        self.assertEqual(
            a,
            compute_fingerprint('Python Dev', 'Acme Corp', 'https://acme.example/jobs/1'),
        )

    def test_pipe_in_title_does_not_collide(self):
        a = compute_fingerprint('a|b', 'c', 'https://x.example/')
        b = compute_fingerprint('a', 'b|c', 'https://x.example/')
        self.assertNotEqual(a, b)

    def test_dedupe_item_assigns_fingerprint(self):
        item = dedupe_item(
            {
                'title': 'Python Dev',
                'company': 'Acme',
                'url': 'https://acme.example/jobs/1',
            }
        )
        self.assertEqual(
            item['dedup_fingerprint'],
            compute_fingerprint('Python Dev', 'Acme', 'https://acme.example/jobs/1'),
        )

    def test_validate_returns_valid_and_errors(self):
        good = {'title': 'T', 'company': 'C', 'url': 'https://x.example/'}
        no_title = {'company': 'C', 'url': 'https://x.example/'}
        no_company = {'title': 'T', 'url': 'https://x.example/'}
        bad_url = {'title': 'T', 'company': 'C', 'url': 'not-a-url'}
        ftp_url = {'title': 'T', 'company': 'C', 'url': 'ftp://x.example/'}
        valid, errors = validate([good, no_title, no_company, bad_url, ftp_url])

        self.assertEqual(valid, [good])
        self.assertEqual(len(errors), 4)
        self.assertEqual(errors[0][2], 'title is required')
        self.assertEqual(errors[1][2], 'company is required')
        self.assertIn('url', errors[2][2])
        self.assertIn('url', errors[3][2])

    def test_validate_rejects_hostless_url(self):
        valid, errors = validate(
            [{'title': 'T', 'company': 'C', 'url': 'http://:8080/'}]
        )
        self.assertEqual(valid, [])
        self.assertEqual(errors[0][2], 'url must be a valid http(s) url')

    def test_validate_rejects_overlong_title(self):
        item = {'title': 'T' * 501, 'company': 'C', 'url': 'https://x.example/'}
        valid, errors = validate([item])
        self.assertEqual(valid, [])
        self.assertIn('500', errors[0][2])

    def test_validate_rejects_overlong_company_and_url(self):
        long_company = {'title': 'T', 'company': 'C' * 256, 'url': 'https://x.example/'}
        long_url = {'title': 'T', 'company': 'C', 'url': 'https://x.example/' + 'a' * 2048}
        valid, errors = validate([long_company, long_url])
        self.assertEqual(valid, [])
        self.assertIn('255', errors[0][2])
        self.assertIn('2048', errors[1][2])


class CollectSourceTests(TestCase):
    """COLLECT_* matrix rows through the full collect_source path."""

    def setUp(self):
        clear()

    def _source(self, name='source', adapter_key='stub-collect', **config):
        return Source.objects.create(
            name=name, adapter_key=adapter_key, config=config or {'keywords': ['python']}
        )

    def test_collect_ok_persists_listings_with_canonical_fields(self):
        register_stub(raw_items=RAW_ITEMS)
        source = self._source()

        created = collect_source(source)

        self.assertEqual(created, 3)
        self.assertEqual(Listing.objects.count(), 3)
        listing = Listing.objects.get(
            dedup_fingerprint=compute_fingerprint(
                'Python Developer', 'Acme Corp', 'https://acme.example/jobs/1'
            )
        )
        self.assertEqual(listing.title, 'Python Developer')
        self.assertEqual(listing.company, 'Acme Corp')
        self.assertEqual(listing.url, 'https://acme.example/jobs/1')
        self.assertEqual(listing.published_at.isoformat(), '2026-08-18T07:30:00+00:00')
        self.assertEqual(listing.keywords, ['python', 'django'])
        self.assertEqual(listing.status, 'new')
        self.assertEqual(listing.seen_sources, ['stub-collect'])
        self.assertEqual(listing.raw_snapshot['extra'], 'ignored-key')

        # lenient published_at: unparseable -> None; string keywords coerced.
        devops = Listing.objects.get(company='Initech')
        self.assertIsNone(devops.published_at)
        self.assertEqual(devops.keywords, ['kubernetes', 'terraform'])

        # success row: one ok=True FetchLog with empty error (AD-6 consistency).
        ok_log = FetchLog.objects.get(source=source, ok=True)
        self.assertEqual(ok_log.stage, 'persist')
        self.assertEqual(ok_log.error, '')

    def test_collect_dup_is_idempotent(self):
        register_stub(raw_items=RAW_ITEMS)
        source = self._source()

        first = collect_source(source)
        second = collect_source(source)

        self.assertEqual(first, 3)
        self.assertEqual(second, 0)
        self.assertEqual(Listing.objects.count(), 3)
        for listing in Listing.objects.all():
            self.assertEqual(listing.seen_sources.count('stub-collect'), 1)

    def test_collect_fetch_failure_logged_and_isolated(self):
        register_stub(fetch_error=ConnectionError('connection refused'))
        source = self._source()

        created = collect_source(source)  # must not raise

        self.assertEqual(created, 0)
        self.assertEqual(Listing.objects.count(), 0)
        log = FetchLog.objects.get(source=source, ok=False)
        self.assertEqual(log.stage, 'fetch')
        self.assertIn('connection refused', log.error)

    def test_collect_bad_item_skipped_others_persist(self):
        bad = {'title': 'Broken', 'company': 'Acme', 'url': 'not-a-url'}
        register_stub(raw_items=[bad, RAW_ITEMS[0], RAW_ITEMS[1]])
        source = self._source()

        created = collect_source(source)

        self.assertEqual(created, 2)
        self.assertEqual(Listing.objects.count(), 2)
        log = FetchLog.objects.get(source=source, ok=False, stage='validate')
        self.assertIn('Broken', log.error)
        self.assertIn('url', log.error)
        # a failed pass writes no ok=True row (AD-6 consistency)
        self.assertEqual(FetchLog.objects.filter(source=source, ok=True).count(), 0)

    def test_non_dict_item_fails_extract_others_proceed(self):
        register_stub(raw_items=['<div>not a dict</div>', RAW_ITEMS[0]])
        source = self._source()

        created = collect_source(source)

        self.assertEqual(created, 1)
        self.assertEqual(FetchLog.objects.filter(ok=False, stage='extract').count(), 1)

    def test_status_preserved_across_collection(self):
        register_stub(raw_items=[RAW_ITEMS[0]])
        source = self._source()
        collect_source(source)
        listing = Listing.objects.get()
        listing.status = Listing.Status.APPLIED
        listing.save()

        collect_source(source)

        listing.refresh_from_db()
        self.assertEqual(listing.status, 'applied')
        self.assertEqual(listing.seen_sources, ['stub-collect'])
        self.assertEqual(Listing.objects.count(), 1)

    def test_fingerprint_stable_dedupes_casing_variants(self):
        raw_a = {
            'title': 'Python Dev',
            'company': 'Acme Corp',
            'url': 'https://acme.example/jobs/1',
        }
        raw_b = {
            'title': 'python dev',
            'company': 'acme corp',
            'url': 'https://ACME.EXAMPLE/jobs/1',
        }
        register_stub(raw_items=[raw_a, raw_b])
        source = self._source()

        created = collect_source(source)

        self.assertEqual(created, 1)
        self.assertEqual(Listing.objects.count(), 1)
        listing = Listing.objects.get()
        self.assertEqual(
            listing.dedup_fingerprint,
            compute_fingerprint('python dev', 'acme corp', 'https://ACME.EXAMPLE/jobs/1'),
        )
        self.assertEqual(listing.seen_sources, ['stub-collect'])

    def test_fetch_receives_source_keywords(self):
        received = []

        @register('capture-keywords')
        class CaptureAdapter:
            def fetch(self, keywords):
                received.append(keywords)
                return []

            def parse(self, raw_items):
                return raw_items

        source = self._source(adapter_key='capture-keywords', keywords=['python', 'django'])

        collect_source(source)

        self.assertEqual(received, [['python', 'django']])

    def test_unknown_adapter_key_logged_not_raised(self):
        source = self._source(adapter_key='no-such-adapter')
        created = collect_source(source)
        self.assertEqual(created, 0)
        log = FetchLog.objects.get(source=source, ok=False)
        self.assertEqual(log.stage, 'fetch')
        self.assertIn('unknown adapter key: no-such-adapter', log.error)

    def test_invalid_config_keywords_logged_stage_config(self):
        register_stub(raw_items=RAW_ITEMS)
        for index, bad_config in enumerate(
            ({'keywords': 'not-a-list'}, {'keywords': []}, {'keywords': None})
        ):
            with self.subTest(config=bad_config):
                source = self._source(name=f'cfg-{index}', **bad_config)
                created = collect_source(source)
                self.assertEqual(created, 0)
                self.assertEqual(Listing.objects.count(), 0)
                log = FetchLog.objects.get(source=source, ok=False, stage='config')
                self.assertIn('keywords', log.error)

    def test_persist_failure_isolated_per_item(self):
        register_stub(raw_items=RAW_ITEMS)
        source = self._source()
        real_upsert = ListingRepository.upsert

        def flaky_upsert(self, item, source):
            if item['title'] == 'Backend Engineer':
                raise RuntimeError('boom: persist exploded')
            return real_upsert(self, item, source)

        with patch.object(ListingRepository, 'upsert', flaky_upsert):
            created = collect_source(source)

        self.assertEqual(created, 2)
        self.assertEqual(Listing.objects.count(), 2)
        log = FetchLog.objects.get(source=source, ok=False, stage='persist')
        self.assertIn('Backend Engineer', log.error)
        self.assertIn('boom: persist exploded', log.error)

    def test_all_persist_failures_write_no_ok_row(self):
        register_stub(raw_items=RAW_ITEMS)
        source = self._source()

        def failing_upsert(self, item, source):
            raise RuntimeError('db exploded')

        with patch.object(ListingRepository, 'upsert', failing_upsert):
            created = collect_source(source)

        self.assertEqual(created, 0)
        self.assertEqual(Listing.objects.count(), 0)
        self.assertEqual(FetchLog.objects.filter(source=source, ok=True).count(), 0)
        self.assertEqual(
            FetchLog.objects.filter(source=source, ok=False, stage='persist').count(),
            3,
        )

    def test_fetch_none_or_non_iterable_logged_fetch(self):
        for index, bad_output in enumerate((None, 42)):
            with self.subTest(bad_output=bad_output):
                clear()

                @register('bad-fetch')
                class BadFetchAdapter:
                    def fetch(self, keywords):
                        return bad_output

                    def parse(self, raw_items):
                        return raw_items

                source = self._source(name=f'bad-fetch-{index}', adapter_key='bad-fetch')
                created = collect_source(source)
                self.assertEqual(created, 0)
                self.assertEqual(Listing.objects.count(), 0)
                log = FetchLog.objects.get(source=source, ok=False, stage='fetch')
                self.assertIn('fetch failed', log.error)

    def test_parse_raises_logged_stage_parse(self):
        @register('parse-boom')
        class ParseBoomAdapter:
            def fetch(self, keywords):
                return [{'title': 'X', 'company': 'Y', 'url': 'https://x.example/'}]

            def parse(self, raw_items):
                raise ValueError('parse exploded')

        source = self._source(adapter_key='parse-boom')
        created = collect_source(source)

        self.assertEqual(created, 0)
        self.assertEqual(Listing.objects.count(), 0)
        log = FetchLog.objects.get(source=source, ok=False, stage='parse')
        self.assertIn('parse exploded', log.error)
        self.assertEqual(FetchLog.objects.filter(source=source, ok=True).count(), 0)

    def test_content_converges_on_recollect(self):
        first = [{
            'title': 'Dev',
            'company': 'Co',
            'url': 'https://co.example/1',
            'published_at': '2026-08-18T10:00:00Z',
            'keywords': ['a'],
            'raw_snapshot': {'v': 1},
        }]
        second = [{
            'title': 'Dev',
            'company': 'Co',
            'url': 'https://co.example/1',
            'published_at': '2026-08-19T10:00:00Z',
            'keywords': ['b'],
            'raw_snapshot': {'v': 2},
        }]
        register_stub(key='converge', raw_items=first)
        source = self._source(name='converge', adapter_key='converge')
        collect_source(source)

        register_stub(key='converge', raw_items=second)
        created = collect_source(source)

        self.assertEqual(created, 0)
        listing = Listing.objects.get()
        self.assertEqual(listing.published_at.isoformat(), '2026-08-19T10:00:00+00:00')
        self.assertEqual(listing.keywords, ['b'])
        # raw_snapshot is the full raw item (extract keeps it verbatim).
        self.assertEqual(
            listing.raw_snapshot,
            {
                'title': 'Dev',
                'company': 'Co',
                'url': 'https://co.example/1',
                'published_at': '2026-08-19T10:00:00Z',
                'keywords': ['b'],
                'raw_snapshot': {'v': 2},
            },
        )
        self.assertEqual(listing.seen_sources, ['converge'])


class ListingRepositoryTests(TestCase):
    """AD-4: content-only updates, append-once seen_sources, immutable identity."""

    def _source(self, adapter_key):
        return Source.objects.create(name=f'source-{adapter_key}', adapter_key=adapter_key)

    def _item(self, **overrides):
        item = {
            'dedup_fingerprint': 'fp-repo-1',
            'title': 'Python Dev',
            'company': 'Acme',
            'url': 'https://acme.example/jobs/1',
            'published_at': '2026-08-18T07:30:00+00:00',
            'keywords': ['python'],
            'raw_snapshot': {'raw': True},
        }
        item.update(overrides)
        return item

    def test_upsert_creates_then_updates_content_only(self):
        repository = ListingRepository()
        source = self._source('src-a')
        listing, created = repository.upsert(self._item(), source)
        self.assertTrue(created)
        self.assertEqual(listing.status, 'new')
        self.assertEqual(listing.seen_sources, ['src-a'])
        self.assertEqual(listing.source, source)  # FK populated on create
        self.assertEqual(listing.published_at.isoformat(), '2026-08-18T07:30:00+00:00')

        listing, created = repository.upsert(
            self._item(title='Python Dev (Updated)'), source
        )

        self.assertFalse(created)
        self.assertEqual(listing.title, 'Python Dev (Updated)')
        self.assertEqual(listing.dedup_fingerprint, 'fp-repo-1')
        self.assertEqual(listing.seen_sources, ['src-a'])
        self.assertEqual(listing.source, source)

    def test_seen_sources_appends_each_source_once(self):
        repository = ListingRepository()
        src_a = self._source('src-a')
        src_b = self._source('src-b')
        item = self._item(published_at=None, keywords=[], raw_snapshot={})
        for source in (src_a, src_b, src_a):
            repository.upsert(item, source)

        listing = Listing.objects.get()
        self.assertEqual(listing.seen_sources, ['src-a', 'src-b'])
        self.assertIsNone(listing.published_at)

    def test_upsert_preserves_existing_status(self):
        repository = ListingRepository()
        item = self._item(published_at=None, keywords=[], raw_snapshot={})
        repository.upsert(item, self._source('src-a'))
        listing = Listing.objects.get()
        listing.status = Listing.Status.APPLIED
        listing.save()

        repository.upsert(item, self._source('src-b'))

        listing.refresh_from_db()
        self.assertEqual(listing.status, 'applied')
        self.assertEqual(listing.seen_sources, ['src-a', 'src-b'])

    def test_upsert_requires_all_content_keys(self):
        repository = ListingRepository()
        source = self._source('src-a')
        item = {'dedup_fingerprint': 'fp-repo-x', 'title': 'Dev'}
        with self.assertRaises(ValueError) as ctx:
            repository.upsert(item, source)
        message = str(ctx.exception)
        for key in ('company', 'url', 'published_at', 'keywords', 'raw_snapshot'):
            self.assertIn(key, message)
        self.assertEqual(Listing.objects.count(), 0)

    def test_upsert_without_fingerprint_raises(self):
        repository = ListingRepository()
        with self.assertRaisesMessage(ValueError, 'item has no dedup_fingerprint'):
            repository.upsert(
                {
                    'title': 'Dev',
                    'company': 'Co',
                    'url': 'https://co.example/3',
                    'published_at': None,
                    'keywords': [],
                    'raw_snapshot': {},
                },
                self._source('src-a'),
            )

    def test_none_published_at_preserves_stored_value(self):
        repository = ListingRepository()
        source = self._source('src-a')
        repository.upsert(self._item(), source)
        repository.upsert(self._item(published_at=None), source)
        listing = Listing.objects.get()
        self.assertEqual(listing.published_at.isoformat(), '2026-08-18T07:30:00+00:00')

    def test_naive_datetime_published_at_stored_none(self):
        repository = ListingRepository()
        item = self._item(
            dedup_fingerprint='fp-repo-naive',
            published_at=datetime(2026, 8, 18, 10, 0),
        )
        repository.upsert(item, self._source('src-a'))
        listing = Listing.objects.get()
        self.assertIsNone(listing.published_at)