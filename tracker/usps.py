from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from .fedex import env, load_local_env, parse_timestamp

DEFAULT_BASE_URL = 'https://apis.usps.com'

_DATE_FORMATS = ['%Y-%m-%d', '%Y%m%d', '%m/%d/%Y', '%B %d, %Y', '%b %d, %Y']
_TIME_FORMATS = ['%H:%M:%S', '%H%M%S', '%I:%M %p', '%I:%M:%S %p', '%H:%M']

_STATUS_CODE_MAP = {'DELIVERED': 'DL', 'ALERT': 'EX', 'EXCEPTION': 'EX', 'AVAILABLE_FOR_PICKUP': 'AP'}


def _parse_date(value):
    if not value:
        return None
    parsed = parse_timestamp(str(value))
    if parsed is not None:
        return parsed.date()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(value):
    if not value:
        return None
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(str(value).strip(), fmt).time()
        except ValueError:
            continue
    return None


def _event_datetime(date_value, time_value):
    day = _parse_date(date_value)
    if not day:
        return None
    clock = _parse_time(time_value)
    moment = datetime.combine(day, clock) if clock else datetime.combine(day, datetime.min.time())
    return moment.isoformat()


def _info(payload: dict[str, Any]) -> dict[str, Any]:
    info_list = (payload or {}).get('trackingInfo')
    if isinstance(info_list, list) and info_list:
        return info_list[0] or {}
    return payload or {}


def normalize_result(payload: dict[str, Any], tracking_number: str | None = None) -> dict[str, Any]:
    """Normalize a USPS v3 tracking response into the carrier-neutral result shape
    consumed by services.upsert_package_from_result (FedEx trackResult layout)."""
    info = _info(payload)
    tracking = info.get('trackingNumber') or tracking_number
    status = (info.get('status') or '').strip()
    summary = info.get('statusSummary') or ''
    status_upper = status.upper().replace(' ', '_')
    code = _STATUS_CODE_MAP.get(status_upper, 'IT' if status else '')

    scans = ((info.get('scanHistory') or {}).get('scan')) or info.get('scanList') or []
    if isinstance(scans, dict):
        scans = [scans]
    events = []
    for scan in scans:
        description = scan.get('event') or scan.get('eventStatus') or ''
        location = scan.get('scanLocation') or ''
        events.append({
            'date': _event_datetime(scan.get('date'), scan.get('time')),
            'eventDescription': description,
            'derivedStatus': description,
            'eventType': _STATUS_CODE_MAP.get((description or '').upper().replace(' ', '_'), 'SC'),
            'scanLocation': {'city': location, 'stateOrProvinceCode': '', 'countryCode': ''},
        })
    events.sort(key=lambda item: item.get('date') or '', reverse=True)

    latest = events[0] if events else {}
    delivery_day = _parse_date(info.get('deliveryDate') or info.get('estimatedDeliveryDate'))
    date_and_times = []
    if delivery_day:
        label = 'Delivered' if status_upper == 'DELIVERED' else 'Estimated Delivery'
        date_and_times = [{'type': label, 'dateTime': delivery_day.isoformat()}]

    return {
        'trackingNumberInfo': {'trackingNumber': tracking},
        'latestStatusDetail': {
            'statusByLocale': status or summary or latest.get('eventDescription'),
            'code': code,
            'scanDateTime': latest.get('date'),
        },
        'dateAndTimes': date_and_times,
        'scanEvents': events,
    }


def fetch_tracking_result(
    tracking_number: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    load_local_env()
    base_url = base_url or env('USPS_BASE_URL', required=False, default=DEFAULT_BASE_URL)
    api_key = api_key or env('USPS_API_KEY', required=False)
    if not api_key:
        raise RuntimeError('No USPS credentials configured — add your X-API-Key under API keys.')
    response = requests.get(
        f'{base_url.rstrip("/")}/shipping/v3/tracking',
        params={'trackingNumber': tracking_number},
        headers={'X-API-Key': api_key, 'Accept': 'application/json'},
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f'USPS tracking lookup failed ({response.status_code}): {response.text[:1500]}')
    payload = response.json()
    return payload, normalize_result(payload, tracking_number)
