from __future__ import annotations

from django.utils import timezone

from .fedex import (
    extract_estimated_delivery,
    extract_latest_scan,
    fetch_reference_tracking_results,
    fetch_tracking_result,
    parse_timestamp,
    render_location,
)
from .models import Package, PackageEvent, SavedReference


def build_candidate_from_result(result: dict) -> dict:
    tracking_info = result.get('trackingNumberInfo') or {}
    tracking_number = tracking_info.get('trackingNumber')
    latest = result.get('latestStatusDetail') or {}
    error = result.get('error') or {}
    error_code = error.get('code') or ''
    error_message = error.get('message') or ''
    has_error = bool(error)

    if has_error:
        tracking_number = None
    latest_scan = extract_latest_scan(result)
    delivery_details = result.get('deliveryDetails') or {}
    package_details = result.get('packageDetails') or {}
    service_detail = result.get('serviceDetail') or {}
    shipment_details = {
        'package_count': result.get('packageCount'),
        'multi_piece_shipment': result.get('multiPieceShipment'),
        'standard_transit_time_window': result.get('standardTransitTimeWindow'),
        'delivery_details': delivery_details,
        'date_and_times': result.get('dateAndTimes') or [],
        'available_images': result.get('availableImages') or [],
        'service_detail': service_detail,
    }
    alternate_identifiers = {
        'tracking_info': tracking_info,
        'master_tracking_number': result.get('masterTrackingNumberInfo') or result.get('masterTrackingNumber'),
        'additional_tracking_info': result.get('additionalTrackingInfo') or {},
        'package_identifiers': package_details.get('identifier') if isinstance(package_details, dict) else None,
        'references': result.get('referenceInformation') or result.get('references') or [],
    }
    return {
        'tracking_number': tracking_number,
        'status': (latest.get('statusByLocale') or latest.get('description') or error_message or 'Lookup failed'),
        'status_code': latest.get('code') or error_code,
        'error_message': error_message,
        'has_error': has_error,
        'latest_location': render_location(latest_scan.get('scanLocation')),
        'estimated_delivery': extract_estimated_delivery(result),
        'package_details': package_details,
        'shipment_details': shipment_details,
        'alternate_identifiers': alternate_identifiers,
        'raw_result': result,
        'persisted': False,
        'package': None,
    }


def upsert_package_from_result(result: dict, payload: dict, nickname: str = '') -> Package:
    tracking_number = (result.get('trackingNumberInfo') or {}).get('trackingNumber')
    if not tracking_number:
        raise RuntimeError('FedEx result did not include a tracking number')

    package, _ = Package.objects.get_or_create(
        tracking_number=tracking_number,
        defaults={'nickname': nickname},
    )
    if nickname and not package.nickname:
        package.nickname = nickname

    latest = result.get('latestStatusDetail') or {}
    latest_scan = extract_latest_scan(result)

    package.status = latest.get('statusByLocale') or latest.get('description') or package.status
    package.status_code = latest.get('code') or package.status_code
    package.latest_event_at = parse_timestamp(latest.get('scanDateTime') or latest_scan.get('date'))
    package.latest_location = render_location(latest_scan.get('scanLocation'))
    package.estimated_delivery = extract_estimated_delivery(result)
    package.has_exception = bool((latest.get('code') or '').upper() in {'DE', 'SE', 'EX', 'DY'})
    package.last_checked_at = timezone.now()
    package.last_raw_payload = payload
    if package.status and package.status.lower() == 'delivered' and package.latest_event_at and not package.delivered_at:
        package.delivered_at = package.latest_event_at
    package.save()

    for event in result.get('scanEvents') or []:
        event_time = parse_timestamp(event.get('date'))
        status = event.get('eventDescription') or event.get('derivedStatus') or ''
        status_code = event.get('eventType') or ''
        location = render_location(event.get('scanLocation'))
        details = event.get('exceptionDescription') or event.get('delayDetailStatusDescription') or ''
        obj, created = PackageEvent.objects.get_or_create(
            package=package,
            event_time=event_time,
            status=status,
            status_code=status_code,
            location=location,
            defaults={
                'details': details,
                'raw_payload': event,
            },
        )
        if not created:
            changed = False
            if details and obj.details != details:
                obj.details = details
                changed = True
            if event and obj.raw_payload != event:
                obj.raw_payload = event
                changed = True
            if changed:
                obj.save(update_fields=['details', 'raw_payload'])

    return package


def lookup_and_store_packages(
    search_text: str,
    ship_date_begin: str | None = None,
    ship_date_end: str | None = None,
    destination_country_code: str | None = None,
    destination_postal_code: str | None = None,
    carrier_code: str = 'FDXE',
    account_number: str | None = None,
    reference_type: str = 'CUSTOMER_REFERENCE',
    force_reference_lookup: bool = False,
) -> dict:
    search_text = search_text.strip()
    if not search_text:
        raise RuntimeError('Search text is required')

    if not force_reference_lookup:
        try:
            payload, result = fetch_tracking_result(search_text)
            package = upsert_package_from_result(result, payload)
            candidate = build_candidate_from_result(result)
            candidate['persisted'] = True
            candidate['package'] = package
            return {
                'mode': 'tracking_number',
                'packages': [package],
                'candidates': [candidate],
            }
        except Exception:
            pass

    if not (ship_date_begin and ship_date_end and destination_country_code and account_number):
        raise RuntimeError(
            'Reference lookup requires account number, ship date begin, ship date end, and destination country code.'
        )

    payload, results = fetch_reference_tracking_results(
        reference_value=search_text,
        account_number=account_number,
        ship_date_begin=ship_date_begin,
        ship_date_end=ship_date_end,
        destination_country_code=destination_country_code,
        destination_postal_code=destination_postal_code,
        carrier_code=carrier_code,
        reference_type=reference_type,
    )

    candidates = []
    packages = []
    for result in results:
        candidate = build_candidate_from_result(result)
        tracking_number = candidate['tracking_number']
        if tracking_number and not candidate.get('has_error'):
            package = upsert_package_from_result(result, payload, nickname=search_text)
            candidate['persisted'] = True
            candidate['package'] = package
            packages.append(package)
        candidates.append(candidate)

    return {
        'mode': 'customer_reference',
        'packages': packages,
        'candidates': candidates,
    }
