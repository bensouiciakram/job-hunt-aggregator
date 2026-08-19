"""Urgency signals (Story 3.2, FR-7) — derived from engine history alone (AD-8).

Batch service: one deletions query (30-day window) + one company-cluster query
(7-day window) serve a whole page. Reads only; never mutates Listings.
"""

import logging
import re
import unicodedata
from datetime import timedelta
from urllib.parse import urlsplit

from django.db.models import Count
from django.utils import timezone
from django.utils.timezone import now as tz_now

from listings.models import Listing, ListingDeletion

logger = logging.getLogger(__name__)

CHURN_WINDOW_DAYS = 30
GROWTH_WINDOW_DAYS = 7
GROWTH_CLUSTER_MIN = 3
CROSS_POSTED_MIN_SOURCES = 2

_WS_RE = re.compile(r'\s+')


def _norm(text):
    """NFKC + casefold + collapsed whitespace: 'Acme ' == 'acme'."""
    return _WS_RE.sub(' ', unicodedata.normalize('NFKC', (text or '')).strip()).casefold()


def _host(url):
    """Hostname of a url: scheme, port, query, and fragment stripped."""
    url = (url or '').strip()
    if url.startswith('//'):
        url = 'http:' + url
    if '://' not in url:
        url = 'http://' + url
    return urlsplit(url).hostname or ''


def compute_signals(listings, at=None):
    """Compute {listing_id: {cross_posted, churn_possible, growth_possible}}.

    `listings` is any iterable of Listing instances (a page). `at` is the
    reference time (default now) — tests pass a fixed time.
    """
    listings = list(listings)
    if not listings:
        return {}

    at = at or tz_now()
    if timezone.is_naive(at):
        at = timezone.make_aware(at)

    churn_cutoff = at - timedelta(days=CHURN_WINDOW_DAYS)
    churn_keys = set()
    for d in ListingDeletion.objects.filter(deleted_at__gte=churn_cutoff):
        key = (_norm(d.title), _norm(d.company), _host(d.url))
        if all(key):
            churn_keys.add(key)

    growth_cutoff = at - timedelta(days=GROWTH_WINDOW_DAYS)
    cluster = {}
    rows = (
        Listing.objects.filter(created_at__gte=growth_cutoff)
        .values('company')
        .annotate(count=Count('id'))
    )
    for row in rows:
        key = _norm(row['company'])
        if key:
            cluster[key] = cluster.get(key, 0) + row['count']

    signals = {}
    for listing in listings:
        sources = listing.seen_sources if isinstance(listing.seen_sources, list) else []
        company = _norm(listing.company)
        signals[listing.id] = {
            'cross_posted': len(set(sources)) >= CROSS_POSTED_MIN_SOURCES,
            'churn_possible': (
                (_norm(listing.title), company, _host(listing.url)) in churn_keys
            ),
            'growth_possible': cluster.get(company, 0) >= GROWTH_CLUSTER_MIN,
        }
    return signals