"""One-time, read-only PostgreSQL export into a NEW SQLite database.

Run with the old environment (psycopg installed). Never shipped with user data.
Refuses to overwrite an existing destination. Keep the original cluster as backup.
"""
import io
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.umask(0o077)
from config.storage import data_directory
destination = data_directory() / 'clareza.sqlite3'
if destination.exists():
    raise SystemExit('O SQLite já existe. A migração não sobrescreve dados.')

with tempfile.TemporaryDirectory(prefix='migration-', dir=destination.parent) as directory:
    from django.conf import settings
    settings.DATABASES['default']['NAME'] = str(Path(directory) / 'clareza.sqlite3')
    settings.DATABASES['legacy'] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'financas'),
        'USER': os.environ.get('POSTGRES_USER', 'financas'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
        'HOST': os.environ.get('POSTGRES_HOST', '127.0.0.1'),
        'PORT': os.environ.get('POSTGRES_PORT', '55433'),
    }
    import django
    django.setup()
    from django.core.management import call_command
    from django.db import connections, transaction
    call_command('migrate', interactive=False, verbosity=0)
    options = dict(exclude=['contenttypes', 'auth.permission', 'sessions'],
                   natural_foreign=True, natural_primary=True, verbosity=0)
    exported = io.StringIO()
    with transaction.atomic(using='legacy'):
        with connections['legacy'].cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        call_command('dumpdata', database='legacy', stdout=exported, **options)
    fixture = Path(directory) / 'migration.json'
    fixture.write_text(exported.getvalue())
    call_command('loaddata', str(fixture), verbosity=0)
    imported = io.StringIO()
    call_command('dumpdata', database='default', stdout=imported, **options)
    import json
    def canonical(raw):
        return sorted(json.loads(raw), key=lambda item: json.dumps(item, sort_keys=True))
    assert canonical(exported.getvalue()) == canonical(imported.getvalue()), 'A conferência dos registros falhou.'
    connections.close_all()
    staged = Path(directory) / 'clareza.sqlite3'
    with sqlite3.connect(staged) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
    # Hard link publishes atomically and fails if another process created the destination.
    os.link(staged, destination)
    print(f'Migração concluída e conferida: {destination}')
    print('O PostgreSQL original foi preservado. Nenhum dado pessoal entrou no pacote.')
