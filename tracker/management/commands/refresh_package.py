from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from tracker.credentials import resolve_carrier_credentials
from tracker.fedex import fetch_tracking_result as fetch_fedex
from tracker.models import Package
from tracker.services import default_owner, upsert_package_from_result
from tracker.ups import fetch_tracking_result as fetch_ups
from tracker.usps import fetch_tracking_result as fetch_usps


class Command(BaseCommand):
    help = ('Refresh one package from the live carrier API using each owner\'s BYOK keys '
            '(env fallback). Updates every tenant copy.')

    def add_arguments(self, parser):
        parser.add_argument('--tracking-number', required=True)
        parser.add_argument('--nickname', default='')

    def _fetch(self, carrier: str, tracking_number: str, creds: dict):
        if carrier == 'ups':
            return fetch_ups(
                tracking_number,
                client_id=creds.get('api_key'),
                client_secret=creds.get('secret_key'),
                base_url=creds.get('base_url') or None)
        if carrier == 'usps':
            return fetch_usps(
                tracking_number,
                api_key=creds.get('api_key'),
                base_url=creds.get('base_url') or None)
        return fetch_fedex(
            tracking_number,
            api_key=creds.get('api_key'),
            secret_key=creds.get('secret_key'),
            base_url=creds.get('base_url') or None)

    def handle(self, *args, **options):
        tracking_number = options['tracking_number'].strip()
        nickname = options['nickname'].strip()

        if not tracking_number:
            raise CommandError('tracking number is required')

        targets = list(Package.objects.filter(tracking_number=tracking_number))
        created = False
        if not targets:
            seed = Package.objects.create(
                tracking_number=tracking_number,
                nickname=nickname,
                owner=default_owner(),
            )
            targets = [seed]
            created = True

        cache: dict[tuple, tuple | None] = {}
        updated = 0
        for package in targets:
            carrier = (package.carrier or 'fedex').lower()
            key = (package.owner_id, carrier)
            if key not in cache:
                try:
                    creds = resolve_carrier_credentials(package.owner, carrier) or {}
                    cache[key] = self._fetch(carrier, tracking_number, creds)
                except Exception as exc:
                    self.stderr.write(self.style.WARNING(
                        f'skipped owner={package.owner_id} carrier={carrier}: {exc}'))
                    cache[key] = None
            fetched = cache[key]
            if not fetched:
                continue
            payload, result = fetched
            if nickname and not package.nickname:
                package.nickname = nickname
            upsert_package_from_result(result, payload, nickname=package.nickname or nickname, owner=package.owner)
            updated += 1

        action = 'Created' if created else 'Updated'
        status = (targets[0].status or 'unknown') if updated else 'not refreshed'
        self.stdout.write(self.style.SUCCESS(
            f'{action} {updated}/{len(targets)} package row(s) for {tracking_number} | status={status}'
        ))
