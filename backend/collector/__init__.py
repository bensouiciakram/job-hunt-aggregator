"""collector package: SourcePort boundary, code-first adapter registry, test-fetch.

Each adapter lives in `collector/adapters/` and is registered here by
kebab-case adapter_key (FR-1): `google-jobs` (JobSpy) and
`ouedkniss-jobs` (ouedkniss GraphQL).
"""

from .adapters.google_jobs import GoogleJobsAdapter
from .adapters.ouedkniss_jobs import OuedknissJobsAdapter
from .registry import register

register('google-jobs')(GoogleJobsAdapter)
register('ouedkniss-jobs')(OuedknissJobsAdapter)
