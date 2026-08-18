"""AD-1: the SourcePort boundary between per-site adapters and the core.

Adapters implement SourcePort and never touch the database; value
harmonization lives in the pipeline's normalize stage, not here.
"""

from typing import Protocol, runtime_checkable

# Raw items as produced by a site fetch: JSON-serializable dicts.
RawItems = list[dict]

# Canonical field set produced by parse(): title, company, url,
# published_at (ISO-8601 UTC), keywords, raw_snapshot.
CanonicalFields = list[dict]


class AdapterNotFound(Exception):
    """Raised by the registry when an adapter_key has no registered class."""


@runtime_checkable
class SourcePort(Protocol):
    """Contract every adapter implements (fetch → raw, parse → canonical)."""

    def fetch(self, keywords: list[str]) -> RawItems:
        """Fetch raw items for the given keywords. Never touches the DB."""

    def parse(self, raw_items: RawItems) -> CanonicalFields:
        """Transform raw items into the canonical field set (pure)."""