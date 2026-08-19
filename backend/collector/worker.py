"""Story 1.4: collector worker — scheduled collection process (AD-2, AD-7).

`uv run python manage.py run_collector` runs as a separate process from
the Django server (two-process envelope, AD-2). A BlockingScheduler
(APScheduler 3.x, pinned <4) holds one interval job that polls every
registered Source through `collect_source` every
COLLECTOR_INTERVAL_MINUTES (AD-6 per-source isolation; the pipeline
never raises, so the loop never aborts on one bad source).

Backfill semantics (AD-7): re-polling everything on boot IS the
catch-up. `needs_backfill` decides whether the startup pass also logs a
stage='backfill' FetchLog (first-ever pass or gap since the last
successful pass >= 2x the interval) vs only the plain stage='pass' row
that `poll_all` writes every cycle. The freshness marker is DERIVED —
a Listing is stale when `published_at < now - 24h` — and the stale
count is recorded in the backfill row's error field. No schema change.

Importing this module never starts a scheduler; only `run()` does.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .collect import collect_source
from listings.models import FetchLog, Listing, Source

# AD-7 freshness marker: a Listing is fresh while published_at is within
# this window; older rows are "stale" and counted at backfill.
STALE_AFTER_HOURS = 24


def needs_backfill(last_pass_at, now):
    """Pure: True when the worker is overdue or has never completed a pass.

    Overdue = the gap since the last successful pass is >= 2x
    COLLECTOR_INTERVAL_MINUTES (>= 60 min at the default 30); a missing
    last pass (first-ever run) always requires backfill.
    """
    if last_pass_at is None:
        return True
    interval = timedelta(minutes=settings.COLLECTOR_INTERVAL_MINUTES)
    return now - last_pass_at >= 2 * interval


def last_pass_at():
    """Datetime of the latest ok=True FetchLog with stage 'pass'; None if none."""
    row = (
        FetchLog.objects.filter(ok=True, stage='pass')
        .order_by('-created_at')
        .first()
    )
    return row.created_at if row else None


def find_stale_count(cutoff):
    """Count Listings older than the cutoff (published_at < cutoff).

    Listings with published_at=None are NOT stale — they were never
    fresh — and are excluded by the __lt lookup.
    """
    return Listing.objects.filter(published_at__lt=cutoff).count()


def _log_cycle(stage, error=''):
    """Write a cycle-level FetchLog (source=None); must never raise (AD-6)."""
    try:
        FetchLog.objects.create(source=None, stage=stage, ok=True, error=error)
    except Exception:
        pass


def poll_all():
    """Job function: poll every registered Source; never raises (AD-6).

    Each Source goes through `collect_source`, which never raises and
    logs its own per-source FetchLog rows (failures included), so one
    bad Source never aborts the cycle. One stage='pass' FetchLog
    (ok=True, source=None) is written per completed cycle.

    Backfill bookkeeping: at startup, `_startup_pass` additionally
    writes a stage='backfill' FetchLog (ok=True) whose error field
    carries the count of stale Listings (published_at older than 24h)
    found at backfill, e.g. "3 listing(s) older than 24h".
    """
    for source in Source.objects.all():
        collect_source(source)
    _log_cycle('pass')


def _startup_pass():
    """Startup catch-up pass: poll everything once, then record the pass.

    First-ever pass or gap >= 2x the interval (needs_backfill) also
    writes a stage='backfill' FetchLog whose error field carries the
    stale-listing count (published_at older than 24h); a fresh start
    writes only poll_all's plain pass row.
    """
    now = timezone.now()
    backfill = needs_backfill(last_pass_at(), now)
    poll_all()
    if backfill:
        stale = find_stale_count(now - timedelta(hours=STALE_AFTER_HOURS))
        _log_cycle('backfill', f'{stale} listing(s) older than 24h')


def run():
    """Start the collector worker process (AD-2): startup pass, then interval.

    Blocks on a BlockingScheduler with one IntervalTrigger job
    (minutes=COLLECTOR_INTERVAL_MINUTES). Ctrl+C shuts the scheduler
    down (wait=False) and the process exits 0 — no zombie worker.
    """
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = BlockingScheduler()
    scheduler.add_job(
        poll_all,
        IntervalTrigger(minutes=settings.COLLECTOR_INTERVAL_MINUTES),
        id='poll-all',
        max_instances=1,
        coalesce=True,
        misfire_grace_time=settings.COLLECTOR_INTERVAL_MINUTES * 60,
    )
    try:
        _startup_pass()
        scheduler.start()
    except KeyboardInterrupt:
        if scheduler.running:
            scheduler.shutdown(wait=False)