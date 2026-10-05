from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from .models import Package, SavedReference


def make_users():
    return (
        User.objects.create_user('alice', password='alice-pass-123'),
        User.objects.create_user('bob', password='bob-pass-12345'),
    )


class PackageScopingTests(TestCase):
    def setUp(self):
        self.alice, self.bob = make_users()

    def test_home_requires_login(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])

    def test_home_scopes_packages_to_owner(self):
        Package.objects.create(tracking_number='123456789012', owner=self.alice, status='On the way')
        self.client.force_login(self.bob)
        response = self.client.get('/')
        self.assertNotContains(response, '123456789012')
        self.client.force_login(self.alice)
        response = self.client.get('/')
        self.assertContains(response, '123456789012')

    def test_package_detail_hidden_from_other_users(self):
        Package.objects.create(tracking_number='123456789012', owner=self.alice)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get('/packages/123456789012/').status_code, 404)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get('/packages/123456789012/').status_code, 200)

    def test_same_tracking_number_allowed_for_two_owners(self):
        Package.objects.create(tracking_number='999999999999', owner=self.alice)
        Package.objects.create(tracking_number='999999999999', owner=self.bob)
        self.assertEqual(Package.objects.filter(tracking_number='999999999999').count(), 2)

    def test_duplicate_tracking_number_rejected_for_same_owner(self):
        Package.objects.create(tracking_number='888888888888', owner=self.alice)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Package.objects.create(tracking_number='888888888888', owner=self.alice)

    def test_legacy_rows_visible_to_original_superuser(self):
        # simulates the 0004 backfill: unowned row adopted by oldest superuser
        norm = User.objects.create_user('norman', password='norman-pass-123', is_superuser=True)
        Package.objects.create(tracking_number='777777777777', owner=norm)
        self.client.force_login(norm)
        self.assertContains(self.client.get('/'), '777777777777')


class SavedReferenceScopingTests(TestCase):
    def setUp(self):
        self.alice, self.bob = make_users()

    def test_same_reference_value_allowed_for_two_owners(self):
        SavedReference.objects.create(reference_value='PO-1001', owner=self.alice)
        SavedReference.objects.create(reference_value='PO-1001', owner=self.bob)
        self.assertEqual(SavedReference.objects.filter(reference_value='PO-1001').count(), 2)

    def test_home_lists_only_own_references(self):
        # home.html doesn't render the reference list itself — assert on the view context
        SavedReference.objects.create(reference_value='PO-ALICE', owner=self.alice, label='Alice ref')
        SavedReference.objects.create(reference_value='PO-BOB', owner=self.bob, label='Bob ref')
        self.client.force_login(self.bob)
        response = self.client.get('/')
        refs = list(response.context['saved_references'])
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].reference_value, 'PO-BOB')

    def test_save_reference_post_assigns_owner(self):
        self.client.force_login(self.alice)
        self.client.post('/', {
            'action': 'save_reference',
            'reference_label': 'Warranty order',
            'reference_value': 'PO-2026-777',
        })
        saved = SavedReference.objects.get(reference_value='PO-2026-777')
        self.assertEqual(saved.owner, self.alice)


class RegistrationTests(TestCase):
    def test_registration_closed_by_default(self):
        response = self.client.get('/register/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])

    @override_settings(REGISTER_INVITE_CODE='north-pole')
    def test_registration_with_valid_invite(self):
        response = self.client.post('/register/', {
            'username': 'newtenant',
            'password1': 'correct-horse-battery-9',
            'password2': 'correct-horse-battery-9',
            'invite_code': 'north-pole',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username='newtenant').exists())

    @override_settings(REGISTER_INVITE_CODE='north-pole')
    def test_registration_rejects_bad_invite(self):
        self.client.post('/register/', {
            'username': 'intruder',
            'password1': 'correct-horse-battery-9',
            'password2': 'correct-horse-battery-9',
            'invite_code': 'wrong',
        })
        self.assertFalse(User.objects.filter(username='intruder').exists())

    @override_settings(REGISTER_INVITE_CODE='north-pole')
    def test_registered_user_gets_empty_workspace(self):
        self.alice, _ = make_users()
        Package.objects.create(tracking_number='111111111111', owner=self.alice)
        self.client.post('/register/', {
            'username': 'newtenant',
            'password1': 'correct-horse-battery-9',
            'password2': 'correct-horse-battery-9',
            'invite_code': 'north-pole',
        })
        newtenant = User.objects.get(username='newtenant')
        self.client.force_login(newtenant)
        self.assertNotContains(self.client.get('/'), '111111111111')


class ImportOwnerTests(TestCase):
    def test_import_assigns_owner(self):
        import json
        import tempfile
        from pathlib import Path

        alice, _ = make_users()
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as handle:
            handle.write('Tracking Number,Status,Reference\n')
            handle.write('555555555555,Delivered,Warranty order\n')
            path = handle.name
        try:
            call_command('import_shipping_history_csv', path, user_id=alice.id)
        finally:
            Path(path).unlink(missing_ok=True)

        package = Package.objects.get(tracking_number='555555555555')
        self.assertEqual(package.owner, alice)

    def test_import_defaults_to_oldest_superuser(self):
        import tempfile
        from pathlib import Path

        norm = User.objects.create_user('norman', password='norman-pass-123', is_superuser=True)
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as handle:
            handle.write('Tracking Number,Status\n666666666666,Delivered\n')
            path = handle.name
        try:
            call_command('import_shipping_history_csv', path)
        finally:
            Path(path).unlink(missing_ok=True)

        package = Package.objects.get(tracking_number='666666666666')
        self.assertEqual(package.owner, norm)

    def test_import_twice_for_two_owners_creates_two_rows(self):
        import tempfile
        from pathlib import Path

        alice, bob = make_users()
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as handle:
            handle.write('Tracking Number,Status\n444444444444,Delivered\n')
            path = handle.name
        try:
            call_command('import_shipping_history_csv', path, user_id=alice.id)
            call_command('import_shipping_history_csv', path, user_id=bob.id)
        finally:
            Path(path).unlink(missing_ok=True)

        self.assertEqual(Package.objects.filter(tracking_number='444444444444').count(), 2)


class MultiCarrierImportTests(TestCase):
    def _run_import(self, csv_text, user):
        import tempfile
        from pathlib import Path
        from django.core.management import call_command

        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False, newline='') as handle:
            handle.write(csv_text)
            path = handle.name
        try:
            call_command('import_packages_csv', path, user_id=user.id)
        finally:
            Path(path).unlink(missing_ok=True)

    def setUp(self):
        self.alice, _ = make_users()

    def test_ups_export_detected_and_stored(self):
        self._run_import(
            'Date/Time Shipped,Tracking Number,Receiver Name,Service,Status,Delivery Date\n'
            '10/01/2026,1Z999AA10123456784,Acme Corp,UPS Ground,Delivered,10/04/2026\n',
            self.alice,
        )
        package = Package.objects.get(tracking_number='1Z999AA10123456784')
        self.assertEqual(package.carrier, 'ups')
        self.assertEqual(package.owner, self.alice)
        self.assertEqual(package.nickname, 'Acme Corp')
        self.assertTrue((package.status or '').lower().startswith('delivered'))

    def test_usps_export_detected_and_stored(self):
        self._run_import(
            'Ship Date,Tracking Number,Recipient Name,Status\n'
            '09/28/2026,9400111899223197428490,Jane Doe,In Transit\n',
            self.alice,
        )
        package = Package.objects.get(tracking_number='9400111899223197428490')
        self.assertEqual(package.carrier, 'usps')
        self.assertEqual(package.owner, self.alice)

    def test_explicit_service_column_overrides_pattern(self):
        self._run_import(
            'Ship Date,Tracking Number,Service,Status\n'
            '09/28/2026,9400111899223197428490,FedEx Ground Economy,In Transit\n',
            self.alice,
        )
        package = Package.objects.get(tracking_number='9400111899223197428490')
        self.assertEqual(package.carrier, 'fedex')

    def test_fedex_number_pattern(self):
        self._run_import(
            'Ship Date,Tracking Number,Status\n'
            '10/01/2026,794657111234,Delivered\n',
            self.alice,
        )
        package = Package.objects.get(tracking_number='794657111234')
        self.assertEqual(package.carrier, 'fedex')

    def test_same_file_two_owners_two_rows(self):
        bob = User.objects.get(username='bob')
        csv_text = 'Tracking Number,Status\n1Z999AA10123456784,Delivered\n'
        self._run_import(csv_text, self.alice)
        self._run_import(csv_text, bob)
        self.assertEqual(Package.objects.filter(tracking_number='1Z999AA10123456784').count(), 2)

    def test_older_row_does_not_clobber_newer(self):
        self._run_import('Tracking Number,Status,Delivery Date\n1Z999AA10123456784,Delivered,10/04/2026\n', self.alice)
        self._run_import('Tracking Number,Status,Delivery Date\n1Z999AA10123456784,Delivered,10/01/2026\n', self.alice)
        package = Package.objects.get(tracking_number='1Z999AA10123456784')
        self.assertIsNotNone(package.delivered_at)
        self.assertEqual(package.delivered_at.day, 4)

    def test_view_routes_fedex_history_to_fedex_importer(self):
        from tracker.csv_formats import looks_like_fedex_history, map_columns

        fedex_fields = ['Tracking Number', 'Status', 'Status with details', 'Recipient contact name']
        self.assertTrue(looks_like_fedex_history(fedex_fields))
        ups_fields = ['Date/Time Shipped', 'Tracking Number', 'Receiver Name', 'Service']
        self.assertFalse(looks_like_fedex_history(ups_fields))
        self.assertIn('tracking', map_columns(ups_fields))
        self.assertIn('tracking', map_columns(['Tracking #', 'Foo']))
        self.assertNotIn('tracking', map_columns(['Order ID', 'Foo']))
