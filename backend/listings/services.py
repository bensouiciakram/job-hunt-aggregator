"""Explicit listing-services layer (AD-4).

Listing `status` changes ONLY through functions here — collection upserts
must never touch status (enforced by Story 1.3's update_fields patch and its
concurrency test). Epic 3 adds outcome/feedback services beside these.
"""

from django.db import transaction

from .models import Application, Listing

APPLIED = Listing.Status.APPLIED


@transaction.atomic
def apply_to_listing(listing):
    """Record an application; idempotent (AD-5/FR-5).

    Creates the Application (or finds the existing one — the OneToOne
    unique constraint makes the second call a hit) and sets the Listing
    status to 'applied'. Never downgrades status: a re-apply on a listing
    that somehow left 'applied' stays 'applied'.

    Returns (application, created) where created is True only when the
    Application row was actually inserted.
    """
    application, created = Application.objects.get_or_create(listing=listing)
    if created or listing.status != APPLIED:
        # Deliberate force (spec): a re-apply leaves the listing 'applied'
        # whatever its current status is. Today only 'new'/'applied' exist;
        # if Epic 3 adds statuses, revisit this line with the outcome services.
        listing.status = APPLIED
        listing.save(update_fields=['status'])
    return application, created
