from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from tracker.fedex import fetch_tracking_result
from tracker.models import Package
from tracker.services import upsert_package_from_result


class Command(BaseCommand):
    help = 'Refresh one FedEx package from the live API and persist current state/events. Updates every tenant copy.'

    def add_arguments(self, parser):
        parser.add_argument('--tracking-number', required=True)
        parser.add_argument('--nickname', default='')

    def handle(self, *args, **options):
        tracking_number = options['tracking_number'].strip()
        nickname = options['nickname'].strip()

        if not tracking_number:
            raise CommandError('tracking number is required')

        try:
            payload, result = fetch_tracking_result(tracking_number)
        except Exception as exc:  # pragma: no cover - simple command surface
            raise CommandError(str(exc)) from exc

        targets = list(Package.objects.filter(tracking_number=tracking_number))
        created = False
        if not targets:
            from tracker.services import default_owner
            seed = Package.objects.create(
                tracking_number=tracking_number,
                nickname=nickname,
                owner=default_owner(),
            )
            targets = [seed]
            created = True

        for package in targets:
            if nickname and not package.nickname:
                package.nickname = nickname
            upsert_package_from_result(result, payload, nickname=package.nickname or nickname, owner=package.owner)

        action = 'Created' if created else 'Updated'
        self.stdout.write(
            self.style.SUCCESS(
                f'{action} {len(targets)} package row(s) for {tracking_number} | status={targets[0].status or "unknown"}'
            )
        )
