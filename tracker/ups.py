from __future__ import annotations

from typing import Any

import requests

from .fedex import env, load_local_env, parse_timestamp

DEFAULT_BASE_URL = 'https://onlinetools.ups.com'


def request_token(base_url: str, client_id: str, client_secret: str) -> str:
    response = requests.post(
        f'{base_url.rstrip("/")}/security/v1/oauth/token',
        auth=(client_id, client_secret),
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        data={'grant_type': 'client_id'},
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f'UPS OAuth failed ({response.status_code}): {response.text[:1000]}')
    token = response.json().get('access_token')
    if not token:
        raise RuntimeError(f'UPS OAuth returned no access_token: {response.text[:1000]}')
    return token


def request_tracking(base_url: str, token: str, tracking_number: str) -> dict[str, Any]:
    response = requests.get(
        f'{base_url.rstrip("/")}/api/track/v1/details/{tracking_number}',
        headers={'Authorization': f'Bearer {token}', 'transId': 'trackingsucks-refresh'},
        params={'locale': 'en_US'},
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f'UPS tracking lookup failed ({response.status_code}): {response.text[:1500]}')
    return response.json()


def _combine_datetime(date_value, time_value):
    if not date_value:
        return None
    raw = f'{date_value}T{time_value}' if time_value else str(date_value)
    parsed = parse_timestamp(raw)
    if parsed is not None:
        return parsed.isoformat()
    return str(date_value)


def _first_package(payload: dict[str, Any]) -> dict[str, Any]:
    shipments = ((payload or {}).get('trackResponse') or {}).get('shipments') or []
    if not shipments:
        return {}
    package = shipments[0].get('package') or {}
    if isinstance(package, list):
        package = package[0] if package else {}
    return package


def _activity_list(package: dict[str, Any]) -> list[dict[str, Any]]:
    events = package.get('activityScan') or package.get('activity') or []
    if isinstance(events, dict):
        events = [events]
    return events


def normalize_result(payload: dict[str, Any], tracking_number: str | None = None) -> dict[str, Any]:
    """Normalize a UPS track response into the carrier-neutral result shape
    consumed by services.upsert_package_from_result (FedEx trackResult layout)."""
    package = _first_package(payload)
    tracking = package.get('trackingNumber') or tracking_number

    events = []
    for scan in _activity_list(package):
        status = scan.get('status') or {}
        description = status.get('localizedDescription') or status.get('description') or status.get('code') or ''
        code = status.get('code') or scan.get('activityType') or ''
        address = ((scan.get('location') or {}).get('address')) or {}
        events.append({
            'date': _combine_datetime(scan.get('date'), scan.get('time')),
            'eventDescription': description,
            'derivedStatus': description,
            'eventType': str(code).upper(),
            'scanLocation': {
                'city': address.get('city') or '',
                'stateOrProvinceCode': address.get('stateCode') or address.get('state') or '',
                'countryCode': address.get('countryCode') or '',
            },
        })
    events.sort(key=lambda item: item.get('date') or '', reverse=True)

    current = package.get('currentStatus') or {}
    latest = events[0] if events else {}
    status_description = current.get('localizedDescription') or current.get('description') or latest.get('eventDescription') or ''
    delivery = package.get('deliveryInformation') or {}
    estimated = delivery.get('estimatedDeliveryDate') or delivery.get('expectedDelivery') or ''
    date_and_times = [{'type': 'Estimated Delivery', 'dateTime': str(estimated)}] if estimated else []

    return {
        'trackingNumberInfo': {'trackingNumber': tracking},
        'latestStatusDetail': {
            'statusByLocale': status_description,
            'code': str(current.get('code') or '').upper(),
            'scanDateTime': latest.get('date'),
        },
        'dateAndTimes': date_and_times,
        'scanEvents': events,
    }


def fetch_tracking_result(
    tracking_number: str,
    client_id: str | None = None,
    client_secret: str | None = None,
    base_url: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    load_local_env()
    base_url = base_url or env('UPS_BASE_URL', required=False, default=DEFAULT_BASE_URL)
    client_id = client_id or env('UPS_CLIENT_ID', required=False)
    client_secret = client_secret or env('UPS_CLIENT_SECRET', required=False)
    if not client_id or not client_secret:
        raise RuntimeError('No UPS credentials configured — add your Client ID + secret under API keys.')
    token = request_token(base_url, client_id, client_secret)
    payload = request_tracking(base_url, token, tracking_number)
    return payload, normalize_result(payload, tracking_number)
