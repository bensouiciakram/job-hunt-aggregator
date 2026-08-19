"""Package: per-site SourcePort adapters (AD-1). Import side effects are
limited to making adapter classes available; nothing is registered here.
"""

from .ouedkniss_jobs import OuedknissJobsAdapter

__all__ = ['OuedknissJobsAdapter']