from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    if not value:
        return ''
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    if not value:
        return ''
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return ''


def mask(value: str) -> str:
    if not value:
        return ''
    if len(value) <= 8:
        return '••••'
    return value[:4] + '••••' + value[-4:]


def resolve_carrier_credentials(owner, carrier: str) -> dict | None:
    """Return decrypted BYOK credentials for owner+carrier, or None."""
    if owner is None or not getattr(owner, 'is_authenticated', True):
        return None
    from tracker.models import CarrierCredential

    credential = CarrierCredential.objects.filter(owner=owner, carrier=carrier).first()
    if not credential:
        return None
    return {
        'api_key': decrypt_secret(credential.api_key_enc),
        'secret_key': decrypt_secret(credential.secret_key_enc),
        'base_url': credential.base_url or '',
        'account_number': credential.account_number or '',
    }
