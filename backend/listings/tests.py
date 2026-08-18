import os
import tempfile
import unittest
from pathlib import Path

from django.db import IntegrityError, connections
from django.test import TestCase

from .models import FetchLog, Listing, Source


class SqlitePragmaTests(unittest.TestCase):
    """AD-2: WAL mode + busy_timeout on every fresh Django connection.

    Plain unittest.TestCase on purpose: the pragma tests need a
    file-backed Django connection (Django's test database is in-memory,
    where journal_mode=WAL is unsupported), and Django's test isolation
    machinery would otherwise reject the ad-hoc connection alias.
    """

    def _pragma_connection(self):
        handle, path = tempfile.mkstemp(suffix='.sqlite3')
        os.close(handle)
        pragma_settings = dict(connections.databases['default'])
        pragma_settings['NAME'] = path
        connections.databases['pragma_test'] = pragma_settings
        return connections['pragma_test'], Path(path)

    def _close_pragma_connection(self, conn, path):
        if conn is not None:
            conn.close()
        try:
            del connections['pragma_test']
        except AttributeError:
            pass
        connections.databases.pop('pragma_test', None)
        if path is not None:
            for suffix in ('', '-wal', '-shm'):
                try:
                    Path(str(path) + suffix).unlink(missing_ok=True)
                except OSError:
                    pass

    def test_journal_mode_is_wal(self):
        conn = path = None
        try:
            conn, path = self._pragma_connection()
            with conn.cursor() as cursor:
                cursor.execute('PRAGMA journal_mode')
                self.assertEqual(cursor.fetchone(), ('wal',))
        finally:
            self._close_pragma_connection(conn, path)

    def test_busy_timeout_matches_configured_value(self):
        conn = path = None
        try:
            conn, path = self._pragma_connection()
            with conn.cursor() as cursor:
                cursor.execute('PRAGMA busy_timeout')
                (busy_timeout,) = cursor.fetchone()
                self.assertEqual(busy_timeout, 30000)
        finally:
            self._close_pragma_connection(conn, path)


class ListingDedupFingerprintTests(TestCase):
    """AD-4: dedup_fingerprint is DB-unique; a second identical insert is rejected."""

    def test_duplicate_fingerprint_raises_integrity_error(self):
        Listing.objects.create(
            dedup_fingerprint='fp-1',
            title='Senior Backend Engineer',
            company='Acme',
            url='https://example.com/jobs/1',
        )
        with self.assertRaises(IntegrityError):
            Listing.objects.create(
                dedup_fingerprint='fp-1',
                title='Backend Engineer',
                company='Acme Inc',
                url='https://example.com/jobs/2',
            )


class ListingDefaultTests(TestCase):
    """Story 1.1 AC: status "new", empty seen_sources, null published_at."""

    def test_defaults(self):
        listing = Listing.objects.create(
            dedup_fingerprint='fp-2',
            title='Frontend Engineer',
            company='Globex',
            url='https://example.com/jobs/3',
        )
        listing.refresh_from_db()
        self.assertEqual(listing.status, 'new')
        self.assertEqual(listing.seen_sources, [])
        self.assertEqual(listing.keywords, [])
        self.assertEqual(listing.raw_snapshot, {})
        self.assertIsNone(listing.published_at)


class SourceTests(TestCase):
    """AD-1: Source is a registry row; name is unique."""

    def test_name_unique(self):
        Source.objects.create(name='Ouedkniss', adapter_key='ouedkniss-jobs')
        with self.assertRaises(IntegrityError):
            Source.objects.create(name='Ouedkniss', adapter_key='other-source')

    def test_config_default(self):
        source = Source.objects.create(name='Google Jobs', adapter_key='google-jobs')
        source.refresh_from_db()
        self.assertEqual(source.config, {})


class FetchLogTests(TestCase):
    """AD-6: failure-isolated collection event defaults."""

    def test_defaults(self):
        log = FetchLog.objects.create(stage='fetch')
        log.refresh_from_db()
        self.assertFalse(log.ok)
        self.assertEqual(log.error, '')
        self.assertIsNotNone(log.created_at)