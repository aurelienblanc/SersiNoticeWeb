import io
from datetime import timedelta
from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from .models import AdministrationAccess, Marque
from .admin_access import client_address


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class SharedAdministrationTests(TestCase):
    password = 'Essais-SERSI-partages-2026!'

    def setUp(self):
        self.access = AdministrationAccess.objects.create(pk=1, password_hash=make_password(self.password))

    def connect(self, client=None, **kwargs):
        client = client or self.client
        return client.post('/admin/login/', {'password': self.password, **kwargs})

    def test_login_has_only_a_password_and_catalogue_stays_public(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        response = self.client.get('/admin/login/')
        self.assertContains(response, 'Mot de passe commun')
        self.assertNotContains(response, 'name="username"')
        self.assertNotContains(response, 'name="email"')
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        self.assertRedirects(self.connect(), '/admin/')

    def test_wrong_password_and_old_account_sessions_cannot_enter(self):
        response = self.client.post('/admin/login/', {'password': 'incorrect'})
        self.assertContains(response, 'Le mot de passe est incorrect.')
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        user = get_user_model().objects.create_superuser('legacy', password=self.password)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        self.assertEqual(self.client.get('/admin/catalogue/marque/add/').status_code, 302)

    def test_no_user_or_group_management_and_audited_changes_still_work(self):
        self.connect()
        response = self.client.get('/admin/')
        self.assertNotContains(response, '/admin/auth/user/')
        self.assertNotContains(response, '/admin/auth/group/')
        self.assertNotContains(response, '_sersi_administration')
        for url in ('/admin/auth/user/', '/admin/auth/group/'):
            self.assertEqual(self.client.get(url).status_code, 404)
        response = self.client.post('/admin/catalogue/marque/add/', {'nom': 'Marque ajoutée', '_save': 'Enregistrer'})
        self.assertEqual(response.status_code, 302)
        brand = Marque.objects.get(nom='Marque ajoutée')
        entry = LogEntry.objects.get()
        self.assertEqual(entry.object_id, str(brand.pk))
        self.assertFalse(entry.user.has_usable_password())
        history = self.client.get(f'/admin/catalogue/marque/{brand.pk}/history/')
        self.assertEqual(history.status_code, 200)
        self.assertNotContains(history, '_sersi_administration')

    def test_login_rotates_session_and_rejects_external_return_url(self):
        session = self.client.session
        session['before_login'] = True
        session.save()
        previous_key = session.session_key
        response = self.connect(next='https://outside.example/redirect')
        self.assertEqual(response.url, '/admin/')
        self.assertNotEqual(previous_key, self.client.session.session_key)
        self.assertFalse(Session.objects.filter(session_key=previous_key).exists())
        response = self.connect(next='/admin/catalogue/marque/')
        self.assertEqual(response.url, '/admin/catalogue/marque/')

    def test_csrf_protects_login_and_logout(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.connect(client).status_code, 403)
        client.get('/admin/login/')
        response = self.connect(client, csrfmiddlewaretoken=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.post('/admin/password_change/', {
            'current_password': self.password, 'new_password': self.password, 'confirmation': self.password,
        }).status_code, 403)
        self.assertEqual(client.post('/admin/logout/').status_code, 403)
        self.assertEqual(client.get('/admin/logout/').status_code, 405)
        response = client.post('/admin/logout/', {'csrfmiddlewaretoken': client.cookies['csrftoken'].value})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.get('/admin/').status_code, 302)

    def test_repeated_failures_are_limited_across_sessions_then_expire(self):
        start = timezone.now()
        with patch('catalogue.admin_access.timezone.now', return_value=start):
            for _ in range(4):
                self.assertEqual(Client().post('/admin/login/', {'password': 'incorrect'}).status_code, 200)
            self.assertEqual(Client().post('/admin/login/', {'password': 'incorrect'}).status_code, 429)
            self.assertEqual(self.connect().status_code, 429)
        with patch('catalogue.admin_access.timezone.now', return_value=start + timedelta(minutes=6)):
            self.assertEqual(self.connect().status_code, 302)

    def test_password_change_revokes_other_sessions_and_keeps_current_session(self):
        other = Client()
        self.connect()
        self.connect(other)
        new = 'Nouveau-SERSI-partage-2026!'
        response = self.client.post('/admin/password_change/', {
            'current_password': self.password, 'new_password': new, 'confirmation': new,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/admin/').status_code, 200)
        self.assertEqual(other.get('/admin/').status_code, 302)
        self.access.refresh_from_db()
        self.assertTrue(check_password(new, self.access.password_hash))
        self.assertContains(other.post('/admin/login/', {'password': self.password}), 'Le mot de passe est incorrect.')
        self.assertEqual(other.post('/admin/login/', {'password': new}).status_code, 302)

    @override_settings(SERSI_TRUST_PROXY=True)
    def test_trusted_proxy_keeps_client_login_limits_separate(self):
        proxy = {'REMOTE_ADDR': '172.20.0.4'}
        first = {**proxy, 'HTTP_X_REAL_IP': '192.168.1.10'}
        second = {**proxy, 'HTTP_X_REAL_IP': '192.168.1.11'}
        for _ in range(5):
            Client().post('/admin/login/', {'password': 'incorrect'}, **first)
        self.assertEqual(Client().post('/admin/login/', {'password': self.password}, **first).status_code, 429)
        self.assertEqual(Client().post('/admin/login/', {'password': self.password}, **second).status_code, 302)

    @override_settings(SERSI_TRUST_PROXY=False)
    def test_direct_clients_cannot_reset_limits_with_forwarded_headers(self):
        for index in range(5):
            Client().post('/admin/login/', {'password': 'incorrect'}, HTTP_X_REAL_IP=f'192.168.1.{index}', HTTP_X_FORWARDED_FOR=f'192.168.2.{index}')
        self.assertEqual(Client().post('/admin/login/', {'password': self.password}, HTTP_X_REAL_IP='192.168.1.99').status_code, 429)

    @override_settings(SERSI_TRUST_PROXY=True)
    def test_proxy_address_is_validated_and_normalized(self):
        factory = RequestFactory()
        for invalid in ('', 'host.example', '192.168.1.1, 192.168.1.2'):
            with self.subTest(address=invalid):
                request = factory.get('/', REMOTE_ADDR='172.20.0.4', HTTP_X_REAL_IP=invalid)
                self.assertEqual(client_address(request), '172.20.0.4')
        request = factory.get('/', HTTP_X_REAL_IP='2001:0db8:0:0:0:0:0:1')
        self.assertEqual(client_address(request), '2001:db8::1')

    def test_admin_requires_export_group_for_new_document_types(self):
        self.connect()
        response = self.client.post('/admin/catalogue/typedocument/add/', {'nom': 'Sans groupe', 'type_export': ''})
        self.assertEqual(response.status_code, 200)
        self.assertIn('type_export', response.context['adminform'].form.errors)

    def test_password_change_checks_current_password_strength_and_confirmation(self):
        self.connect()
        original_hash = self.access.password_hash
        for data in [
            {'current_password': 'incorrect', 'new_password': self.password, 'confirmation': self.password},
            {'current_password': self.password, 'new_password': 'abc', 'confirmation': 'abc'},
            {'current_password': self.password, 'new_password': self.password, 'confirmation': 'different'},
        ]:
            self.assertEqual(self.client.post('/admin/password_change/', data).status_code, 200)
            self.access.refresh_from_db()
            self.assertEqual(self.access.password_hash, original_hash)

    def test_unconfigured_access_fails_closed(self):
        self.access.delete()
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        self.assertEqual(self.connect().status_code, 503)

    def test_reset_command_hashes_password_and_revokes_existing_sessions(self):
        self.connect()
        new = 'Reinitialisation-SERSI-2026!'
        with patch('sys.stdin', io.StringIO(new + '\n')):
            call_command('set_admin_password', password_stdin=True, stdout=io.StringIO())
        self.access.refresh_from_db()
        self.assertNotEqual(self.access.password_hash, new)
        self.assertTrue(check_password(new, self.access.password_hash))
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        with patch('sys.stdin', io.StringIO('abc\n')):
            with self.assertRaises(CommandError):
                call_command('set_admin_password', password_stdin=True, stdout=io.StringIO())
