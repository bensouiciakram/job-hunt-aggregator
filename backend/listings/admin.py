from django.contrib import admin

from .models import Application, FetchLog, Listing, Source

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