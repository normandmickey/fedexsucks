from __future__ import annotations

import csv
from datetime import datetime, time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker.csv_formats import detect_carrier, map_columns
from tracker.models import Package


DATE_FORMATS = ('%m/%d/%y', '%m/%d/%Y', '%Y-%m-%d', '%m-%d-%Y')


def parse_flexible_date(value: str):
    value = (value or '').strip()
    if not value or value.lower() in {'will be updated soon', 'n/a', 'cancelled', '-'}:
        return None
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
            return timezone.make_aware(datetime.combine(dt.date(), time.min))
        except ValueError:
            continue
    return None


def update_existing_package(package: Package, candidate_latest_event_at, candidate_delivered_at) -> bool:
    """Only clobber stored data when the incoming row is actually newer."""
    if candidate_latest_event_at and (not package.latest_event_at or candidate_latest_event_at > package.latest_event_at):
        return True
    if candidate_delivered_at and (not package.delivered_at or candidate_delivered_at > package.delivered_at):
        return True
    return not package.latest_event_at and not package.delivered_at


class Command(BaseCommand):
    help = 'Import packages from any carrier CSV export (FedEx/UPS/USPS/generic). Columns are sniffed.'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=str)
        parser.add_argument('--user-id', type=int, default=None, help='Owner for imported packages (defaults to oldest superuser)')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        csv_path = Path(options['csv_path']).expanduser()
        if not csv_path.exists():
            raise CommandError(f'CSV not found: {csv_path}')

        from django.contrib.auth import get_user_model

        if options['user_id']:
            owner = get_user_model().objects.filter(id=options['user_id']).first()
            if owner is None:
                raise CommandError(f'User {options["user_id"]} not found')
        else:
            owner = (
                get_user_model().objects.filter(is_superuser=True).order_by('id').first()
                or get_user_model().objects.order_by('id').first()
            )

        created = 0
        updated = 0
        skipped = 0
        updated_same = 0
        carriers_seen = {}

        with csv_path.open(newline='', encoding='utf-8-sig') as handle:
            reader = csv.DictReader(handle)
            mapping = map_columns(reader.fieldnames or [])
            if 'tracking' not in mapping:
                raise CommandError('Could not find a tracking number column. Tried headers like: Tracking Number, Shipment ID, 1Z...')
            for raw_row in reader:
                row = {(k or '').strip(): (v or '').strip() for k, v in raw_row.items() if k}
                tracking_number = row.get(mapping['tracking'], '')
                if not tracking_number:
                    skipped += 1
                    continue

                carrier_hint = row.get(mapping.get('carrier') or mapping.get('service') or '', '')
                carrier = detect_carrier(tracking_number, carrier_hint)
                carriers_seen[carrier] = carriers_seen.get(carrier, 0) + 1

                status = row.get(mapping.get('status') or '', '')
                recipient_name = row.get(mapping.get('recipient_name') or '', '')
                reference = row.get(mapping.get('reference') or '', '')
                city = row.get(mapping.get('recipient_city') or '', '')
                state = row.get(mapping.get('recipient_state') or '', '')
                delivered_at = parse_flexible_date(row.get(mapping.get('delivered_date') or '', ''))
                latest_event_at = delivered_at or parse_flexible_date(row.get(mapping.get('ship_date') or '', ''))
                latest_location = ', '.join(part for part in (city, state) if part)
                nickname = reference or recipient_name or tracking_number
                raw_payload = {'source': 'multi_carrier_csv', 'row': row, 'imported_csv_row': row}

                package, was_created = Package.objects.get_or_create(
                    tracking_number=tracking_number,
                    owner=owner,
                    defaults={
                        'carrier': carrier,
                        'nickname': nickname[:200],
                        'status': status[:200],
                        'latest_event_at': latest_event_at,
                        'latest_location': latest_location[:255],
                        'estimated_delivery': (row.get(mapping.get('estimated_delivery') or mapping.get('service') and '' or '', '') or '')[:255],
                        'delivered_at': delivered_at,
                        'last_checked_at': timezone.now(),
                        'last_raw_payload': raw_payload,
                    },
                )

                if was_created:
                    if options['dry_run']:
                        skipped += 1
                        continue
                    package.save()
                    created += 1
                    continue

                if not update_existing_package(package, latest_event_at, delivered_at):
                    updated_same += 1
                    continue

                package.carrier = carrier
                package.nickname = nickname[:200]
                package.status = status[:200]
                package.latest_event_at = latest_event_at
                package.latest_location = latest_location[:255]
                package.delivered_at = delivered_at or package.delivered_at
                existing_payload = package.last_raw_payload or {}
                package.last_raw_payload = {**existing_payload, **raw_payload}
                package.last_checked_at = timezone.now()
                if not options['dry_run']:
                    package.save()
                updated += 1

        carrier_summary = ', '.join(f'{c}={n}' for c, n in sorted(carriers_seen.items())) or 'none'
        self.stdout.write(self.style.SUCCESS(
            f'Import complete: created={created} updated={updated} unchanged={updated_same} skipped={skipped} carriers[{carrier_summary}] dry_run={options["dry_run"]}'
        ))
