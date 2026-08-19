"""Deletion audit hook (Story 3.2): every Listing deletion records a
ListingDeletion row — append-only engine history the churn signal reads.
"""

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Listing, ListingDeletion

import logging

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Listing)
def record_listing_deletion(sender, instance, **kwargs):
    # An audit failure must never abort the deletion itself (AD-6 spirit).
    try:
        ListingDeletion.objects.create(
            fingerprint=instance.dedup_fingerprint,
            title=instance.title,
            company=instance.company,
            url=instance.url,
        )
    except Exception:
        logger.exception('failed to record deletion audit for listing %s', instance.pk)