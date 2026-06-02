from __future__ import annotations

from django.conf import settings
from django.http import Http404

from .fedex import first_result
from .models import Package


class InternalAPIAuthError(PermissionError):
    pass



def require_internal_api_key(request):
    configured_key = (getattr(settings, 'INTERNAL_API_KEY', '') or '').strip()
    if not configured_key:
        raise InternalAPIAuthError('Internal API is not configured.')

    auth_header = (request.META.get('HTTP_AUTHORIZATION') or '').strip()
    token = ''
    if auth_header.lower().startswith('bearer '):
        token = auth_header.split(' ', 1)[1].strip()

    if not token:
        token = (request.META.get('HTTP_X_INTERNAL_API_KEY') or '').strip()

    if token != configured_key:
        raise InternalAPIAuthError('Authentication required.')



def serialize_package_summary(package: Package) -> dict:
    return {
        'tracking_number': package.tracking_number,
        'nickname': package.nickname,
        'carrier': package.carrier,
        'status': package.status,
        'status_code': package.status_code,
        'latest_event_at': package.latest_event_at.isoformat() if package.latest_event_at else None,
        'latest_location': package.latest_location,
        'estimated_delivery': package.estimated_delivery,
        'delivered_at': package.delivered_at.isoformat() if package.delivered_at else None,
        'has_exception': package.has_exception,
        'last_checked_at': package.last_checked_at.isoformat() if package.last_checked_at else None,
        'updated_at': package.updated_at.isoformat() if package.updated_at else None,
    }



def serialize_package_detail(package: Package) -> dict:
    payload = package.last_raw_payload or {}
    raw_row = (payload.get('imported_csv_row') or payload.get('row') or {})
    result = first_result(payload) or {}
    package_details = result.get('packageDetails') or {}
    shipment_details = {
        'package_count': result.get('packageCount'),
        'multi_piece_shipment': result.get('multiPieceShipment'),
        'standard_transit_time_window': result.get('standardTransitTimeWindow'),
        'delivery_details': result.get('deliveryDetails') or {},
        'date_and_times': result.get('dateAndTimes') or [],
        'available_images': result.get('availableImages') or [],
        'service_detail': result.get('serviceDetail') or {},
    }
    recipient_address_summary_parts = [
        raw_row.get('Recipient address', ''),
        raw_row.get('Recipient city', ''),
        raw_row.get('Recipient state', ''),
        raw_row.get('Recipient postal', ''),
    ]
    return {
        'package': serialize_package_summary(package),
        'recipient_contact': raw_row.get('Recipient contact name', '') or '',
        'recipient_company': raw_row.get('Recipient company', '') or '',
        'recipient_address_summary': ', '.join(part for part in recipient_address_summary_parts if part),
        'ship_date': raw_row.get('Ship date', '') or '',
        'delivered_date': raw_row.get('Delivered date', '') or '',
        'shipment_details': shipment_details,
        'package_details': package_details,
        'events': [
            {
                'event_time': event.event_time.isoformat() if event.event_time else None,
                'status': event.status,
                'status_code': event.status_code,
                'location': event.location,
                'details': event.details,
            }
            for event in package.events.all()[:5]
        ],
    }



def _flatten_strings(value):
    if value is None:
        return []
    if isinstance(value, dict):
        parts = []
        for key, child in value.items():
            parts.append(str(key))
            parts.extend(_flatten_strings(child))
        return parts
    if isinstance(value, (list, tuple, set)):
        parts = []
        for child in value:
            parts.extend(_flatten_strings(child))
        return parts
    return [str(value)]



def _tokenize(text: str) -> list[str]:
    import re
    return [token for token in re.findall(r"[a-z0-9']+", (text or '').lower()) if token]



def _package_search_blob(package: Package) -> str:
    payload = package.last_raw_payload or {}
    raw_row = (payload.get('imported_csv_row') or payload.get('row') or {})
    parts = [
        package.tracking_number,
        package.nickname,
        package.status,
        package.status_code,
        package.latest_location,
        package.estimated_delivery,
        package.notes,
        raw_row.get('Recipient contact name', ''),
        raw_row.get('Recipient company', ''),
        raw_row.get('Recipient address', ''),
        raw_row.get('Recipient city', ''),
        raw_row.get('Recipient state', ''),
        raw_row.get('Recipient postal', ''),
        raw_row.get('Shipper name', ''),
        raw_row.get('Shipper company', ''),
        raw_row.get('Shipper address', ''),
        raw_row.get('Shipper city', ''),
        raw_row.get('Shipper state', ''),
        raw_row.get('Shipper postal', ''),
        raw_row.get('Delivered To', ''),
        raw_row.get('Received by', ''),
        raw_row.get('Reference', ''),
    ]
    parts.extend(_flatten_strings(package.last_raw_payload or {}))
    for event in package.events.all()[:20]:
        parts.extend([
            event.status,
            event.status_code,
            event.location,
            event.details,
        ])
        parts.extend(_flatten_strings(event.raw_payload or {}))
    return ' '.join(part for part in parts if part).lower()



def search_packages(query: str, limit: int = 10) -> list[dict]:
    query = (query or '').strip().lower()
    if not query:
        return []

    query_tokens = _tokenize(query)
    candidates = list(Package.objects.prefetch_related('events').all()[:500])
    scored = []
    for package in candidates:
        blob = _package_search_blob(package)
        score = 0
        if query == (package.tracking_number or '').lower():
            score += 100
        if query and query in blob:
            score += 40
        nickname = (package.nickname or '').lower()
        if query and query in nickname:
            score += 20
        if query and query in (package.status or '').lower():
            score += 5
        if query_tokens:
            matched_tokens = sum(1 for token in query_tokens if token in blob)
            if matched_tokens:
                score += matched_tokens * 8
                if matched_tokens == len(query_tokens):
                    score += 15
        if score > 0:
            scored.append((score, package.updated_at, package))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [serialize_package_summary(package) for _score, _updated_at, package in scored[:limit]]



def get_package_or_404(tracking_number: str) -> Package:
    try:
        return Package.objects.prefetch_related('events').get(tracking_number=tracking_number)
    except Package.DoesNotExist as exc:
        raise Http404('Package not found.') from exc
