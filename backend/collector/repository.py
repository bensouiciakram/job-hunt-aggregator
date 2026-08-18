"""ListingRepository: the only code that writes Listing rows (AD-4).

The API shape enforces the write-protection: callers pass a canonical
item plus the Source; status/dedup_fingerprint can never be supplied,
only derived (status=NEW on create). Content is written with explicit
update_fields on the update path, so a concurrent status change can
never be clobbered by collection.
"""

from datetime import datetime

from django.db import IntegrityError, transaction

from listings.models import Listing

# AD-1 content contract: every upsert must carry all six keys — no
# silent `.get` defaulting that could wipe existing data.
_CONTENT_KEYS = ('title', 'company', 'url', 'published_at', 'keywords', 'raw_snapshot')


def _missing_content_keys(item):
    return [key for key in _CONTENT_KEYS if key not in item]


def _parse_published_at(value):
    """Canonical ISO-8601 UTC string (or None) -> datetime for the ORM.

    Lenient: naive (tz-less) datetimes and naive ISO strings -> None —
    the timezone is never guessed. Pipeline-normalized values always
    carry +00:00, so this only bites direct repository callers.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value
    if not isinstance(value, str):
        raise ValueError(f'invalid published_at: {value!r}')
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f'invalid published_at: {value!r}') from None
    if dt.tzinfo is None:
        return None
    return dt


class ListingRepository:
    """AD-4-safe write surface over the Listing model."""

    @staticmethod
    def _apply_content(listing, item, published_at):
        """Content fields only; never status/fingerprint/source."""
        if published_at is None and listing.published_at is not None:
            # Lenient parsing must not erase good data already stored.
            published_at = listing.published_at
        listing.title = item['title']
        listing.company = item['company']
        listing.url = item['url']
        listing.published_at = published_at
        listing.keywords = item['keywords']
        listing.raw_snapshot = item['raw_snapshot']

    def _update_existing(self, listing, item, published_at, source):
        """AD-4 update path: content fields only, seen_sources append-only.

        `status`, `dedup_fingerprint`, and `source` are never written —
        a concurrent status change can never be clobbered by collection.
        """
        self._apply_content(listing, item, published_at)
        fields = list(_CONTENT_KEYS)
        if source.adapter_key not in listing.seen_sources:
            listing.seen_sources.append(source.adapter_key)
            fields.append('seen_sources')
        with transaction.atomic():
            listing.save(update_fields=fields)
        return listing

    def upsert(self, item, source):
        """Atomic idempotent upsert by dedup_fingerprint.

        `source` is the Source row (or a duck-typed stand-in exposing
        `.adapter_key`): the FK is populated on CREATE only (first
        source wins; updates never change it), and `source.adapter_key`
        is the seen_sources append key.

        All six content keys are required (title, company, url,
        published_at, keywords, raw_snapshot) — missing keys raise
        ValueError instead of silently defaulting.

        Returns `(listing, created: bool)`.
        """
        fingerprint = item.get('dedup_fingerprint')
        if not fingerprint:
            raise ValueError('item has no dedup_fingerprint')
        missing = _missing_content_keys(item)
        if missing:
            raise ValueError(
                'item missing required content keys: '
                + ', '.join(sorted(missing))
            )
        published_at = _parse_published_at(item.get('published_at'))

        existing = Listing.objects.filter(dedup_fingerprint=fingerprint).first()
        if existing is not None:
            return self._update_existing(existing, item, published_at, source), False

        try:
            with transaction.atomic():
                listing = Listing.objects.create(
                    dedup_fingerprint=fingerprint,
                    status=Listing.Status.NEW,
                    seen_sources=[source.adapter_key],
                    source=source,
                    title=item['title'],
                    company=item['company'],
                    url=item['url'],
                    published_at=published_at,
                    keywords=item['keywords'],
                    raw_snapshot=item['raw_snapshot'],
                )
            return listing, True
        except IntegrityError:
            # Lost a create race: someone else inserted first. Re-get by
            # fingerprint and take the update path; if the row is gone,
            # re-raise the ORIGINAL exception — never mask the cause.
            raced = Listing.objects.filter(dedup_fingerprint=fingerprint).first()
            if raced is None:
                raise
            return self._update_existing(raced, item, published_at, source), False