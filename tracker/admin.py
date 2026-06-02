from django.contrib import admin

from .models import Package, PackageEvent, SavedReference


@admin.register(SavedReference)
class SavedReferenceAdmin(admin.ModelAdmin):
    list_display = ('label', 'reference_value', 'reference_type', 'is_active', 'last_used_at', 'updated_at')
    list_filter = ('reference_type', 'is_active')
    search_fields = ('label', 'reference_value', 'notes')
    readonly_fields = ('created_at', 'updated_at', 'last_used_at')


class PackageEventInline(admin.TabularInline):
    model = PackageEvent
    extra = 0
    readonly_fields = ('event_time', 'status', 'status_code', 'location', 'details', 'created_at')
    fields = ('event_time', 'status', 'status_code', 'location', 'details', 'created_at')
    ordering = ('-event_time', '-created_at')
    show_change_link = True


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = (
        'tracking_number',
        'nickname',
        'status',
        'latest_location',
        'estimated_delivery',
        'is_active',
        'has_exception',
        'last_checked_at',
        'updated_at',
    )
    list_filter = ('is_active', 'has_exception', 'carrier')
    search_fields = ('tracking_number', 'nickname', 'status', 'latest_location')
    readonly_fields = ('created_at', 'updated_at', 'last_checked_at', 'last_raw_payload')
    inlines = [PackageEventInline]


@admin.register(PackageEvent)
class PackageEventAdmin(admin.ModelAdmin):
    list_display = ('package', 'event_time', 'status', 'status_code', 'location', 'created_at')
    list_filter = ('status_code',)
    search_fields = ('package__tracking_number', 'package__nickname', 'status', 'location', 'details')
    readonly_fields = ('created_at', 'raw_payload')
