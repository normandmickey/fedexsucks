from django.conf import settings
from django.db import models

from .credentials import decrypt_secret, encrypt_secret, mask


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


class CarrierCredential(models.Model):
    """Per-tenant carrier API credentials (BYOK). Secrets encrypted at rest.

    Field shapes by carrier:
      fedex: api_key + secret_key (+ account_number for reference lookups)
      ups:   api_key = client id, secret_key = client secret
      usps:  api_key only
    """

    CARRIERS = [('fedex', 'FedEx'), ('ups', 'UPS'), ('usps', 'USPS')]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='carrier_credentials',
    )
    carrier = models.CharField(max_length=20, choices=CARRIERS, db_index=True)
    api_key_enc = models.TextField(blank=True)
    secret_key_enc = models.TextField(blank=True)
    account_number = models.CharField(max_length=100, blank=True)
    base_url = models.CharField(max_length=255, blank=True,
                                help_text='Optional API base URL override')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['carrier']
        constraints = [
            models.UniqueConstraint(fields=['owner', 'carrier'], name='uniq_credential_owner_carrier'),
        ]

    def set_secrets(self, api_key: str = '', secret_key: str = '') -> None:
        if api_key:
            self.api_key_enc = encrypt_secret(api_key)
        if secret_key:
            self.secret_key_enc = encrypt_secret(secret_key)

    @property
    def api_key(self) -> str:
        return decrypt_secret(self.api_key_enc)

    @property
    def secret_key(self) -> str:
        return decrypt_secret(self.secret_key_enc)

    @property
    def masked_api_key(self) -> str:
        return mask(self.api_key)

    @property
    def masked_secret_key(self) -> str:
        return mask(self.secret_key)

    def __str__(self) -> str:
        return f'{self.carrier} credentials ({self.owner})'


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
