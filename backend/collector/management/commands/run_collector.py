"""Management command: run the collector worker as its own process (AD-2).

Start it separately from `runserver` — `uv run python manage.py
run_collector` — so the AD-7 30-minute collection cadence survives the
dev server. Ctrl+C shuts the worker down cleanly.
"""

from django.core.management.base import BaseCommand

from collector.worker import run


class Command(BaseCommand):
    help = (
        'Run the collector worker: startup catch-up pass, then one poll of '
        'every Source every COLLECTOR_INTERVAL_MINUTES.'
    )

    def handle(self, *args, **options):
        run()