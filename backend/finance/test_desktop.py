from io import BytesIO
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient
from desktop_runtime import DesktopGate, prepare_database


class DesktopSecurityTests(TestCase):
    @override_settings(DESKTOP_TOKEN='desktop-secret')
    def test_desktop_requires_secret_even_on_loopback(self):
        client = APIClient()
        self.assertEqual(client.get('/api/v1/profile/').status_code, 403)
        self.assertEqual(client.get('/api/v1/accounts/', HTTP_X_CLAREZA_TOKEN='wrong').status_code, 403)
        self.assertEqual(client.get('/api/v1/profile/', HTTP_X_CLAREZA_TOKEN='desktop-secret').status_code, 200)
        self.assertEqual(client.get('/api/v1/accounts/', HTTP_X_CLAREZA_TOKEN='desktop-secret').status_code, 200)

    @override_settings(DESKTOP_TOKEN='desktop-secret')
    def test_local_deletion_cannot_be_recreated_without_desktop_secret(self):
        client = APIClient()
        client.get('/api/v1/profile/', HTTP_X_CLAREZA_TOKEN='desktop-secret')
        response = client.delete('/api/v1/profile/', {'confirmation': 'EXCLUIR'}, format='json', HTTP_X_CLAREZA_TOKEN='desktop-secret')
        self.assertEqual(response.status_code, 204)
        response = client.post('/api/v1/profile/', {'confirmation': 'CRIAR'}, format='json')
        self.assertEqual(response.status_code, 403)


class DesktopRuntimeTests(SimpleTestCase):
    def test_wsgi_gate_blocks_before_django(self):
        reached = []
        def application(environ, start):
            reached.append(True)
            return [b'OK']
        gate = DesktopGate(application, 'secret')
        status = []
        self.assertIn(b'Desktop authentication', b''.join(gate({}, lambda code, headers: status.append(code))))
        self.assertEqual(status, ['403 Forbidden'])
        self.assertEqual(reached, [])
        self.assertEqual(gate({'HTTP_X_CLAREZA_TOKEN': 'secret'}, lambda *_: None), [b'OK'])

    def test_sqlite_backup_preserves_committed_records(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'CLAREZA_DATA_DIR': directory}):
                prepare_database()
                database = Path(directory) / 'clareza.sqlite3'
                with sqlite3.connect(database) as connection:
                    connection.execute('CREATE TABLE example (value TEXT)')
                    connection.execute("INSERT INTO example VALUES ('saved')")
                prepare_database()
                backup = next((Path(directory) / 'backups').glob('*.sqlite3'))
                with sqlite3.connect(backup) as connection:
                    self.assertEqual(connection.execute('SELECT value FROM example').fetchone(), ('saved',))
                self.assertEqual(database.stat().st_mode & 0o777, 0o600)

    def test_storage_is_independent_of_working_directory(self):
        from config.storage import data_directory
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'XDG_DATA_HOME': directory}, clear=True):
                self.assertEqual(data_directory(), Path(directory) / 'br.local.clareza')
