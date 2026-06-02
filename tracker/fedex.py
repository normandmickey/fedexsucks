from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / '.env'


def load_local_env(env_path: Path = ENV_PATH) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env(name: str, required: bool = True, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f'Missing required environment variable: {name}')
    return value


def request_access_token(base_url: str, api_key: str, secret_key: str) -> str:
    response = requests.post(
        f'{base_url.rstrip("/")}/oauth/token',
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        data={
            'grant_type': 'client_credentials',
            'client_id': api_key,
            'client_secret': secret_key,
        },
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f'FedEx OAuth failed ({response.status_code}): {response.text[:1000]}')
    payload = response.json()
    token = payload.get('access_token')
    if not token:
        raise RuntimeError(f'FedEx OAuth returned no access_token: {json.dumps(payload)[:1000]}')
    return token


def request_tracking(base_url: str, token: str, tracking_number: str) -> dict[str, Any]:
    response = requests.post(
        f'{base_url.rstrip("/")}/track/v1/trackingnumbers',
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'X-locale': 'en_US',
        },
        json={
            'includeDetailedScans': True,
            'trackingInfo': [
                {
                    'trackingNumberInfo': {
                        'trackingNumber': tracking_number,
                    }
                }
            ],
        },
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f'FedEx tracking lookup failed ({response.status_code}): {response.text[:1500]}')
    return response.json()


def request_tracking_by_reference(
    base_url: str,
    token: str,
    reference_type: str,
    reference_value: str,
    account_number: str,
    ship_date_begin: str,
    ship_date_end: str,
    destination_country_code: str,
    destination_postal_code: str | None = None,
    carrier_code: str = 'FDXE',
) -> dict[str, Any]:
    references_information = {
        'type': reference_type,
        'value': reference_value,
        'accountNumber': account_number,
        'carrierCode': carrier_code,
        'shipDateBegin': ship_date_begin,
        'shipDateEnd': ship_date_end,
        'destinationCountryCode': destination_country_code,
    }
    if destination_postal_code:
        references_information['destinationPostalCode'] = destination_postal_code

    response = requests.post(
        f'{base_url.rstrip("/")}/track/v1/referencenumbers',
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'X-locale': 'en_US',
        },
        json={
            'referencesInformation': references_information,
            'includeDetailedScans': True,
        },
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(
            f'FedEx reference tracking lookup failed ({response.status_code}): {response.text[:1500]}'
        )
    return response.json()


def first_result(payload: dict[str, Any]) -> dict[str, Any] | None:
    output = payload.get('output') or {}
    complete = output.get('completeTrackResults') or []
    if not complete:
        return None
    track_results = complete[0].get('trackResults') or []
    if not track_results:
        return None
    return track_results[0]


def fetch_tracking_result(tracking_number: str) -> tuple[dict[str, Any], dict[str, Any]]:
    load_local_env()
    base_url = env('FEDEX_BASE_URL', required=False, default='https://apis.fedex.com')
    api_key = env('FEDEX_API_KEY')
    secret_key = env('FEDEX_SECRET_KEY')
    token = request_access_token(base_url, api_key, secret_key)
    payload = request_tracking(base_url, token, tracking_number)
    result = first_result(payload)
    if not result:
        raise RuntimeError(f'FedEx response had no track result: {json.dumps(payload)[:1500]}')
    return payload, result


def fetch_reference_tracking_results(
    reference_value: str,
    account_number: str,
    ship_date_begin: str,
    ship_date_end: str,
    destination_country_code: str,
    destination_postal_code: str | None = None,
    carrier_code: str = 'FDXE',
    reference_type: str = 'CUSTOMER_REFERENCE',
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    load_local_env()
    base_url = env('FEDEX_BASE_URL', required=False, default='https://apis.fedex.com')
    api_key = env('FEDEX_API_KEY')
    secret_key = env('FEDEX_SECRET_KEY')
    token = request_access_token(base_url, api_key, secret_key)
    payload = request_tracking_by_reference(
        base_url,
        token,
        reference_type,
        reference_value,
        account_number,
        ship_date_begin,
        ship_date_end,
        destination_country_code,
        destination_postal_code,
        carrier_code,
    )
    output = payload.get('output') or {}
    complete = output.get('completeTrackResults') or []
    results = complete[0].get('trackResults') if complete else []
    if not results:
        raise RuntimeError(f'FedEx reference response had no track results: {json.dumps(payload)[:1500]}')
    return payload, results


def parse_timestamp(value: str | None):
    if not value:
        return None
    from django.utils.dateparse import parse_datetime

    dt = parse_datetime(value)
    if dt is not None:
        return dt
    cleaned = value.replace('Z', '+00:00')
    return parse_datetime(cleaned)


def render_location(scan_location: dict[str, Any] | None) -> str:
    if not scan_location:
        return ''
    parts = [
        scan_location.get('city'),
        scan_location.get('stateOrProvinceCode'),
        scan_location.get('countryCode'),
    ]
    return ', '.join(part for part in parts if part)


def extract_latest_scan(result: dict[str, Any]) -> dict[str, Any]:
    scan_events = result.get('scanEvents') or []
    return scan_events[0] if scan_events else {}


def extract_estimated_delivery(result: dict[str, Any]) -> str:
    date_and_times = result.get('dateAndTimes') or []
    if not date_and_times:
        return ''
    for item in date_and_times:
        label = item.get('type') or item.get('dateTimeType') or 'date'
        value = item.get('dateTime') or item.get('date') or ''
        if value:
            return f'{label}: {value}'
    return ''


def summarize_track_result(result: dict[str, Any]) -> dict[str, Any]:
    latest = result.get('latestStatusDetail') or {}
    latest_scan = extract_latest_scan(result)
    delivery_details = result.get('deliveryDetails') or {}
    package_details = result.get('packageDetails') or {}
    service_detail = result.get('serviceDetail') or {}

    return {
        'tracking_number': result.get('trackingNumberInfo', {}).get('trackingNumber'),
        'status': latest.get('statusByLocale') or latest.get('description'),
        'status_code': latest.get('code'),
        'latest_status_scan_time': latest.get('scanDateTime') or latest_scan.get('date'),
        'estimated_delivery': extract_estimated_delivery(result),
        'service': service_detail,
        'latest_location': render_location(latest_scan.get('scanLocation')),
        'latest_event': {
            'date': latest_scan.get('date'),
            'event_type': latest_scan.get('eventType'),
            'description': latest_scan.get('eventDescription'),
            'location': render_location(latest_scan.get('scanLocation')),
        },
        'package_details': package_details,
        'shipment_details': {
            'package_count': result.get('packageCount'),
            'multi_piece_shipment': result.get('multiPieceShipment'),
            'standard_transit_time_window': result.get('standardTransitTimeWindow'),
            'delivery_details': delivery_details,
            'date_and_times': result.get('dateAndTimes'),
            'available_images': result.get('availableImages'),
        },
    }
