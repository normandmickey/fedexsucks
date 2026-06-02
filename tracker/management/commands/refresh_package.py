from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker.fedex import (
    extract_estimated_delivery,
    extract_latest_scan,
    fetch_tracking_result,
    parse_timestamp,
    render_location,
)
from tracker.models import Package, PackageEvent


class Command(BaseCommand):
    help = 'Refresh one FedEx package from the live API and persist current state/events.'

    def add_arguments(self, parser):
        parser.add_argument('--tracking-number', required=True)
        parser.add_argument('--nickname', default='')

    def handle(self, *args, **options):
        tracking_number = options['tracking_number'].strip()
        nickname = options['nickname'].strip()

        if not tracking_number:
            raise CommandError('tracking number is required')

        package, created = Package.objects.get_or_create(
            tracking_number=tracking_number,
            defaults={'nickname': nickname},
        )
        if nickname and not package.nickname:
            package.nickname = nickname

        try:
            payload, result = fetch_tracking_result(tracking_number)
        except Exception as exc:  # pragma: no cover - simple command surface
            raise CommandError(str(exc)) from exc

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

        created_events = 0
        for event in result.get('scanEvents') or []:
            event_time = parse_timestamp(event.get('date'))
            status = event.get('eventDescription') or event.get('derivedStatus') or ''
            status_code = event.get('eventType') or ''
            location = render_location(event.get('scanLocation'))
            details = event.get('exceptionDescription') or event.get('delayDetailStatusDescription') or ''
            obj, was_created = PackageEvent.objects.get_or_create(
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
            if was_created:
                created_events += 1
            else:
                changed = False
                if details and obj.details != details:
                    obj.details = details
                    changed = True
                if event and obj.raw_payload != event:
                    obj.raw_payload = event
                    changed = True
                if changed:
                    obj.save(update_fields=['details', 'raw_payload'])

        action = 'Created' if created else 'Updated'
        self.stdout.write(
            self.style.SUCCESS(
                f'{action} package {package.tracking_number} | status={package.status or "unknown"} | new_events={created_events}'
            )
        )
