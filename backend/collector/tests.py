"""Story 1.2 + 1.3 tests: SourcePort contract, registry, test-fetch,
pipeline stages, repository, and collect_source orchestration.

Story 1.3 covers every matrix row — COLLECT_OK / COLLECT_DUP /
COLLECT_FETCH_FAIL / COLLECT_BAD_ITEM / STATUS_PRESERVED /
FINGERPRINT_STABLE — with stub adapters; no network in these tests.
"""

import copy
import json
import types
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urljoin, urlsplit

import numpy as np
import pandas as pd
import parsel
import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from .adapters.facebook_groups import (
    AUTHOR_SELECTOR,
    BASE_URL,
    FEED_CONTAINER_SELECTOR,
    FacebookGroupsAdapter,
    FacebookGroupsAdapterError,
    LOGIN_WALL_SELECTOR,
    PERMALINK_SELECTOR,
    POST_CARD_SELECTOR,
    POST_TEXT_SELECTOR,
)
from .adapters.google_jobs import (
    DEFAULT_HOURS_OLD,
    GoogleJobsAdapter,
    GoogleJobsAdapterError,
    _sanitize_value,
)
from .adapters.ouedkniss_jobs import (
    OuedknissAdapterError,
    OuedknissJobsAdapter,
    _SEARCH_QUERY,
)
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
from .worker import (
    _startup_pass,
    find_stale_count,
    last_pass_at,
    needs_backfill,
    poll_all,
    run,
)
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


class JsonResponse:
    """requests-like response for GraphQL adapter tests (hermetic)."""

    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f'{self.status_code} Server Error', response=self
            )

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class RegistryTests(SimpleTestCase):
    """FR-1 code-first registry: one module + registry row per site type.

    No `clear()` in setUp: the ouedkniss-jobs row is registered at import
    time (Story 1.5) and must survive for the Ouedkniss* test classes;
    each test re-registers its own key, so isolation does not need a wipe.
    """

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
        def __init__(self, config=None):
            pass

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
    """COLLECT_* matrix rows through the full collect_source path.

    No `clear()` here: the ouedkniss-jobs row is registered at import time
    (Story 1.5) and must survive for the Ouedkniss* test classes; stub keys
    are re-registered per test, so isolation does not need a wipe.
    """

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
            def __init__(self, config=None):
                pass

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
                @register('bad-fetch')
                class BadFetchAdapter:
                    def __init__(self, config=None):
                        pass

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
            def __init__(self, config=None):
                pass

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


# ---------------------------------------------------------------------------
# Story 1.4: collector worker
# ---------------------------------------------------------------------------


def register_empty_stub(key):
    """Stub adapter that fetches nothing (no Listing side effects)."""

    @register(key)
    class EmptyStubAdapter:
        def __init__(self, config=None):
            pass

        def fetch(self, keywords):
            return []

        def parse(self, raw_items):
            return []

    return EmptyStubAdapter


class NeedsBackfillTests(SimpleTestCase):
    """FIRST_PASS / GAP_OVERDUE / GAP_FRESH: pure backfill decision."""

    def test_first_pass_requires_backfill(self):
        self.assertTrue(needs_backfill(None, timezone.now()))

    def test_gap_overdue_requires_backfill(self):
        now = timezone.now()
        self.assertTrue(needs_backfill(now - timedelta(hours=3), now))

    def test_gap_fresh_does_not_require_backfill(self):
        now = timezone.now()
        self.assertFalse(needs_backfill(now - timedelta(minutes=10), now))

    def test_gap_at_exactly_two_intervals_requires_backfill(self):
        now = timezone.now()
        gap = 2 * timedelta(minutes=settings.COLLECTOR_INTERVAL_MINUTES)
        self.assertTrue(needs_backfill(now - gap, now))

    def test_gap_just_under_two_intervals_does_not_require_backfill(self):
        now = timezone.now()
        gap = 2 * timedelta(minutes=settings.COLLECTOR_INTERVAL_MINUTES) - timedelta(
            seconds=1
        )
        self.assertFalse(needs_backfill(now - gap, now))


class WorkerTests(TestCase):
    """POLL_ALL isolation, pass/backfill bookkeeping, stale counting.

    No `clear()` in setUp: the ouedkniss-jobs row is registered at import
    time (Story 1.5) and must survive for the Ouedkniss* test classes;
    stub keys are re-registered here, so isolation does not need a wipe.
    """

    def setUp(self):
        register_stub(key='stub-ok-a', raw_items=RAW_ITEMS)
        register_stub(key='stub-ok-b', raw_items=RAW_ITEMS)
        register_stub(key='stub-fail', fetch_error=ConnectionError('connection refused'))
        Source.objects.create(
            name='ok-a', adapter_key='stub-ok-a', config={'keywords': ['python']}
        )
        Source.objects.create(
            name='ok-b', adapter_key='stub-ok-b', config={'keywords': ['python']}
        )
        self.failing = Source.objects.create(
            name='fail', adapter_key='stub-fail', config={'keywords': ['python']}
        )

    def _listing(self, fingerprint, published_at):
        return Listing.objects.create(
            dedup_fingerprint=fingerprint,
            title=f'Job {fingerprint}',
            company='Co',
            url=f'https://co.example/{fingerprint}',
            published_at=published_at,
        )

    def test_poll_all_isolates_failures_and_writes_one_pass_row(self):
        poll_all()  # must not raise (AD-6)

        # both OK sources feed the same 3 raw items -> deduped to 3 listings
        self.assertEqual(Listing.objects.count(), 3)
        for listing in Listing.objects.all():
            self.assertEqual(listing.seen_sources, ['stub-ok-a', 'stub-ok-b'])
        self.assertEqual(
            FetchLog.objects.filter(stage='pass', ok=True, source=None).count(), 1
        )
        fail_log = FetchLog.objects.get(source=self.failing, ok=False)
        self.assertEqual(fail_log.stage, 'fetch')
        self.assertIn('connection refused', fail_log.error)
        for source in Source.objects.exclude(pk=self.failing.pk):
            self.assertEqual(
                FetchLog.objects.filter(source=source, ok=True, stage='persist').count(),
                1,
            )

    def test_poll_all_with_no_sources_still_writes_pass_row(self):
        Source.objects.all().delete()
        poll_all()
        self.assertEqual(FetchLog.objects.filter(stage='pass', ok=True).count(), 1)

    def test_last_pass_at_none_until_ok_pass_exists(self):
        self.assertIsNone(last_pass_at())
        FetchLog.objects.create(source=None, stage='backfill', ok=True)
        self.assertIsNone(last_pass_at())
        FetchLog.objects.create(source=None, stage='pass', ok=False)
        self.assertIsNone(last_pass_at())
        FetchLog.objects.create(source=None, stage='pass', ok=True)
        self.assertEqual(
            last_pass_at(), FetchLog.objects.get(stage='pass', ok=True).created_at
        )

    def test_freshness_cutoff_counts_only_published_at_before_cutoff(self):
        now = timezone.now()
        self._listing('fresh-2h', now - timedelta(hours=2))
        self._listing('stale-30h', now - timedelta(hours=30))
        self._listing('never-fresh', None)

        self.assertEqual(find_stale_count(now - timedelta(hours=24)), 1)

    def test_startup_first_pass_logs_backfill_with_stale_count(self):
        register_empty_stub('empty-backfill')
        # isolate from the setUp stub sources: their RAW_ITEMS rows carry
        # fixed fixture dates that may be stale on any given run day
        Source.objects.all().delete()
        Source.objects.create(
            name='empty', adapter_key='empty-backfill', config={'keywords': ['python']}
        )
        now = timezone.now()
        self._listing('stale-30h', now - timedelta(hours=30))
        self._listing('fresh-2h', now - timedelta(hours=2))
        self._listing('never-fresh', None)

        _startup_pass()

        backfill = FetchLog.objects.get(stage='backfill', ok=True)
        self.assertIn('1 listing(s) older than 24h', backfill.error)
        self.assertIsNone(backfill.source)
        self.assertEqual(FetchLog.objects.filter(stage='pass', ok=True).count(), 1)

    def test_startup_fresh_start_writes_plain_pass_not_backfill(self):
        register_empty_stub('empty-fresh')
        Source.objects.create(
            name='empty', adapter_key='empty-fresh', config={'keywords': ['python']}
        )
        FetchLog.objects.create(source=None, stage='pass', ok=True)

        _startup_pass()

        self.assertEqual(FetchLog.objects.filter(stage='backfill').count(), 0)
        self.assertEqual(FetchLog.objects.filter(stage='pass', ok=True).count(), 2)

    def test_startup_overdue_gap_logs_backfill(self):
        Source.objects.all().delete()
        now = timezone.now()
        self._listing('stale-30h', now - timedelta(hours=30))
        self._listing('never-fresh', None)
        old_pass = FetchLog.objects.create(source=None, stage='pass', ok=True)
        FetchLog.objects.filter(pk=old_pass.pk).update(
            created_at=now - timedelta(hours=3)
        )

        _startup_pass()

        backfill = FetchLog.objects.get(stage='backfill', ok=True)
        self.assertIn('1 listing(s) older than 24h', backfill.error)
        self.assertIsNone(backfill.source)
        self.assertEqual(FetchLog.objects.filter(stage='pass', ok=True).count(), 2)

    def test_second_startup_skips_backfill(self):
        Source.objects.all().delete()

        _startup_pass()
        _startup_pass()

        self.assertEqual(FetchLog.objects.filter(stage='backfill', ok=True).count(), 1)
        self.assertEqual(FetchLog.objects.filter(stage='pass', ok=True).count(), 2)

    def test_freshness_exact_cutoff_not_stale(self):
        now = timezone.now()
        cutoff = now - timedelta(hours=24)
        self._listing('exact-cutoff', cutoff)

        self.assertEqual(find_stale_count(cutoff), 0)


class SchedulerTests(TestCase):
    """INTERVAL_JOB / GRACEFUL_STOP: scheduler wiring without starting it."""

    def _run(self, start_side_effect=None):
        with patch('apscheduler.schedulers.blocking.BlockingScheduler') as scheduler_cls:
            scheduler = scheduler_cls.return_value
            scheduler.start.side_effect = start_side_effect
            run()
        return scheduler

    def test_run_registers_one_interval_job_and_starts(self):
        scheduler = self._run()

        scheduler.add_job.assert_called_once()
        trigger = scheduler.add_job.call_args[0][1]
        self.assertEqual(
            trigger.interval,
            timedelta(minutes=settings.COLLECTOR_INTERVAL_MINUTES),
        )
        self.assertEqual(scheduler.add_job.call_args[1]['id'], 'poll-all')
        scheduler.start.assert_called_once()

    def test_run_first_pass_writes_backfill_row(self):
        self._run()
        self.assertEqual(FetchLog.objects.filter(stage='backfill', ok=True).count(), 1)

    def test_run_fresh_start_writes_no_backfill_row(self):
        FetchLog.objects.create(source=None, stage='pass', ok=True)
        self._run()
        self.assertEqual(FetchLog.objects.filter(stage='backfill').count(), 0)

    def test_keyboard_interrupt_shuts_scheduler_down_cleanly(self):
        scheduler = self._run(start_side_effect=KeyboardInterrupt)
        scheduler.shutdown.assert_called_once_with(wait=False)

    def test_interrupt_during_startup_pass_returns_cleanly(self):
        # REAL BlockingScheduler: Ctrl+C during the startup pass must not
        # raise SchedulerNotRunningError from shutdown() on a stopped
        # scheduler (fails pre-patch with the unguarded shutdown call).
        with patch('collector.worker._startup_pass', side_effect=KeyboardInterrupt):
            run()

    def test_run_registers_job_on_real_scheduler(self):
        # REAL BlockingScheduler: start() is stopped via SystemExit (never
        # blocks); add_job spies on the real registration to capture the job.
        jobs = []
        real_add_job = BlockingScheduler.add_job

        def spy_add_job(self, func, trigger, **kwargs):
            job = real_add_job(self, func, trigger, **kwargs)
            jobs.append(job)
            return job

        with patch('collector.worker._startup_pass'), \
                patch('apscheduler.schedulers.blocking.BlockingScheduler.start',
                      side_effect=SystemExit), \
                patch('apscheduler.schedulers.blocking.BlockingScheduler.add_job',
                      spy_add_job):
            with self.assertRaises(SystemExit):
                run()

        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(
            job.trigger.interval,
            timedelta(minutes=settings.COLLECTOR_INTERVAL_MINUTES),
        )
        self.assertEqual(job.max_instances, 1)
        self.assertIs(job.coalesce, True)
        self.assertEqual(
            job.misfire_grace_time,
            settings.COLLECTOR_INTERVAL_MINUTES * 60,
        )


class CollectorCommandTests(SimpleTestCase):
    """run_collector management command wiring (AD-2 two-process envelope)."""

    def test_command_invokes_run(self):
        with patch('collector.worker.run') as mock_run:
            call_command('run_collector')
        mock_run.assert_called_once()

    def test_command_listed_in_help(self):
        # Django 6.1 dropped the `help` management command; the command
        # advertises itself via its non-empty help string instead.
        from collector.management.commands.run_collector import Command

        self.assertTrue(Command.help)


# ---------------------------------------------------------------------------
# Story 1.5: ouedkniss-jobs adapter
# ---------------------------------------------------------------------------


class OuedknissJobsAdapterTests(SimpleTestCase):
    """Story 1.5 matrix rows — hermetic against the live-probe fixture.

    Every row monkeypatches `requests.post` at the adapter module level;
    no live network, no DB. The fixture `tests/fixtures/search_response.json`
    is the recorded probe response (redacted to 3 items).
    """

    FIXTURE = json.loads(
        (
            Path(__file__).parent
            / 'tests'
            / 'fixtures'
            / 'search_response.json'
        ).read_text(encoding='utf-8')
    )
    BODY = {key: value for key, value in FIXTURE.items() if not key.startswith('_')}
    ITEMS = BODY['data']['search']['announcements']['data']

    def setUp(self):
        self.adapter = OuedknissJobsAdapter()

    def _patched_post(self, side_effect=None, return_value=None):
        post = Mock(side_effect=side_effect, return_value=return_value)
        patcher = patch('collector.adapters.ouedkniss_jobs.requests.post', post)
        patcher.start()
        self.addCleanup(patcher.stop)
        return post

    def _synthetic(self, index, **overrides):
        item = copy.deepcopy(self.ITEMS[0])
        item['id'] = f'99999{index:02d}'
        item['slug'] = f'synthetic-{index}-algerie'
        item.update(overrides)
        return item

    def test_ok_fetch_issues_one_search_query_per_keyword(self):
        post = self._patched_post(return_value=JsonResponse(self.BODY))

        raw = self.adapter.fetch(['développeur'])

        self.assertEqual(len(raw), 3)
        post.assert_called_once()
        call = post.call_args
        self.assertEqual(call.args[0], 'https://api.ouedkniss.com/graphql')
        self.assertEqual(call.kwargs['timeout'], 30)
        self.assertIn('User-Agent', call.kwargs['headers'])
        payload = call.kwargs['json']
        self.assertEqual(payload['operationName'], 'SearchQuery')
        self.assertEqual(payload['variables']['q'], 'développeur')
        filter_ = payload['variables']['filter']
        self.assertEqual(filter_['categorySlug'], 'offres_demandes_emploi')
        self.assertEqual(filter_['page'], 1)
        self.assertEqual(filter_['count'], 50)
        self.assertEqual(filter_['orderByField'], {'field': 'REFRESHED_AT'})

    def test_ok_parse_exactly_six_keys_with_fixture_values(self):
        self._patched_post(return_value=JsonResponse(self.BODY))
        raw = self.adapter.fetch(['développeur'])
        parsed = self.adapter.parse(raw)

        self.assertEqual(len(parsed), 3)
        for item in parsed:
            self.assertEqual(
                set(item),
                {'title', 'company', 'url', 'published_at', 'keywords', 'raw_snapshot'},
            )
        first = parsed[0]
        self.assertEqual(first['title'], 'développeur web e-commerce')
        self.assertEqual(first['company'], 'recrutementgit')
        self.assertEqual(
            first['url'],
            'https://www.ouedkniss.com/commercial-marketing-developpeur-web-e-commerce-kouba-mohammadia-alger-algerie-d39785675',
        )
        self.assertEqual(first['published_at'], '2026-08-18T20:15:11.000Z')
        self.assertEqual(first['keywords'], ['développeur'])
        self.assertEqual(first['raw_snapshot'], self.ITEMS[0])
        # store: null -> company falls back to user.displayName
        self.assertEqual(parsed[1]['company'], 'societe industrielle')

    def test_keyword_multi_one_call_per_keyword_and_id_dedupe(self):
        second_body = copy.deepcopy(self.BODY)
        second_body['data']['search']['announcements']['data'] = [
            copy.deepcopy(self.ITEMS[1]),
            self._synthetic(1),
        ]
        post = self._patched_post(
            side_effect=[JsonResponse(self.BODY), JsonResponse(second_body)]
        )

        raw = self.adapter.fetch(['python', 'django'])

        self.assertEqual(post.call_count, 2)
        queries = [call.kwargs['json']['variables']['q'] for call in post.call_args_list]
        self.assertEqual(queries, ['python', 'django'])
        # 3 items from kw1 + 2 from kw2, minus 1 shared id -> 4 raw items.
        self.assertEqual(len(raw), 4)
        shared = [item for item in raw if item['item']['id'] == '57225396']
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0]['keyword'], 'python')

    def test_sample_capped_at_fifty(self):
        body = copy.deepcopy(self.BODY)
        body['data']['search']['announcements']['data'] = [self._synthetic(i) for i in range(60)]
        post = self._patched_post(return_value=JsonResponse(body))

        raw = self.adapter.fetch(['développeur'])

        self.assertEqual(len(raw), 50)
        # single keyword: one call; the output cap truncates, not the loop
        post.assert_called_once()

    def test_no_company_uses_empty_string(self):
        item = self._synthetic(2)
        item['user'] = None
        item['store'] = None

        parsed = self.adapter.parse([{'keyword': 'dev', 'item': item}])

        self.assertEqual(parsed[0]['company'], '')
        self.assertEqual(
            set(parsed[0]),
            {'title', 'company', 'url', 'published_at', 'keywords', 'raw_snapshot'},
        )

    def test_http_500_raises_with_keyword_context(self):
        self._patched_post(return_value=JsonResponse('oops', status_code=500))

        with self.assertRaises(OuedknissAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn('keyword', message)
        self.assertIn('500', message)

    def test_network_error_raises_with_keyword_context(self):
        self._patched_post(side_effect=ConnectionError('connection refused'))

        with self.assertRaises(OuedknissAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn("keyword 'python'", message)
        self.assertIn('connection refused', message)

    def test_invalid_json_raises_with_keyword_context(self):
        self._patched_post(
            return_value=JsonResponse(ValueError('Expecting value: line 1 column 1'))
        )

        with self.assertRaises(OuedknissAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn("keyword 'python'", message)
        self.assertIn('Expecting value', message)

    def test_graphql_errors_key_raises(self):
        self._patched_post(
            return_value=JsonResponse({'errors': [{'message': 'boom'}]})
        )

        with self.assertRaises(OuedknissAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn('GraphQL errors', message)
        self.assertIn('boom', message)

    def test_url_pinned_to_live_show_format(self):
        self._patched_post(return_value=JsonResponse(self.BODY))
        parsed = self.adapter.parse(self.adapter.fetch(['développeur']))

        for item in parsed:
            self.assertRegex(
                item['url'], r'^https://www\.ouedkniss\.com/.+-d\d+$'
            )

    def test_missing_slug_or_id_skips_item(self):
        items = [self._synthetic(3), self._synthetic(4), self._synthetic(5)]
        del items[0]['slug']
        del items[1]['id']

        parsed = self.adapter.parse([{'keyword': 'dev', 'item': item} for item in items])

        self.assertEqual(len(parsed), 1)

    def test_published_at_none_when_absent(self):
        item = self._synthetic(6)
        del item['refreshedAt']

        parsed = self.adapter.parse([{'keyword': 'dev', 'item': item}])

        self.assertIsNone(parsed[0]['published_at'])

    def test_store_name_fallback_when_user_absent(self):
        item = self._synthetic(7)
        item['user'] = None
        item['store'] = {'name': 'Boutique X'}

        parsed = self.adapter.parse([{'keyword': 'dev', 'item': item}])

        self.assertEqual(parsed[0]['company'], 'Boutique X')

    def test_non_string_slug_or_title_skips_item(self):
        items = [self._synthetic(9), self._synthetic(10)]
        items[0]['slug'] = 12345  # truthy non-str slug would build a garbage URL
        items[1]['title'] = 42

        parsed = self.adapter.parse([{'keyword': 'dev', 'item': item} for item in items])

        self.assertEqual(parsed, [])

    def test_timeout_raises_with_keyword_context(self):
        self._patched_post(side_effect=requests.exceptions.Timeout('timed out'))

        with self.assertRaises(OuedknissAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn("keyword 'python'", message)
        self.assertIn('timed out', message)

    def test_non_object_json_raises(self):
        self._patched_post(return_value=JsonResponse([1, 2]))

        with self.assertRaises(OuedknissAdapterError) as ctx:
            self.adapter.fetch(['python'])
        self.assertIn('non-object JSON', str(ctx.exception))

    def test_missing_search_shape_raises_labelled(self):
        self._patched_post(return_value=JsonResponse({'data': {}}))

        with self.assertRaises(OuedknissAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn('unexpected shape', message)
        self.assertIn("keyword 'python'", message)

    def test_cap_fifty_one_unique_items_returns_fifty(self):
        body = copy.deepcopy(self.BODY)
        body['data']['search']['announcements']['data'] = [
            self._synthetic(i) for i in range(51)
        ]
        post = self._patched_post(return_value=JsonResponse(body))

        raw = self.adapter.fetch(['développeur'])

        self.assertEqual(len(raw), 50)
        post.assert_called_once()

    def test_cap_mid_keyword_still_queries_remaining_keywords(self):
        body_one = copy.deepcopy(self.BODY)
        body_one['data']['search']['announcements']['data'] = [
            self._synthetic(i) for i in range(50)
        ]
        body_two = copy.deepcopy(self.BODY)
        body_two['data']['search']['announcements']['data'] = [
            self._synthetic(i) for i in range(50, 53)
        ]
        post = self._patched_post(
            side_effect=[JsonResponse(body_one), JsonResponse(body_two)]
        )

        raw = self.adapter.fetch(['python', 'django'])

        self.assertEqual(post.call_count, 2)
        self.assertEqual(len(raw), 50)
        # first-occurrence order: kw1's 50 items fill the cap
        self.assertTrue(all(item['keyword'] == 'python' for item in raw))

    def test_fetch_empty_keywords_returns_empty(self):
        post = self._patched_post(return_value=JsonResponse(self.BODY))

        raw = self.adapter.fetch([])

        self.assertEqual(raw, [])
        post.assert_not_called()

    def test_duplicate_keywords_two_calls_first_tag_wins(self):
        post = self._patched_post(return_value=JsonResponse(self.BODY))

        raw = self.adapter.fetch(['python', 'python'])

        self.assertEqual(post.call_count, 2)
        queries = [call.kwargs['json']['variables']['q'] for call in post.call_args_list]
        self.assertEqual(queries, ['python', 'python'])
        self.assertEqual(len(raw), 3)
        self.assertTrue(all(item['keyword'] == 'python' for item in raw))

    def test_blank_keyword_sends_empty_q(self):
        post = self._patched_post(return_value=JsonResponse(self.BODY))

        raw = self.adapter.fetch(['python', ''])

        self.assertEqual(post.call_count, 2)
        queries = [call.kwargs['json']['variables']['q'] for call in post.call_args_list]
        self.assertEqual(queries, ['python', ''])

    def test_data_null_response_returns_empty(self):
        self._patched_post(return_value=JsonResponse({'data': None}))

        self.assertEqual(self.adapter.fetch(['python']), [])

    def test_search_null_response_returns_empty(self):
        self._patched_post(return_value=JsonResponse({'data': {'search': None}}))

        self.assertEqual(self.adapter.fetch(['python']), [])

    def test_arabic_title_round_trips_unchanged(self):
        item = self._synthetic(8)
        item['title'] = 'مطور ويب'

        parsed = self.adapter.parse([{'keyword': 'web', 'item': item}])

        self.assertEqual(parsed[0]['title'], 'مطور ويب')

    def test_hostile_keyword_round_trips_through_json_payload(self):
        keyword = 'a"b\\c$d\n'
        post = self._patched_post(return_value=JsonResponse(self.BODY))

        self.adapter.fetch([keyword])

        payload = post.call_args.kwargs['json']
        self.assertEqual(
            json.loads(json.dumps(payload))['variables']['q'], keyword
        )
        # the query text is the module constant — never interpolated
        self.assertEqual(payload['query'], _SEARCH_QUERY)

    def test_fixture_metadata_probe_date_and_total(self):
        self.assertIn('_probe_date', OuedknissJobsAdapterTests.FIXTURE)
        paginator = self.BODY['data']['search']['announcements']['paginatorInfo']
        self.assertGreaterEqual(paginator['total'], len(self.ITEMS))


class OuedknissProductionRegistrationTests(SimpleTestCase):
    """The ouedkniss-jobs registry row comes from import time (no test
    scaffolding; setUp intentionally does not call clear())."""

    def test_ouedkniss_jobs_production_registration_resolves(self):
        self.assertIs(get_adapter('ouedkniss-jobs'), OuedknissJobsAdapter)


class OuedknissFullStackTests(TestCase):
    """Story 1.5 acceptance: registered adapter through collect_source.

    Relies on the import-time registration in collector/__init__.py.
    """

    def test_collect_source_logs_ok_and_stores_listings(self):
        source = Source.objects.create(
            name='ouedkniss-jobs',
            adapter_key='ouedkniss-jobs',
            config={'keywords': ['développeur']},
        )
        items = OuedknissJobsAdapterTests.ITEMS
        raw = [{'keyword': 'développeur', 'item': item} for item in items]
        with patch.object(OuedknissJobsAdapter, 'fetch', return_value=raw):
            created = collect_source(source)

        self.assertEqual(created, len(items))
        self.assertEqual(Listing.objects.count(), len(items))
        ok_log = FetchLog.objects.get(source=source, ok=True)
        self.assertEqual(ok_log.stage, 'persist')
        self.assertEqual(ok_log.error, '')
        listing = Listing.objects.get(
            url='https://www.ouedkniss.com/commercial-marketing-developpeur-web-e-commerce-kouba-mohammadia-alger-algerie-d39785675'
        )
        self.assertEqual(listing.title, 'développeur web e-commerce')
        self.assertEqual(listing.company, 'recrutementgit')
        self.assertEqual(
            listing.published_at.isoformat(), '2026-08-18T20:15:11+00:00'
        )
        self.assertEqual(listing.keywords, ['développeur'])
        # extract keeps the raw item verbatim: the fixture item survives
        # nested inside the stored snapshot chain
        self.assertEqual(
            listing.raw_snapshot,
            {
                'title': 'développeur web e-commerce',
                'company': 'recrutementgit',
                'url': 'https://www.ouedkniss.com/commercial-marketing-developpeur-web-e-commerce-kouba-mohammadia-alger-algerie-d39785675',
                'published_at': '2026-08-18T20:15:11.000Z',
                'keywords': ['développeur'],
                'raw_snapshot': items[0],
            },
        )
        self.assertEqual(listing.source, source)
        self.assertEqual(listing.seen_sources, ['ouedkniss-jobs'])
        self.assertEqual(listing.status, 'new')


# ---------------------------------------------------------------------------
# Story 1.6: google-jobs adapter (JobSpy)
# ---------------------------------------------------------------------------


class GoogleJobsAdapterTests(SimpleTestCase):
    """Story 1.6 matrix rows — hermetic against the recorded fixture.

    Every row monkeypatches `scrape_jobs` at the adapter module level
    (`collector.adapters.google_jobs.scrape_jobs`); no live network, no
    DB. The fixture `tests/fixtures/google_jobs_probe.json`
    records the probe outcome (2026-08-19: the live call succeeded but
    Google returned an empty DataFrame) and the verified JobSpy 1.1.82
    output schema (`desired_order` columns; `date_posted` is the posting
    date column — the spec-era `listed_time`/`posting_date` names do not
    exist in this version).
    """

    FIXTURE = json.loads(
        (
            Path(__file__).parent
            / 'tests'
            / 'fixtures'
            / 'google_jobs_probe.json'
        ).read_text(encoding='utf-8')
    )
    ROWS = FIXTURE['rows']

    def setUp(self):
        self.adapter = GoogleJobsAdapter()

    def _patched_scrape(self, side_effect=None, return_value=None):
        scrape = Mock(side_effect=side_effect, return_value=return_value)
        patcher = patch('collector.adapters.google_jobs.scrape_jobs', scrape)
        patcher.start()
        self.addCleanup(patcher.stop)
        return scrape

    def _fixture_df(self, rows=None):
        return pd.DataFrame(rows if rows is not None else self.ROWS)

    def _synthetic(self, index, **overrides):
        row = copy.deepcopy(self.ROWS[0])
        row['id'] = f'go-9{index:03d}'
        row['job_url'] = f'https://careers.example.com/jobs/{index}'
        row['title'] = f'Synthetic Job {index}'
        row.update(overrides)
        return row

    def test_ok_fetch_one_call_per_keyword_with_verified_kwargs(self):
        scrape = self._patched_scrape(return_value=self._fixture_df())

        raw = self.adapter.fetch(['développeur'])

        self.assertEqual(len(raw), 3)
        scrape.assert_called_once()
        call = scrape.call_args
        self.assertEqual(call.kwargs['site_name'], 'google')
        self.assertEqual(call.kwargs['search_term'], 'développeur')
        self.assertEqual(call.kwargs['location'], 'Algeria')
        self.assertEqual(call.kwargs['results_wanted'], 50)
        self.assertEqual(call.kwargs['hours_old'], 24)
        json.dumps(raw)  # sanitized at the seam: fully JSON-serializable
        for item in raw:
            self.assertEqual(set(item), {'keyword', 'item'})
            self.assertEqual(item['keyword'], 'développeur')

    def test_ok_parse_exactly_six_keys_with_fixture_values(self):
        self._patched_scrape(return_value=self._fixture_df())
        raw = self.adapter.fetch(['développeur'])
        parsed = self.adapter.parse(raw)

        self.assertEqual(len(parsed), 3)
        for item in parsed:
            self.assertEqual(
                set(item),
                {'title', 'company', 'url', 'published_at', 'keywords', 'raw_snapshot'},
            )
        first = parsed[0]
        self.assertEqual(first['title'], self.ROWS[0]['title'])
        self.assertEqual(first['company'], self.ROWS[0]['company'])
        self.assertEqual(first['url'], self.ROWS[0]['job_url'])
        self.assertEqual(first['published_at'], self.ROWS[0]['date_posted'])
        self.assertEqual(first['keywords'], ['développeur'])
        self.assertEqual(first['raw_snapshot'], raw[0]['item'])

    def test_keyword_multi_one_call_per_keyword_and_url_dedupe(self):
        second_rows = [
            copy.deepcopy(self.ROWS[0]),
            self._synthetic(1),
            self._synthetic(2),
        ]
        scrape = self._patched_scrape(
            side_effect=[self._fixture_df(), self._fixture_df(second_rows)]
        )

        raw = self.adapter.fetch(['python', 'django'])

        self.assertEqual(scrape.call_count, 2)
        terms = [call.kwargs['search_term'] for call in scrape.call_args_list]
        self.assertEqual(terms, ['python', 'django'])
        # 3 items from kw1 + 3 from kw2, minus 1 shared job_url -> 5 raw
        self.assertEqual(len(raw), 5)
        shared = [
            item
            for item in raw
            if item['item']['job_url'] == self.ROWS[0]['job_url']
        ]
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0]['keyword'], 'python')

    def test_empty_result_returns_empty(self):
        scrape = self._patched_scrape(return_value=pd.DataFrame())

        self.assertEqual(self.adapter.fetch(['python']), [])

        scrape.assert_called_once()

    def test_api_error_raises_with_keyword_context(self):
        self._patched_scrape(side_effect=ConnectionError('google blocked us'))

        with self.assertRaises(GoogleJobsAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn("keyword 'python'", message)
        self.assertIn('google blocked us', message)

    def test_timestamp_sanitize_to_json_safe(self):
        df = pd.DataFrame([
            {
                'title': 'Dev',
                'company': 'Co',
                'job_url': 'https://g.example/1',
                'date_posted': pd.Timestamp('2026-08-18T10:00:00'),
                'min_amount': np.nan,
                'company_reviews_count': None,
                'is_remote': np.bool_(False),
            },
            {
                'title': 'Dev 2',
                'company': 'Co 2',
                'job_url': 'https://g.example/2',
                'date_posted': pd.NaT,
                'min_amount': 10.0,
                'company_reviews_count': 3,
                # realistic drift shape: a python date cell in listed_time
                'listed_time': date(2026, 8, 17),
                'is_remote': np.bool_(True),
            },
        ])
        # object dtype keeps the numpy scalar in the cell through to_dict
        df['company_reviews_count'] = df['company_reviews_count'].astype(object)
        df.loc[0, 'company_reviews_count'] = np.int64(7)
        df['is_remote'] = df['is_remote'].astype(object)
        self._patched_scrape(return_value=df)

        raw = self.adapter.fetch(['python'])
        parsed = self.adapter.parse(raw)

        first = raw[0]['item']
        self.assertEqual(first['date_posted'], '2026-08-18T10:00:00')
        self.assertIsNone(first['min_amount'])
        self.assertEqual(first['company_reviews_count'], 7)
        self.assertIsInstance(first['company_reviews_count'], int)
        self.assertIs(first['is_remote'], False)
        second = raw[1]['item']
        self.assertIsNone(second['date_posted'])
        self.assertEqual(second['listed_time'], '2026-08-17')
        self.assertIs(second['is_remote'], True)
        json.dumps(raw)  # sanitized at the seam: fully JSON-serializable
        json.dumps(parsed)  # canonical dicts are JSON-serializable too
        self.assertEqual(parsed[1]['published_at'], '2026-08-17')

    def test_sanitize_value_numpy_scalars(self):
        self.assertEqual(_sanitize_value(np.int64(5)), 5)
        self.assertEqual(_sanitize_value(np.float64(2.5)), 2.5)
        self.assertIsNone(_sanitize_value(np.float64('nan')))
        self.assertIsNone(_sanitize_value(pd.NaT))
        self.assertIsNone(_sanitize_value(pd.NA))
        self.assertEqual(
            _sanitize_value(pd.Timestamp('2026-08-18T10:00:00')),
            '2026-08-18T10:00:00',
        )

    def test_non_dataframe_return_raises_labelled(self):
        # scrape_jobs drift: dict/list instead of a DataFrame would
        # AttributeError on .to_dict — must surface as the labelled
        # error with keyword context, never a bare AttributeError.
        for bad in ({'a': 1}, [1, 2]):
            with self.subTest(return_value=bad):
                with patch(
                    'collector.adapters.google_jobs.scrape_jobs', return_value=bad
                ):
                    with self.assertRaises(GoogleJobsAdapterError) as ctx:
                        self.adapter.fetch(['python'])
                message = str(ctx.exception)
                self.assertIn("keyword 'python'", message)
                self.assertIn("object has no attribute 'to_dict'", message)

    def test_df_conversion_failure_raises_labelled(self):
        self._patched_scrape(return_value=self._fixture_df())
        with patch.object(
            pd.DataFrame, 'to_dict', side_effect=ValueError('to_dict exploded')
        ):
            with self.assertRaises(GoogleJobsAdapterError) as ctx:
                self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn("keyword 'python'", message)
        self.assertIn('to_dict exploded', message)

    def test_date_posted_as_datetime_date(self):
        # jobspy's google path emits datetime.date in date_posted; a
        # python date cell must sanitize to the date-only ISO string.
        df = pd.DataFrame([
            {
                'title': 'Dev',
                'company': 'Co',
                'job_url': 'https://g.example/1',
                'date_posted': date(2026, 8, 18),
            },
        ])
        self._patched_scrape(return_value=df)

        raw = self.adapter.fetch(['python'])

        self.assertEqual(raw[0]['item']['date_posted'], '2026-08-18')
        parsed = self.adapter.parse(raw)
        self.assertEqual(parsed[0]['published_at'], '2026-08-18')

    def test_timestamp_tz_aware_iso(self):
        df = pd.DataFrame([
            {
                'title': 'Dev',
                'company': 'Co',
                'job_url': 'https://g.example/1',
                'date_posted': pd.Timestamp('2026-08-18T10:00:00+01:00'),
            },
        ])
        self._patched_scrape(return_value=df)

        raw = self.adapter.fetch(['python'])

        # offset preserved through isoformat, not shifted to UTC
        self.assertEqual(raw[0]['item']['date_posted'], '2026-08-18T10:00:00+01:00')
        self.assertEqual(
            self.adapter.parse(raw)[0]['published_at'], '2026-08-18T10:00:00+01:00'
        )

    def test_published_at_fallback_column(self):
        # no date_posted column: _posted_at must fall back to the
        # spec-era names listed_time / posting_date (drift fallbacks).
        df = pd.DataFrame([
            {
                'title': 'Dev',
                'company': 'Co',
                'job_url': 'https://g.example/1',
                'listed_time': '2026-08-17',
            },
            {
                'title': 'Dev 2',
                'company': 'Co 2',
                'job_url': 'https://g.example/2',
                'posting_date': '2026-08-16',
            },
        ])
        self._patched_scrape(return_value=df)

        parsed = self.adapter.parse(self.adapter.fetch(['python']))

        self.assertEqual(parsed[0]['published_at'], '2026-08-17')
        self.assertEqual(parsed[1]['published_at'], '2026-08-16')

    def test_hours_old_zero_defaults(self):
        # 0 is falsy in jobspy's google path (disables the freshness
        # window -> unbounded scrape); negatives widen to 'last month'.
        for bad in (0, -5, None):
            with self.subTest(hours_old=bad):
                adapter = GoogleJobsAdapter(config={'hours_old': bad})
                with patch(
                    'collector.adapters.google_jobs.scrape_jobs',
                    return_value=self._fixture_df(),
                ) as scrape:
                    adapter.fetch(['python'])
                self.assertEqual(scrape.call_args.kwargs['hours_old'], DEFAULT_HOURS_OLD)

    def test_no_company_uses_empty_string(self):
        df = pd.DataFrame([
            {'title': 'Dev', 'company': None, 'job_url': 'https://g.example/1'},
            {'title': 'Dev 2', 'company': np.nan, 'job_url': 'https://g.example/2'},
        ])
        self._patched_scrape(return_value=df)

        parsed = self.adapter.parse(self.adapter.fetch(['dev']))

        self.assertEqual(parsed[0]['company'], '')
        self.assertEqual(parsed[1]['company'], '')
        self.assertEqual(
            set(parsed[0]),
            {'title', 'company', 'url', 'published_at', 'keywords', 'raw_snapshot'},
        )

    def test_cap_boundary_fifty_one_unique_urls_returns_fifty(self):
        rows = [self._synthetic(i) for i in range(51)]
        scrape = self._patched_scrape(
            side_effect=[self._fixture_df(rows[:50]), self._fixture_df(rows[50:])]
        )

        raw = self.adapter.fetch(['python', 'django'])

        # all keywords searched: the cap never short-circuits the loop
        self.assertEqual(scrape.call_count, 2)
        self.assertEqual(len(raw), 50)
        # first-occurrence order: kw1's 50 items fill the cap
        self.assertTrue(all(item['keyword'] == 'python' for item in raw))

    def test_fetch_empty_keywords_returns_empty(self):
        scrape = self._patched_scrape(return_value=self._fixture_df())

        self.assertEqual(self.adapter.fetch([]), [])

        scrape.assert_not_called()

    def test_blank_keyword_sent_as_search_term(self):
        scrape = self._patched_scrape(return_value=self._fixture_df())

        self.adapter.fetch(['python', ''])

        self.assertEqual(scrape.call_count, 2)
        terms = [call.kwargs['search_term'] for call in scrape.call_args_list]
        self.assertEqual(terms, ['python', ''])

    def test_duplicate_keywords_two_calls_first_tag_wins(self):
        scrape = self._patched_scrape(return_value=self._fixture_df())

        raw = self.adapter.fetch(['python', 'python'])

        self.assertEqual(scrape.call_count, 2)
        self.assertEqual(len(raw), 3)
        self.assertTrue(all(item['keyword'] == 'python' for item in raw))

    def test_fixture_probe_metadata(self):
        self.assertEqual(GoogleJobsAdapterTests.FIXTURE['_probe_date'], '2026-08-19')
        self.assertEqual(
            GoogleJobsAdapterTests.FIXTURE['_probe']['outcome'],
            'empty DataFrame (call succeeded; Google served no results for the window)',
        )
        for name in ('title', 'company', 'job_url', 'date_posted'):
            self.assertIn(name, GoogleJobsAdapterTests.FIXTURE['columns'])


class GoogleJobsProductionRegistrationTests(SimpleTestCase):
    """The google-jobs registry row comes from import time (no test
    scaffolding; setUp intentionally does not call clear())."""

    def test_google_jobs_production_registration_resolves(self):
        self.assertIs(get_adapter('google-jobs'), GoogleJobsAdapter)


class GoogleJobsFullStackTests(TestCase):
    """Story 1.6 acceptance: registered adapter through collect_source.

    Relies on the import-time registration in collector/__init__.py.
    """

    def test_collect_source_logs_ok_and_stores_listings(self):
        source = Source.objects.create(
            name='google-jobs',
            adapter_key='google-jobs',
            config={'keywords': ['développeur']},
        )
        rows = GoogleJobsAdapterTests.ROWS
        raw = [{'keyword': 'développeur', 'item': row} for row in rows]
        with patch.object(GoogleJobsAdapter, 'fetch', return_value=raw):
            created = collect_source(source)

        self.assertEqual(created, len(rows))
        self.assertEqual(Listing.objects.count(), len(rows))
        ok_log = FetchLog.objects.get(source=source, ok=True)
        self.assertEqual(ok_log.stage, 'persist')
        self.assertEqual(ok_log.error, '')
        listing = Listing.objects.get(url=rows[0]['job_url'])
        self.assertEqual(listing.title, rows[0]['title'])
        self.assertEqual(listing.company, rows[0]['company'])
        # date-only fixture date_posted normalizes to midnight UTC
        self.assertEqual(
            listing.published_at.isoformat(), '2026-08-18T00:00:00+00:00'
        )
        self.assertEqual(listing.keywords, ['développeur'])
        # extract keeps the raw item verbatim: the fixture row survives
        # nested inside the stored snapshot chain
        self.assertEqual(
            listing.raw_snapshot,
            {
                'title': rows[0]['title'],
                'company': rows[0]['company'],
                'url': rows[0]['job_url'],
                'published_at': rows[0]['date_posted'],
                'keywords': ['développeur'],
                'raw_snapshot': rows[0],
            },
        )
        self.assertEqual(listing.source, source)
        self.assertEqual(listing.seen_sources, ['google-jobs'])
        self.assertEqual(listing.status, 'new')


# ---------------------------------------------------------------------------
# Story 1.7: facebook-groups adapter (Playwright)
# ---------------------------------------------------------------------------

GROUP_1 = 'https://www.facebook.com/groups/1248610773920835'
GROUP_2 = 'https://www.facebook.com/groups/9876543210987654'

FACEBOOK_FIXTURE = (
    Path(__file__).parent / 'tests' / 'fixtures' / 'facebook_feed.html'
).read_text(encoding='utf-8')
# The scoped extraction selector (review loopback, F6): post cards are
# queried INSIDE the feed container so sidebar/suggested-group articles
# OUTSIDE the pagelet are never extracted.
FACEBOOK_CARD_SELECTOR = f'{FEED_CONTAINER_SELECTOR} {POST_CARD_SELECTOR}'


def _fake_card_from_node(node):
    """One fake card element from a parsel node (pinned selectors).

    Playwright semantics: a dir="auto" block's text nodes are joined
    with '\n' inside inner_text; a card with several blocks stores them
    as a list under POST_TEXT_SELECTOR so the adapter's all-blocks loop
    sees every paragraph (review loopback, F12).
    """
    children = {}
    text_hits = node.css(POST_TEXT_SELECTOR)
    if text_hits:
        children[POST_TEXT_SELECTOR] = [
            _FakeElement(text='\n'.join(hit.css('::text').getall()))
            for hit in text_hits
        ]
    author_hit = node.css(AUTHOR_SELECTOR)
    if author_hit:
        children[AUTHOR_SELECTOR] = _FakeElement(
            text='\n'.join(author_hit[0].css('::text').getall())
        )
    link_hit = node.css(PERMALINK_SELECTOR)
    if link_hit:
        children[PERMALINK_SELECTOR] = _FakeElement(
            attrs={'href': link_hit[0].attrib.get('href', '')}
        )
    return _FakeElement(children=children)


def _fixture_fake_cards():
    """Fixture cards through the SCOPED selector, exactly like the adapter."""
    doc = parsel.Selector(text=FACEBOOK_FIXTURE)
    return [
        _fake_card_from_node(node)
        for node in doc.css(FACEBOOK_CARD_SELECTOR)
    ]


class _FakeElement:
    """Minimal playwright element handle: children keyed by selector,
    plus get_attribute/inner_text (the subset the adapter drives).

    query_selector_all returns the stored list (several dir="auto"
    blocks) or a single element wrapped in a list — the adapter's text
    loop joins each block's inner_text with '\n'.
    """

    def __init__(self, children=None, attrs=None, text=''):
        self._children = children or {}
        self._attrs = attrs or {}
        self._text = text

    def query_selector(self, selector):
        found = self._children.get(selector)
        if isinstance(found, list):
            return found[0] if found else None
        return found

    def query_selector_all(self, selector):
        found = self._children.get(selector)
        if found is None:
            return []
        return found if isinstance(found, list) else [found]

    def get_attribute(self, name):
        return self._attrs.get(name)

    def inner_text(self):
        return self._text


class _FakePage:
    """Playwright Page subset the adapter drives, scripted per scenario:
    rendered feed, login wall (marker and/or redirect URL), wall that
    appears only after load, navigation/wait timeouts, zero-post feed,
    cards missing permalink/author, close failures.

    Fidelity (review loopback, F12): wait_for_selector asserts that the
    feed wait targets the pinned feed-container selector, so extraction
    drift fails loudly instead of passing silently; the wall marker is
    scripted per probe via `wall_probes` (wall-after-load scenarios).
    """

    def __init__(self, cards=None, wall=False, url='', goto_error=None,
                 wait_error=None, gotos=None, wall_probes=None,
                 close_error=None):
        self.cards = list(cards or [])
        self.wall = wall
        self.url = url
        self.goto_error = goto_error
        self.wait_error = wait_error
        self.gotos = gotos
        self.wall_probes = list(wall_probes) if wall_probes is not None else None
        self.close_error = close_error
        self.closed = False
        self.feed_waits = 0

    def goto(self, url, timeout=None):
        if self.gotos is not None:
            self.gotos.append(url)
        if self.goto_error is not None:
            raise self.goto_error

    def _wall_marker_present(self):
        if self.wall_probes is not None:
            if self.wall_probes:
                return self.wall_probes.pop(0)
            return self.wall
        return self.wall

    def wait_for_selector(self, selector, timeout=None, state=None):
        if selector == LOGIN_WALL_SELECTOR:
            if self._wall_marker_present():
                return _FakeElement()
            raise TimeoutError(f'Timeout {timeout}ms exceeded')
        assert selector == FEED_CONTAINER_SELECTOR
        self.feed_waits += 1
        if self.wait_error is not None:
            raise self.wait_error
        return _FakeElement()

    def query_selector(self, selector):
        if self.wall and selector == LOGIN_WALL_SELECTOR:
            return _FakeElement()
        return None

    def query_selector_all(self, selector):
        if selector == FACEBOOK_CARD_SELECTOR:
            return list(self.cards)
        return []

    def close(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class _FakeContext:
    """Hands out one scripted page per group visit; records closes."""

    def __init__(self, pages=None, new_page_error=None, close_error=None):
        self.pages = list(pages or [])
        self.new_page_error = new_page_error
        self.close_error = close_error
        self.closed = False

    def new_page(self):
        if self.new_page_error is not None:
            raise self.new_page_error
        return self.pages.pop(0)

    def close(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class _FakeBrowser:
    def __init__(self, context=None, launch_error=None, context_error=None,
                 close_error=None):
        self.context = context or _FakeContext()
        self.launch_error = launch_error
        self.context_error = context_error
        self.close_error = close_error
        self.closed = False

    def new_context(self):
        if self.context_error is not None:
            raise self.context_error
        return self.context

    def close(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class _FakePlaywright:
    """Stand-in for sync_playwright(): `with ... as p:` yields a fake
    whose chromium.launch() returns the scripted browser."""

    def __init__(self, browser, enter_error=None):
        self.browser = browser
        self.enter_error = enter_error

    def __enter__(self):
        if self.enter_error is not None:
            raise self.enter_error
        return self

    def __exit__(self, *exc_info):
        return False

    @property
    def chromium(self):
        return self

    def launch(self, headless=True):
        if self.browser.launch_error is not None:
            raise self.browser.launch_error
        return self.browser


class FacebookGroupsAdapterTests(SimpleTestCase):
    """Story 1.7 matrix rows — hermetic against fake page objects.

    Every row patches `sync_playwright` at the adapter module level
    (`collector.adapters.facebook_groups.sync_playwright`); no live
    network, no real Playwright API, no browser. The fixture
    `tests/fixtures/facebook_feed.html` (documented 2026-08-19) is the
    selector ground truth: card fakes are built by parsing it through the
    adapter's pinned selectors (parsel), so selector/fixture drift fails
    loudly.
    """

    FIXTURE = FACEBOOK_FIXTURE

    def setUp(self):
        self.adapter = FacebookGroupsAdapter(config={'groups': [GROUP_1]})

    def _patch_playwright(self, browser):
        fake_pw = _FakePlaywright(browser)
        patcher = patch(
            'collector.adapters.facebook_groups.sync_playwright',
            return_value=fake_pw,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake_pw

    def _fixture_cards(self):
        return _fixture_fake_cards()

    def _card(self, index, author='Author X', text=None, href=None,
              with_link=True):
        if with_link and href is None:
            href = f'/groups/g/posts/{index}'
        children = {
            POST_TEXT_SELECTOR: _FakeElement(
                text=text if text is not None else f'Post text {index}'
            ),
            AUTHOR_SELECTOR: _FakeElement(text=author),
        }
        if href:
            children[PERMALINK_SELECTOR] = _FakeElement(attrs={'href': href})
        return _FakeElement(children=children)

    def test_ok_fetch_three_raw_items_and_parse_keyword_filtered(self):
        page = _FakePage(cards=self._fixture_cards())
        browser = _FakeBrowser(context=_FakeContext(pages=[page]))
        self._patch_playwright(browser)

        raw = self.adapter.fetch(['développeur'])

        self.assertEqual(len(raw), 3)
        # browser lifecycle: page/context/browser all close on the happy path
        self.assertTrue(page.closed)
        self.assertTrue(browser.context.closed)
        self.assertTrue(browser.closed)
        # decoys excluded: the nested comment article (no permalink) and
        # the sidebar article (outside the feed container) never surface
        permalinks = [item['permalink'] for item in raw]
        self.assertNotIn(f'{BASE_URL}/groups/9999999999999999/posts/1', permalinks)
        # URL variants emitted as-is: trailing slash and ?comment_id= kept
        self.assertEqual(
            permalinks,
            [
                f'{BASE_URL}/groups/1248610773920835/posts/101/',
                f'{BASE_URL}/groups/1248610773920835/posts/102?comment_id=987654321',
                f'{BASE_URL}/groups/1248610773920835/posts/103',
            ],
        )
        # the nested comment's body never pollutes the parent post text
        self.assertEqual(
            raw[0]['text'],
            'Urgent recrutement développeur web à Alger, CDI temps plein.',
        )
        # multi-paragraph post: every dir="auto" block, joined with '\n'
        self.assertEqual(
            raw[1]['text'],
            'Vente voiture Peugeot 208 essence, très bon état.\n'
            'Prix négociable, visite possible à Alger.',
        )

        parsed = self.adapter.parse(raw)

        self.assertEqual(len(parsed), 1)  # only the fixture card matching the keyword
        first = parsed[0]
        self.assertEqual(
            set(first),
            {'title', 'company', 'url', 'published_at', 'keywords', 'raw_snapshot'},
        )
        self.assertEqual(
            first['title'], 'Urgent recrutement développeur web à Alger, CDI temps plein.'
        )
        self.assertEqual(first['company'], 'Karim Benali')
        self.assertEqual(
            first['url'],
            f'{BASE_URL}/groups/1248610773920835/posts/101/',
        )
        self.assertIsNone(first['published_at'])
        self.assertEqual(first['keywords'], ['développeur'])
        self.assertEqual(
            first['raw_snapshot'],
            {
                'text': 'Urgent recrutement développeur web à Alger, CDI temps plein.',
                'author': 'Karim Benali',
                'permalink': f'{BASE_URL}/groups/1248610773920835/posts/101/',
            },
        )

    def test_keyword_filter_case_insensitive_any_match(self):
        self.adapter.keywords = ['développeur', 'commercial']
        self.adapter._fetched = True
        raw = [
            {
                'text': 'Besoin d un DÉVELOPPEUR python confirmé',
                'author': 'A',
                'permalink': f'{BASE_URL}/groups/1/posts/1',
            },
            {
                'text': 'Aucun mot clé ici',
                'author': 'B',
                'permalink': f'{BASE_URL}/groups/1/posts/2',
            },
            {
                'text': 'Commercial et développeur h/f recherchés',
                'author': 'C',
                'permalink': f'{BASE_URL}/groups/1/posts/3',
            },
        ]

        parsed = self.adapter.parse(raw)

        self.assertEqual(len(parsed), 2)
        # case-insensitive substring match; original keyword string emitted
        self.assertEqual(parsed[0]['keywords'], ['développeur'])
        # a post matching two keywords lists both, in keyword-set order
        self.assertEqual(parsed[1]['keywords'], ['développeur', 'commercial'])

    def test_multi_group_order_dedupe_and_browser_lifecycle(self):
        gotos = []
        page_a = _FakePage(cards=[self._card(1), self._card(2)], gotos=gotos)
        page_b = _FakePage(cards=[self._card(2), self._card(3)], gotos=gotos)
        adapter = FacebookGroupsAdapter(config={'groups': [GROUP_1, GROUP_2]})
        browser = _FakeBrowser(context=_FakeContext(pages=[page_a, page_b]))
        self._patch_playwright(browser)

        raw = adapter.fetch(['python'])

        # both groups visited, in config order
        self.assertEqual(gotos, [GROUP_1, GROUP_2])
        # 4 cards - 1 shared permalink (deduped across groups) = 3 raw
        self.assertEqual(len(raw), 3)
        permalinks = [item['permalink'] for item in raw]
        self.assertEqual(len(set(permalinks)), 3)
        self.assertTrue(page_a.closed)
        self.assertTrue(page_b.closed)
        self.assertTrue(browser.context.closed)
        self.assertTrue(browser.closed)

    def test_no_posts_valid_empty(self):
        page = _FakePage(cards=[])
        browser = _FakeBrowser(context=_FakeContext(pages=[page]))
        self._patch_playwright(browser)

        self.assertEqual(self.adapter.fetch(['python']), [])
        self.assertTrue(browser.closed)

    def test_login_wall_labelled_with_group_context(self):
        page = _FakePage(cards=[], wall=True)
        browser = _FakeBrowser(context=_FakeContext(pages=[page]))
        self._patch_playwright(browser)

        with self.assertRaises(FacebookGroupsAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn('login required', message)
        self.assertIn(GROUP_1, message)
        # the wall check runs BEFORE the feed wait: the feed is never
        # waited for on a wall
        self.assertEqual(page.feed_waits, 0)
        # the failed group still closes the browser cleanly
        self.assertTrue(browser.closed)

    def test_login_wall_redirect_url_labelled_with_group_context(self):
        # compound check (blind #3/#4, F4): '/login' in page.url counts
        # as a wall even when the marker is not present
        page = _FakePage(cards=[], url='https://www.facebook.com/login/')
        browser = _FakeBrowser(context=_FakeContext(pages=[page]))
        self._patch_playwright(browser)

        with self.assertRaises(FacebookGroupsAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn('login required', message)
        self.assertIn(GROUP_1, message)
        self.assertEqual(page.feed_waits, 0)
        self.assertTrue(browser.closed)

    def test_wall_and_feed_co_present_labelled_login_required(self):
        # a gated group whose page renders BOTH the wall marker and the
        # feed must be labelled 'login required', never NAV_TIMEOUT
        page = _FakePage(cards=self._fixture_cards(), wall=True)
        browser = _FakeBrowser(context=_FakeContext(pages=[page]))
        self._patch_playwright(browser)

        with self.assertRaises(FacebookGroupsAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn('login required', message)
        self.assertNotIn('timeout', message.lower())
        self.assertEqual(page.feed_waits, 0)

    def test_wall_after_load_labelled_login_required_not_nav_timeout(self):
        # the wall marker appears only AFTER the feed-wait timeout: the
        # re-probe on the timeout path must report 'login required'
        page = _FakePage(
            cards=[],
            wall_probes=[False, True],
            wait_error=TimeoutError('Timeout 30000ms exceeded'),
        )
        browser = _FakeBrowser(context=_FakeContext(pages=[page]))
        self._patch_playwright(browser)

        with self.assertRaises(FacebookGroupsAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn('login required', message)
        self.assertNotIn('timeout', message.lower())
        self.assertIn(GROUP_1, message)
        self.assertTrue(browser.closed)

    def test_slow_public_group_wall_reprobe_does_not_false_positive(self):
        # a slow public group: no wall before, none after the feed-wait
        # timeout -> labelled NAV_TIMEOUT, never 'login required'
        page = _FakePage(
            cards=[],
            wall_probes=[False, False],
            wait_error=TimeoutError('Timeout 30000ms exceeded'),
        )
        browser = _FakeBrowser(context=_FakeContext(pages=[page]))
        self._patch_playwright(browser)

        with self.assertRaises(FacebookGroupsAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn(GROUP_1, message)
        self.assertIn('timeout', message.lower())
        self.assertNotIn('login required', message)

    def test_nav_timeout_labelled_with_group_context(self):
        for label, wait_error, goto_error in (
            ('wait_for_selector', TimeoutError('Timeout 30000ms exceeded'), None),
            ('goto', None, TimeoutError('Navigation timeout')),
        ):
            with self.subTest(stage=label):
                page = _FakePage(
                    cards=[], wait_error=wait_error, goto_error=goto_error
                )
                browser = _FakeBrowser(context=_FakeContext(pages=[page]))
                self._patch_playwright(browser)
                with self.assertRaises(FacebookGroupsAdapterError) as ctx:
                    self.adapter.fetch(['python'])
                message = str(ctx.exception)
                self.assertIn(GROUP_1, message)
                self.assertIn('timeout', message.lower())

    def test_browser_launch_failure_labelled(self):
        browser = _FakeBrowser(
            context=_FakeContext(), launch_error=RuntimeError('launch exploded')
        )
        self._patch_playwright(browser)

        with self.assertRaises(FacebookGroupsAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn('browser failed', message)
        self.assertIn('launch exploded', message)

    def test_new_context_failure_labelled_browser(self):
        browser = _FakeBrowser(context_error=RuntimeError('context exploded'))
        self._patch_playwright(browser)

        with self.assertRaises(FacebookGroupsAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn('browser failed', message)
        self.assertIn('context exploded', message)
        self.assertTrue(browser.closed)

    def test_new_page_failure_labelled_with_group_context(self):
        browser = _FakeBrowser(
            context=_FakeContext(
                pages=[], new_page_error=RuntimeError('page exploded')
            )
        )
        self._patch_playwright(browser)

        with self.assertRaises(FacebookGroupsAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn(GROUP_1, message)
        self.assertIn('page exploded', message)
        self.assertTrue(browser.context.closed)
        self.assertTrue(browser.closed)

    def test_playwright_enter_failure_labelled(self):
        fake_pw = _FakePlaywright(
            _FakeBrowser(), enter_error=RuntimeError('playwright exploded')
        )
        patcher = patch(
            'collector.adapters.facebook_groups.sync_playwright',
            return_value=fake_pw,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        with self.assertRaises(FacebookGroupsAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn('browser failed', message)
        self.assertIn('playwright exploded', message)

    def test_page_close_failure_never_masks_in_flight_error(self):
        # F2: a teardown failure must never replace the labelled
        # in-flight error (the login wall here)
        page = _FakePage(
            cards=[], wall=True, close_error=RuntimeError('close exploded')
        )
        browser = _FakeBrowser(context=_FakeContext(pages=[page]))
        self._patch_playwright(browser)

        with self.assertRaises(FacebookGroupsAdapterError) as ctx:
            self.adapter.fetch(['python'])
        message = str(ctx.exception)
        self.assertIn('login required', message)
        self.assertNotIn('close exploded', message)
        # the rest of the teardown still runs
        self.assertTrue(browser.context.closed)
        self.assertTrue(browser.closed)

    def test_teardown_close_failures_on_happy_path_swallowed(self):
        page = _FakePage(cards=[self._card(1)])
        context = _FakeContext(
            pages=[page], close_error=RuntimeError('context close exploded')
        )
        browser = _FakeBrowser(
            context=context, close_error=RuntimeError('browser close exploded')
        )
        self._patch_playwright(browser)

        raw = self.adapter.fetch(['python'])

        self.assertEqual(len(raw), 1)
        self.assertTrue(page.closed)
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)

    def test_dedupe_collapses_slash_and_query_variants(self):
        # F8: the dedupe identity is (netloc.lower(), path) — trailing
        # slashes, ?comment_id= queries and host casing collapse onto
        # the first occurrence; the permalink is emitted as-is
        page = _FakePage(cards=[
            self._card(1, href='/groups/g/posts/5'),
            self._card(2, href='/groups/g/posts/5/'),
            self._card(3, href='https://WWW.FACEBOOK.com/groups/g/posts/5?comment_id=123'),
        ])
        browser = _FakeBrowser(context=_FakeContext(pages=[page]))
        self._patch_playwright(browser)

        raw = self.adapter.fetch(['python'])

        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0]['permalink'], f'{BASE_URL}/groups/g/posts/5')

    def test_parse_without_fetch_raises_labelled(self):
        adapter = FacebookGroupsAdapter(config={'groups': [GROUP_1]})

        with self.assertRaises(FacebookGroupsAdapterError) as ctx:
            adapter.parse([{
                'text': 'Recrutement développeur web',
                'author': 'A',
                'permalink': f'{BASE_URL}/groups/g/posts/9',
            }])
        message = str(ctx.exception)
        self.assertIn('parse', message)
        self.assertIn('before fetch', message)

    def test_card_without_permalink_skipped(self):
        page = _FakePage(
            cards=[
                self._card(1),
                self._card(2, with_link=False),  # no link element at all
                self._card(3, href=''),  # link with empty href
            ]
        )
        browser = _FakeBrowser(context=_FakeContext(pages=[page]))
        self._patch_playwright(browser)

        raw = self.adapter.fetch(['python'])

        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0]['permalink'], f'{BASE_URL}/groups/g/posts/1')

    def test_missing_author_company_empty(self):
        self.adapter.keywords = ['développeur']
        self.adapter._fetched = True
        raw = [{
            'text': 'Recrutement développeur web',
            'author': '',
            'permalink': f'{BASE_URL}/groups/g/posts/9',
        }]

        parsed = self.adapter.parse(raw)

        self.assertEqual(parsed[0]['company'], '')

    def test_missing_author_element_fetch_yields_empty_author(self):
        card = _FakeElement(children={
            POST_TEXT_SELECTOR: _FakeElement(text='Recrutement développeur web'),
            PERMALINK_SELECTOR: _FakeElement(
                attrs={'href': '/groups/g/posts/9'}
            ),
        })
        page = _FakePage(cards=[card])
        browser = _FakeBrowser(context=_FakeContext(pages=[page]))
        self._patch_playwright(browser)

        raw = self.adapter.fetch(['python'])

        self.assertEqual(raw[0]['author'], '')

    def test_long_text_title_truncated_to_500(self):
        self.adapter.keywords = ['développeur']
        self.adapter._fetched = True
        line = 'Recrutement développeur ' + 'x' * 600
        text = '\n\n' + line + '\nsecond line ignored'
        raw = [{
            'text': text,
            'author': 'A',
            'permalink': f'{BASE_URL}/groups/g/posts/9',
        }]

        parsed = self.adapter.parse(raw)

        self.assertEqual(len(parsed[0]['title']), 500)
        self.assertEqual(parsed[0]['title'], line[:500])
        self.assertNotIn('second line', parsed[0]['title'])
        # raw_snapshot keeps the FULL text (the cap lives in the pipeline)
        self.assertEqual(parsed[0]['raw_snapshot']['text'], text)

    def test_cap_boundary_51_unique_across_groups_both_visited(self):
        gotos = []
        # 50 unique permalinks in group 1; group 2 re-posts the same 50
        # plus one new -> 51 unique, capped at 50 first-occurrence.
        page_a = _FakePage(cards=[self._card(i) for i in range(50)], gotos=gotos)
        page_b = _FakePage(
            cards=[self._card(i) for i in range(50)] + [self._card(50)],
            gotos=gotos,
        )
        adapter = FacebookGroupsAdapter(config={'groups': [GROUP_1, GROUP_2]})
        browser = _FakeBrowser(context=_FakeContext(pages=[page_a, page_b]))
        self._patch_playwright(browser)

        raw = adapter.fetch(['python'])

        self.assertEqual(len(raw), 50)
        # the cap never short-circuits the group loop: both visited
        self.assertEqual(gotos, [GROUP_1, GROUP_2])
        self.assertTrue(page_b.closed)
        self.assertTrue(browser.context.closed)
        self.assertTrue(browser.closed)

    def test_config_bad_groups_labelled_before_browser_launch(self):
        for bad_config in (
            None,
            {},
            {'groups': []},
            {'groups': 'https://www.facebook.com/groups/123'},
            {'groups': ['https://www.facebook.com/groups/123', 42]},
        ):
            with self.subTest(config=bad_config):
                adapter = FacebookGroupsAdapter(config=bad_config)
                with patch(
                    'collector.adapters.facebook_groups.sync_playwright'
                ) as pw:
                    with self.assertRaises(FacebookGroupsAdapterError) as ctx:
                        adapter.fetch(['python'])
                self.assertIn("'groups'", str(ctx.exception))
                # config is validated before any browser work
                pw.assert_not_called()

    def test_fixture_documents_selector_ground_truth(self):
        self.assertIn('2026-08-19', self.FIXTURE)
        doc = parsel.Selector(text=self.FIXTURE)
        self.assertEqual(len(doc.css(FEED_CONTAINER_SELECTOR)), 1)
        # Decoys: a nested comment article inside card 1 and a
        # sidebar/suggested-group article OUTSIDE the feed container —
        # both match the BARE card selector (5 articles total).
        self.assertEqual(len(doc.css(POST_CARD_SELECTOR)), 5)
        # Scoping (feed container + card, F6) excludes the sidebar; the
        # nested comment still matches the scoped selector but carries no
        # permalink, so extraction yields exactly the 3 real cards.
        scoped = FACEBOOK_CARD_SELECTOR
        scoped_cards = doc.css(scoped)
        self.assertEqual(len(scoped_cards), 4)
        real = [card for card in scoped_cards if card.css(PERMALINK_SELECTOR)]
        self.assertEqual(len(real), 3)
        for card in real:
            self.assertTrue(card.css(POST_TEXT_SELECTOR))
            self.assertTrue(card.css(AUTHOR_SELECTOR))
        # URL variants pinned as-is: trailing slash + ?comment_id= query
        hrefs = [card.css(PERMALINK_SELECTOR)[0].attrib['href'] for card in real]
        self.assertEqual(hrefs, [
            '/groups/1248610773920835/posts/101/',
            '/groups/1248610773920835/posts/102?comment_id=987654321',
            '/groups/1248610773920835/posts/103',
        ])
        # dedupe identity (F8): the (netloc, path) keys stay distinct for
        # distinct posts — the variants collapse onto these keys, never
        # off them
        keys = []
        for href in hrefs:
            parts = urlsplit(urljoin(BASE_URL, href))
            keys.append((parts.netloc.lower(), parts.path.rstrip('/')))
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(
            keys,
            [
                ('www.facebook.com', '/groups/1248610773920835/posts/101'),
                ('www.facebook.com', '/groups/1248610773920835/posts/102'),
                ('www.facebook.com', '/groups/1248610773920835/posts/103'),
            ],
        )
        # multi-paragraph card (2): two dir="auto" blocks, joined with
        # '\n' (F7 — the fake inner_text joins block text nodes with
        # '\n', the adapter joins the blocks the same way)
        blocks = real[1].css(POST_TEXT_SELECTOR)
        self.assertEqual(len(blocks), 2)
        joined = '\n'.join(
            '\n'.join(block.css('::text').getall()) for block in blocks
        )
        self.assertEqual(
            joined,
            'Vente voiture Peugeot 208 essence, très bon état.\n'
            'Prix négociable, visite possible à Alger.',
        )
        # card 1 carries the nested comment decoy: single dir="auto"
        # block (the comment's body is a plain div, never polluting the
        # parent post text)
        self.assertEqual(len(real[0].css(POST_TEXT_SELECTOR)), 1)
        # the nested comment decoy has NO permalink (skipped by the
        # no-permalink rule) and NO dir="auto" body; the sidebar decoy
        # HAS a permalink (excluded by scoping only)
        comment = [
            card for card in scoped_cards if not card.css(PERMALINK_SELECTOR)
        ]
        self.assertEqual(len(comment), 1)
        self.assertFalse(comment[0].css(PERMALINK_SELECTOR))
        self.assertFalse(comment[0].css(POST_TEXT_SELECTOR))


class FacebookProductionRegistrationTests(SimpleTestCase):
    """The facebook-groups registry row comes from import time (no test
    scaffolding; setUp intentionally does not call clear())."""

    def test_facebook_groups_production_registration_resolves(self):
        self.assertIs(get_adapter('facebook-groups'), FacebookGroupsAdapter)


class FacebookFullStackTests(TestCase):
    """Story 1.7 acceptance: registered adapter through collect_source.

    Relies on the import-time registration in collector/__init__.py; the
    REAL adapter fetch runs against the module-level fake playwright (no
    network, no browser, no Playwright API) driven by the fixture cards.
    """

    def test_collect_source_logs_ok_and_stores_listings(self):
        source = Source.objects.create(
            name='facebook-groups',
            adapter_key='facebook-groups',
            config={
                'groups': [GROUP_1],
                'keywords': ['développeur'],
            },
        )
        page = _FakePage(cards=_fixture_fake_cards())
        browser = _FakeBrowser(context=_FakeContext(pages=[page]))
        with patch(
            'collector.adapters.facebook_groups.sync_playwright',
            return_value=_FakePlaywright(browser),
        ):
            created = collect_source(source)

        # only the keyword-matching post lands in the listing store
        self.assertEqual(created, 1)
        self.assertEqual(Listing.objects.count(), 1)
        ok_log = FetchLog.objects.get(source=source, ok=True)
        self.assertEqual(ok_log.stage, 'persist')
        self.assertEqual(ok_log.error, '')
        listing = Listing.objects.get()
        self.assertEqual(
            listing.title,
            'Urgent recrutement développeur web à Alger, CDI temps plein.',
        )
        self.assertEqual(listing.company, 'Karim Benali')
        self.assertEqual(
            listing.url, f'{BASE_URL}/groups/1248610773920835/posts/101/'
        )
        self.assertIsNone(listing.published_at)
        self.assertEqual(listing.keywords, ['développeur'])
        # extract keeps the raw item verbatim: the canonical dict from
        # parse survives nested inside the stored snapshot chain
        self.assertEqual(
            listing.raw_snapshot,
            {
                'title': 'Urgent recrutement développeur web à Alger, CDI temps plein.',
                'company': 'Karim Benali',
                'url': f'{BASE_URL}/groups/1248610773920835/posts/101/',
                'published_at': None,
                'keywords': ['développeur'],
                'raw_snapshot': {
                    'text': 'Urgent recrutement développeur web à Alger, CDI temps plein.',
                    'author': 'Karim Benali',
                    'permalink': f'{BASE_URL}/groups/1248610773920835/posts/101/',
                },
            },
        )
        self.assertEqual(listing.source, source)
        self.assertEqual(listing.seen_sources, ['facebook-groups'])
        self.assertEqual(listing.status, 'new')
        # the real fetch drove the flow end-to-end: browser fully torn down
        self.assertTrue(page.closed)
        self.assertTrue(browser.context.closed)
        self.assertTrue(browser.closed)