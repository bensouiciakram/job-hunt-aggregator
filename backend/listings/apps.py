from django.apps import AppConfig
from django.db.backends.signals import connection_created


def set_sqlite_pragmas(sender, connection, **kwargs):
    """AD-2: WAL mode + busy_timeout on every SQLite connection.

    journal_mode=WAL is persistent in the DB file, but busy_timeout is
    per-connection, so both are applied here via the connection_created
    signal (Django removed init_command in 4.2).
    """
    if connection.vendor != 'sqlite':
        return
    with connection.cursor() as cursor:
        cursor.execute('PRAGMA journal_mode=WAL;')
        cursor.execute('PRAGMA busy_timeout=30000;')


class ListingsConfig(AppConfig):
    name = 'listings'

    def ready(self):
        connection_created.connect(
            set_sqlite_pragmas,
            dispatch_uid='listings_set_sqlite_pragmas',
        )