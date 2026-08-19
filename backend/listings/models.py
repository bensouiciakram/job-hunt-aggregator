from django.db import models


class Source(models.Model):
    """A registered job source (registry row, AD-1)."""

    name = models.CharField(max_length=255, unique=True)
    adapter_key = models.CharField(max_length=255)
    config = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.name


class Listing(models.Model):
    """A canonical job listing (AD-4)."""

    class Status(models.TextChoices):
        NEW = 'new', 'New'
        # Epic 2: `applied` is only ever set by the apply service.
        APPLIED = 'applied', 'Applied'

    # Identity: computed once at ingestion, immutable, DB-unique (AD-4/AD-5 pattern).
    dedup_fingerprint = models.CharField(max_length=64, unique=True)

    title = models.CharField(max_length=500)
    company = models.CharField(max_length=255)
    url = models.CharField(max_length=2048)
    # Indexed for the AD-9 sorted paged queries (published_at DESC, id DESC).
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    keywords = models.JSONField(default=list, blank=True)
    raw_snapshot = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
    )
    # Append-only cross-posting footprint (AD-4/AD-8): the pipeline only ever
    # appends; it never overwrites this field.
    seen_sources = models.JSONField(default=list, blank=True)

    source = models.ForeignKey(
        Source,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='listings',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at', '-id']

    def __str__(self):
        return self.title


class FetchLog(models.Model):
    """Failure-isolated collection event per Source (AD-6)."""

    source = models.ForeignKey(
        Source,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fetch_logs',
    )
    stage = models.CharField(max_length=100)
    ok = models.BooleanField(default=False)
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.source_id} / {self.stage} / ok={self.ok}'


class Application(models.Model):
    """A recorded job application (FR-4/FR-5).

    At most one Application per Listing (AD-5): the OneToOne FK is the
    DB-level unique constraint; the apply service (listings/services.py)
    is the only writer (AD-4).
    """

    listing = models.OneToOneField(
        Listing,
        on_delete=models.CASCADE,
        related_name='application',
        # AD-5: the unique constraint on listing_id is the idempotence backstop.
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Nullable in v1 (FR-8); Epic 3 owns the choices (response/interview/silence).
    outcome = models.CharField(max_length=20, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'application({self.listing_id})'


class ListingDeletion(models.Model):
    """Append-only audit of Listing deletions (Story 3.2, AD-8 engine history).

    Written by the post_delete signal (listings/signals.py) so every deletion
    path — admin, shell, future flows — leaves a trail the churn signal reads.
    Rows are never edited or deleted.
    """

    fingerprint = models.CharField(max_length=64)
    title = models.CharField(max_length=500)
    company = models.CharField(max_length=255)
    url = models.CharField(max_length=2048)
    deleted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-deleted_at']

    def __str__(self):
        return f'deleted({self.fingerprint})'