"""Five-stage collection pipeline (Structural Seed).

extract -> clean -> normalize -> dedupe -> validate. All stages are PURE:
no DB access, no I/O; they import only stdlib + each other (AD-1/AD-3).
"""

from .clean import clean, clean_item
from .dedupe import compute_fingerprint, dedupe, dedupe_item
from .extract import extract, extract_item
from .normalize import (
    normalize,
    normalize_item,
    normalize_keywords,
    normalize_published_at,
    url_host,
)
from .validate import validate

__all__ = [
    'clean',
    'clean_item',
    'compute_fingerprint',
    'dedupe',
    'dedupe_item',
    'extract',
    'extract_item',
    'normalize',
    'normalize_item',
    'normalize_keywords',
    'normalize_published_at',
    'url_host',
    'validate',
]