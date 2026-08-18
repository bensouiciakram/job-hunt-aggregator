"""collector package: SourcePort boundary, code-first adapter registry, test-fetch.

Registers the `google-jobs` placeholder stub so a Source can be registered
and test-fetched through the generic FR-1 path before the real adapter
ships; Story 1.6 overwrites this registration with the same key.
"""

from .registry import register


@register('google-jobs')
class GoogleJobsStub:
    """Placeholder adapter — replaced by the real google-jobs adapter (Story 1.6)."""

    def fetch(self, keywords: list[str]) -> list[dict]:
        raise NotImplementedError('google-jobs adapter lands in Story 1.6')

    def parse(self, raw_items: list[dict]) -> list[dict]:
        raise NotImplementedError('google-jobs adapter lands in Story 1.6')