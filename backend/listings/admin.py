from django.contrib import admin

from .models import Application, FetchLog, Listing, ListingDeletion, Source

admin.site.register(Source)


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'status', 'published_at')
    # AD-4: dedup_fingerprint is immutable once computed at ingestion.
    readonly_fields = ('dedup_fingerprint',)


@admin.register(FetchLog)
class FetchLogAdmin(admin.ModelAdmin):
    list_display = ('source', 'stage', 'ok', 'created_at')


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('listing', 'created_at', 'outcome')


@admin.register(ListingDeletion)
class ListingDeletionAdmin(admin.ModelAdmin):
    # Append-only audit (Story 3.2): nothing here is editable or deletable.
    readonly_fields = ('fingerprint', 'title', 'company', 'url', 'deleted_at')
    list_display = ('title', 'company', 'deleted_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True