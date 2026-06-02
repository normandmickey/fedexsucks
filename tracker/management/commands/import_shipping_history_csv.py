import csv
from datetime import datetime, time
from pathlib import Path

from io import StringIO

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker.models import Package


STATUS_CODE_MAP = {
    'Label created': 'LABEL_CREATED',
    'Delivered': 'DELIVERED',
    'Delivery updated': 'DELIVERY_UPDATED',
    'On the way': 'ON_THE_WAY',
    'Out for delivery': 'OUT_FOR_DELIVERY',
    'We have your package': 'WE_HAVE_YOUR_PACKAGE',
    'Cancelled': 'CANCELLED',
}


def clean_row(row: dict) -> dict:
    cleaned = {}
    for key, value in row.items():
        normalized_key = (key or '').strip()
        cleaned[normalized_key] = (value or '').strip()
    return cleaned


def parse_short_date(value: str):
    if not value or value.lower() == 'will be updated soon' or value.lower() == 'cancelled':
        return None
    for fmt in ('%m/%d/%y', '%m/%d/%Y'):
        try:
            dt = datetime.strptime(value, fmt)
            return timezone.make_aware(datetime.combine(dt.date(), time.min))
        except ValueError:
            continue
    return None


def should_update_existing_package(package: Package, candidate_latest_event_at, candidate_delivered_at) -> bool:
    current_latest = package.latest_event_at
    candidate_latest = candidate_delivered_at or candidate_latest_event_at
    if candidate_latest is None:
        return False
    if current_latest is None:
        return True
    return candidate_latest > current_latest


class Command(BaseCommand):
    help = 'Import FedEx shipping history CSV export into local Package rows.'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=str)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        csv_path = Path(options['csv_path']).expanduser()
        if not csv_path.exists():
            raise CommandError(f'CSV not found: {csv_path}')

        created = 0
        updated = 0
        skipped = 0
        duplicates = 0

        with csv_path.open(newline='', encoding='utf-8-sig') as handle:
            reader = csv.DictReader(handle)
            for raw_row in reader:
                row = clean_row(raw_row)
                tracking_number = row.get('Tracking Number', '')
                if not tracking_number:
                    skipped += 1
                    continue

                status = row.get('Status', '') or row.get('Status ', '')
                reference = row.get('Reference', '') or row.get('Reference ', '')
                recipient_company = row.get('Recipient company', '') or row.get('Recipient company ', '')
                recipient_contact = row.get('Recipient contact name', '') or row.get('Recipient contact name ', '')
                delivered_date = row.get('Delivered date', '')
                ship_date = row.get('Ship date', '') or row.get('Ship date ', '')
                latest_location_parts = [
                    row.get('Recipient city', '') or row.get('Recipient city ', ''),
                    row.get('Recipient state', '') or row.get('Recipient state ', ''),
                ]
                latest_location = ', '.join(part for part in latest_location_parts if part)
                nickname = reference or recipient_company or recipient_contact or tracking_number
                status_details = row.get('Status with details', '') or row.get('Status with details ', '')
                estimated_date = row.get('Scheduled delivery date', '') or row.get('Scheduled delivery date ', '')
                estimated_time = row.get('Scheduled Delivery Time Before', '')
                estimated_delivery = ' · '.join(part for part in [estimated_date, estimated_time] if part and part.lower() != 'will be updated soon')
                delivered_at = parse_short_date(delivered_date)
                latest_event_at = delivered_at or parse_short_date(ship_date)
                raw_payload = {
                    'source': 'shipping_history_csv',
                    'row': row,
                    'imported_csv_row': row,
                }

                package, was_created = Package.objects.get_or_create(
                    tracking_number=tracking_number,
                    defaults={
                        'nickname': nickname[:200],
                        'carrier': 'fedex',
                        'status': status[:200],
                        'status_code': STATUS_CODE_MAP.get(status, status.upper().replace(' ', '_')[:100]),
                        'latest_event_at': latest_event_at,
                        'latest_location': latest_location[:255],
                        'estimated_delivery': estimated_delivery[:255],
                        'delivered_at': delivered_at,
                        'has_exception': status.lower() in {'delivery exception', 'exception'},
                        'last_checked_at': timezone.now(),
                        'last_raw_payload': raw_payload,
                        'notes': status_details,
                    },
                )

                if not was_created:
                    duplicates += 1
                    if not should_update_existing_package(package, latest_event_at, delivered_at):
                        continue

                    package.nickname = nickname[:200]
                    package.status = status[:200]
                    package.status_code = STATUS_CODE_MAP.get(status, status.upper().replace(' ', '_')[:100])
                    package.latest_event_at = latest_event_at
                    package.latest_location = latest_location[:255]
                    package.estimated_delivery = estimated_delivery[:255]
                    package.delivered_at = delivered_at
                    package.has_exception = status.lower() in {'delivery exception', 'exception'}
                    package.last_checked_at = timezone.now()
                    existing_payload = package.last_raw_payload or {}
                    imported_csv_row = existing_payload.get('imported_csv_row') or row
                    package.last_raw_payload = {
                        **existing_payload,
                        'imported_csv_row': imported_csv_row,
                        'row': row,
                        'source': 'shipping_history_csv',
                    }
                    package.notes = status_details

                    if options['dry_run']:
                        updated += 1
                        continue

                    package.save()
                    updated += 1
                    continue

                if options['dry_run']:
                    created += 1
                    continue

                package.save()
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Import complete: created={created} updated={updated} duplicates={duplicates} skipped={skipped} dry_run={options["dry_run"]}'
        ))
