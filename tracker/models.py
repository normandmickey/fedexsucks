from django.conf import settings
from django.db import models


class SavedReference(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='saved_references',
    )
    label = models.CharField(max_length=200, blank=True)
    reference_value = models.CharField(max_length=255, db_index=True)
    reference_type = models.CharField(max_length=100, default='CUSTOMER_REFERENCE')
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['label', 'reference_value']
        constraints = [
            models.UniqueConstraint(fields=['owner', 'reference_value'], name='uniq_savedreference_owner_value'),
        ]

    def __str__(self) -> str:
        return self.label or self.reference_value


class Package(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='packages',
    )
    tracking_number = models.CharField(max_length=64, db_index=True)
    nickname = models.CharField(max_length=200, blank=True)
    carrier = models.CharField(max_length=50, default='fedex')
    status = models.CharField(max_length=200, blank=True)
    status_code = models.CharField(max_length=100, blank=True)
    latest_event_at = models.DateTimeField(null=True, blank=True)
    latest_location = models.CharField(max_length=255, blank=True)
    estimated_delivery = models.CharField(max_length=255, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    has_exception = models.BooleanField(default=False)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_alert_fingerprint = models.CharField(max_length=255, blank=True)
    last_raw_payload = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(fields=['owner', 'tracking_number'], name='uniq_package_owner_tracking'),
        ]

    def __str__(self) -> str:
        return self.nickname or self.tracking_number


class PackageEvent(models.Model):
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name='events')
    event_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=200, blank=True)
    status_code = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=255, blank=True)
    details = models.TextField(blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-event_time', '-created_at']

    def __str__(self) -> str:
        when = self.event_time.isoformat() if self.event_time else 'unknown-time'
        return f'{self.package} · {self.status or "event"} · {when}'
