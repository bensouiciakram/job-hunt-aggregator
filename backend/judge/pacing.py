"""Pacing service (Story 3.3, FR-8) — derived from Applications alone (AD-8).

Read-only: per-source response-rate weights (Laplace-smoothed over the last
30 days) reorder collection toward responding sources, and a stop signal
surfaces when >= 10 applications were made in the last 7 days.
"""

from datetime import timedelta

from django.utils import timezone
from django.utils.timezone import now as tz_now

from listings.models import Application

REST_APPLIED_MIN = 10
OUTCOME_WINDOW_DAYS = 30
APPLIED_WINDOW_DAYS = 7

RESPONSE_OUTCOMES = frozenset({Application.Outcome.RESPONSE, Application.Outcome.INTERVIEW})


def source_weights(at=None):
    """{source_id: weight} for sources with outcomes in the last 30 days.

    weight = 0.5 + (responses + 1) / (total + 2), Laplace-smoothed, so a
    single silent outcome lands at ~0.83 and a perfect responder at 1.5.
    Sources with no recent outcomes get no key (neutral 1.0). Applications
    whose listing has no source are skipped.
    """
    at = at or tz_now()
    if timezone.is_naive(at):
        at = timezone.make_aware(at)
    cutoff = at - timedelta(days=OUTCOME_WINDOW_DAYS)
    rows = (
        Application.objects.filter(created_at__gte=cutoff, outcome__isnull=False)
        .select_related('listing__source')
        .values_list('listing__source_id', 'outcome')
    )
    buckets = {}
    for source_id, outcome in rows:
        if source_id is None:
            continue
        responses, total = buckets.get(source_id, (0, 0))
        buckets[source_id] = (responses + (1 if outcome in RESPONSE_OUTCOMES else 0), total + 1)
    return {
        source_id: round(0.5 + (responses + 1) / (total + 2), 2)
        for source_id, (responses, total) in buckets.items()
    }


def compute_pacing(at=None):
    """{applied_7d, rest, source_weights} for the listings payload (FR-8)."""
    at = at or tz_now()
    if timezone.is_naive(at):
        at = timezone.make_aware(at)
    applied_7d = Application.objects.filter(
        created_at__gte=at - timedelta(days=APPLIED_WINDOW_DAYS)
    ).count()
    return {
        'applied_7d': applied_7d,
        'rest': applied_7d >= REST_APPLIED_MIN,
        'source_weights': source_weights(at),
    }