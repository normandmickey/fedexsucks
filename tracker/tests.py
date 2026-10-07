from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from unittest.mock import patch

from . import ups as ups_client
from . import usps as usps_client
from .credentials import encrypt_secret
from .models import CarrierCredential, Package, SavedReference


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


class CarrierCredentialTests(TestCase):
    def setUp(self):
        self.alice, self.bob = make_users()

    def test_round_trip_encryption(self):
        cred = CarrierCredential.objects.create(carrier='ups', owner=self.alice)
        cred.set_secrets(api_key='MY-CLIENT-ID', secret_key='MY-SECRET')
        cred.save()
        fresh = CarrierCredential.objects.get(pk=cred.pk)
        self.assertEqual(fresh.api_key, 'MY-CLIENT-ID')
        self.assertEqual(fresh.secret_key, 'MY-SECRET')
        self.assertNotIn('MY-SECRET', fresh.secret_key_enc)

    def test_one_credential_per_carrier_per_user(self):
        CarrierCredential.objects.create(carrier='fedex', owner=self.alice)
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CarrierCredential.objects.create(carrier='fedex', owner=self.alice)

    def test_scoping_two_users_same_carrier(self):
        CarrierCredential.objects.create(carrier='fedex', owner=self.alice)
        CarrierCredential.objects.create(carrier='fedex', owner=self.bob)
        self.assertEqual(self.alice.carrier_credentials.count(), 1)
        self.assertEqual(self.bob.carrier_credentials.count(), 1)

    def test_masking(self):
        cred = CarrierCredential.objects.create(carrier='usps', owner=self.alice)
        cred.set_secrets(api_key='ABCDEFGHIJ')
        cred.save()
        self.assertEqual(cred.masked_api_key, 'ABCD••••GHIJ')


class CarrierKeysViewTests(TestCase):
    def setUp(self):
        self.alice, self.bob = make_users()

    def test_keys_page_requires_login(self):
        response = self.client.get('/keys/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])

    def test_save_encrypts_and_masks(self):
        self.client.force_login(self.alice)
        response = self.client.post('/keys/', {
            'action': 'save', 'carrier': 'fedex',
            'api_key': 'test-api-key-1234567890', 'secret_key': 'test-secret-0987654321',
        })
        self.assertRedirects(response, '/keys/')
        cred = CarrierCredential.objects.get(owner=self.alice, carrier='fedex')
        self.assertNotEqual(cred.api_key_enc, 'test-api-key-1234567890')
        self.assertNotEqual(cred.api_key_enc, '')
        page = self.client.get('/keys/')
        self.assertContains(page, 'test••••7890')
        self.assertNotContains(page, 'test-api-key-1234567890')

    def test_usps_requires_only_api_key(self):
        self.client.force_login(self.alice)
        self.client.post('/keys/', {'action': 'save', 'carrier': 'usps', 'api_key': 'usps-key-1'})
        self.assertTrue(CarrierCredential.objects.filter(owner=self.alice, carrier='usps').exists())

    def test_fedex_requires_secret(self):
        self.client.force_login(self.alice)
        self.client.post('/keys/', {'action': 'save', 'carrier': 'fedex', 'api_key': 'k'})
        self.assertFalse(CarrierCredential.objects.filter(owner=self.alice).exists())

    def test_keys_scoped_to_owner(self):
        CarrierCredential.objects.create(owner=self.alice, carrier='fedex',
                                         api_key_enc='alice-enc', secret_key_enc='alice-enc2')
        self.client.force_login(self.bob)
        page = self.client.get('/keys/')
        self.assertNotContains(page, 'alice-enc')
        self.client.post('/keys/', {'action': 'delete', 'carrier': 'fedex'})
        self.assertTrue(CarrierCredential.objects.filter(owner=self.alice).exists())

    def test_delete_removes_own_keys(self):
        CarrierCredential.objects.create(owner=self.alice, carrier='ups', api_key_enc='enc')
        self.client.force_login(self.alice)
        self.client.post('/keys/', {'action': 'delete', 'carrier': 'ups'})
        self.assertFalse(CarrierCredential.objects.filter(owner=self.alice).exists())


UPS_FIXTURE = {'trackResponse': {'shipments': [{'package': {
    'trackingNumber': '1Z8479RQ0392817465',
    'currentStatus': {'code': 'of', 'description': 'Out for Delivery'},
    'deliveryInformation': {'estimatedDeliveryDate': '2026-10-08'},
    'activityScan': [
        {'date': '2026-10-07', 'time': '08:14:00', 'status': {'code': 'of', 'description': 'Out for Delivery'},
         'location': {'address': {'city': 'MIDDLETOWN', 'stateCode': 'CT', 'countryCode': 'US'}}},
        {'date': '2026-10-06', 'time': '19:42:00', 'status': {'code': 'or', 'description': 'Origin Scan'},
         'location': {'address': {'city': 'LOUISVILLE', 'stateCode': 'KY'}}},
    ]}}]}}

USPS_FIXTURE = {
    'trackingNumber': '9400111899223197428490',
    'status': 'In Transit',
    'statusSummary': 'In Transit to Next Facility',
    'scanHistory': {'scan': [
        {'event': 'In Transit to Next Facility', 'date': 'October 6, 2026', 'time': '9:14 am',
         'scanLocation': 'CHARLOTTE NC DISTRIBUTION CENTER'},
        {'event': 'USPS in Possession of Item', 'date': '2026-10-04', 'time': '132000',
         'scanLocation': 'ATLANTA GA 30309'},
    ]},
}


class CarrierClientNormalizeTests(TestCase):
    def test_ups_normalize(self):
        result = ups_client.normalize_result(UPS_FIXTURE)
        self.assertEqual(result['trackingNumberInfo']['trackingNumber'], '1Z8479RQ0392817465')
        self.assertEqual(result['latestStatusDetail']['statusByLocale'], 'Out for Delivery')
        self.assertEqual(result['latestStatusDetail']['scanDateTime'], '2026-10-07T08:14:00')
        self.assertEqual(len(result['scanEvents']), 2)
        self.assertEqual(result['scanEvents'][0]['scanLocation']['city'], 'MIDDLETOWN')
        self.assertEqual(result['dateAndTimes'][0]['type'], 'Estimated Delivery')

    def test_usps_normalize(self):
        result = usps_client.normalize_result(USPS_FIXTURE)
        self.assertEqual(result['latestStatusDetail']['statusByLocale'], 'In Transit')
        self.assertEqual(result['latestStatusDetail']['code'], 'IT')
        self.assertEqual(len(result['scanEvents']), 2)
        self.assertEqual(result['scanEvents'][0]['scanLocation']['city'], 'CHARLOTTE NC DISTRIBUTION CENTER')

    def test_usps_delivered_maps_to_dl_not_exception(self):
        result = usps_client.normalize_result(dict(USPS_FIXTURE, status='Delivered', deliveryDate='2026-10-06'))
        self.assertEqual(result['latestStatusDetail']['code'], 'DL')
        self.assertEqual(result['dateAndTimes'][0]['type'], 'Delivered')


class RefreshThreadingTests(TestCase):
    def setUp(self):
        self.alice, _bob = make_users()

    @patch('tracker.views.fetch_tracking_result')
    def test_refresh_uses_byok_creds(self, mock_fetch):
        CarrierCredential.objects.create(
            owner=self.alice, carrier='fedex',
            api_key_enc=encrypt_secret('byok-api-1234567890'),
            secret_key_enc=encrypt_secret('byok-secret'))
        Package.objects.create(tracking_number='794653128740', owner=self.alice, carrier='fedex')
        mock_fetch.return_value = ({}, {
            'trackingNumberInfo': {'trackingNumber': '794653128740'},
            'latestStatusDetail': {'statusByLocale': 'In transit', 'code': 'IT'},
            'scanEvents': []})
        self.client.force_login(self.alice)
        response = self.client.post('/packages/794653128740/', {'action': 'refresh_tracking'})
        mock_fetch.assert_called_once_with(
            '794653128740', api_key='byok-api-1234567890', secret_key='byok-secret', base_url=None)
        self.assertContains(response, 'from FedEx')

    @patch('tracker.views.fetch_tracking_result')
    def test_refresh_env_fallback_without_creds(self, mock_fetch):
        Package.objects.create(tracking_number='490725361890', owner=self.alice, carrier='fedex')
        mock_fetch.return_value = ({}, {
            'trackingNumberInfo': {'trackingNumber': '490725361890'},
            'latestStatusDetail': {'statusByLocale': 'In transit', 'code': 'IT'},
            'scanEvents': []})
        self.client.force_login(self.alice)
        self.client.post('/packages/490725361890/', {'action': 'refresh_tracking'})
        mock_fetch.assert_called_once_with(
            '490725361890', api_key=None, secret_key=None, base_url=None)

    @patch('tracker.views.fetch_ups_tracking')
    def test_refresh_dispatches_ups(self, mock_ups):
        Package.objects.create(tracking_number='1Z8479RQ0392817465', owner=self.alice, carrier='ups')
        mock_ups.return_value = ({}, ups_client.normalize_result(UPS_FIXTURE))
        self.client.force_login(self.alice)
        response = self.client.post('/packages/1Z8479RQ0392817465/', {'action': 'refresh_tracking'})
        mock_ups.assert_called_once()
        self.assertContains(response, 'from UPS')

    def test_clients_raise_without_credentials(self):
        with self.assertRaises(RuntimeError):
            ups_client.fetch_tracking_result('1Z8479RQ0392817465')
        with self.assertRaises(RuntimeError):
            usps_client.fetch_tracking_result('9400111899223197428490')
