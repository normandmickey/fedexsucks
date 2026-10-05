from __future__ import annotations

import re

# Tracking-number shape heuristics. Imperfect by nature (FedEx Ground Economy
# and USPS numbers overlap); an explicit Carrier/Service column always wins.
TRACKING_PATTERNS = [
    ('ups', re.compile(r'^1Z[0-9A-Z]{16}$', re.IGNORECASE)),
    ('usps', re.compile(r'^9[2-5]\d{18,21}$')),
    ('fedex', re.compile(r'^\d{12}$|^\d{15}$|^96\d{18}$')),
]

CARRIER_WORDS = (
    ('fedex', 'fedex'),
    ('ups', 'ups'),
    ('usps', 'usps'),
    ('usps', 'postal'),
    ('usps', 'priority mail'),
)


def _norm(header: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (header or '').lower())


# canonical field -> header aliases (normalized). First hit wins.
FIELD_ALIASES = {
    'tracking': (
        'trackingnumber', 'tracking', 'trackingno', 'trackingid',
        'shipmentidentificationnumber', 'packagestrackingnumber',
    ),
    'carrier': ('carrier', 'carrierservice'),
    'ship_date': (
        'shipdate', 'datetimeshipped', 'shipdatetime', 'dateshipped',
        'shipmentdate', 'pickupdate', 'date',
    ),
    'delivered_date': ('delivereddate', 'deliverydate', 'actualdeliverydate', 'date delivered'),
    'status': ('status', 'statuswithdetails', 'deliverystatus', 'shipmentstatus', 'currentstatus'),
    'recipient_name': ('recipientcontactname', 'recipientname', 'receivername', 'shiptoname', 'to'),
    'recipient_company': ('recipientcompany', 'receivercompany', 'shiptocompany'),
    'recipient_city': ('recipientcity', 'shiptocity', 'tocity'),
    'recipient_state': ('recipientstate', 'shiptostate', 'tostate'),
    'recipient_postal': ('recipientpostal', 'recipientzip', 'shiptopostal', 'shiptozip'),
    'reference': ('reference', 'ref1', 'yourreference', 'shipmentreference', 'trackingreference'),
    'service': ('service', 'servicetype', 'servicedescription', 'shipping service'),
    'estimated_delivery': ('estimateddelivery', 'scheduleddeliverydate', 'estimateddeliverydate'),
}

_SOFT_HINTS = {
    'tracking': ('tracking',),
    'ship_date': ('shipdate',),
    'delivered_date': ('delivereddate', 'deliverydate'),
    'status': ('status',),
    'recipient_name': ('recipient', 'receiver', 'shipto'),
    'recipient_city': ('city',),
    'recipient_state': ('state',),
    'recipient_postal': ('postal', 'zip'),
    'reference': ('reference', 'ref'),
    'service': ('service',),
}


def map_columns(fieldnames) -> dict:
    """Return {canonical_field: original_header} using exact aliases first, soft hints second."""
    normalized = {_norm(f): f for f in fieldnames if f}
    mapping = {}
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in normalized and alias not in mapping.get(field, []):
                mapping[field] = normalized[alias]
                break
    for field, hints in _SOFT_HINTS.items():
        if field in mapping:
            continue
        for norm, original in normalized.items():
            if any(hint in norm for hint in hints) and original not in mapping.values():
                mapping[field] = original
                break
    return mapping


def detect_carrier(tracking_number: str, carrier_hint: str = '') -> str:
    hint = (carrier_hint or '').lower()
    for carrier, word in CARRIER_WORDS:
        if word in hint:
            return carrier
    value = (tracking_number or '').strip()
    for carrier, pattern in TRACKING_PATTERNS:
        if pattern.match(value):
            return carrier
    return 'unknown'


def looks_like_fedex_history(fieldnames) -> bool:
    fields = {_norm(f) for f in fieldnames if f}
    if 'trackingnumber' not in fields:
        return False
    return bool({'statuswithdetails', 'recipientcontactname', 'scheduleddeliverydate'} & fields)
