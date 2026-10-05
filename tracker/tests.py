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
