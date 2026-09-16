"""Local desktop service supervised by the Tauri process (no shell or public listener)."""
import contextlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import threading
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server

def prepare_database():
    from config.storage import data_directory
    import sqlite3
    import datetime
    path = data_directory() / 'clareza.sqlite3'
    # SQLite backup includes committed WAL data and never copies an open file blindly.
    if path.exists():
        backups = data_directory() / 'backups'
        backups.mkdir(exist_ok=True, mode=0o700)
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        with sqlite3.connect(path) as source, sqlite3.connect(backups / f'clareza-{stamp}.sqlite3') as target:
            source.backup(target)
        for expired in sorted(backups.glob('clareza-*.sqlite3'))[:-10]:
            expired.unlink()
    with sqlite3.connect(path) as connection:
        connection.execute('PRAGMA journal_mode=WAL')
    path.chmod(0o600)


class DesktopGate:
    """The listener is loopback-only and every request requires a per-launch secret."""
    def __init__(self, app, token):
        self.app, self.token = app, token

    def __call__(self, environ, start_response):
        supplied = environ.get('HTTP_X_CLAREZA_TOKEN', '')
        if not hmac.compare_digest(supplied, self.token):
            start_response('403 Forbidden', [('Content-Type', 'application/json')])
            return [b'{"detail":"Desktop authentication required."}']
        return self.app(environ, start_response)


class DesktopServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        # Avoid persisting financial request paths and profile content in logs.
        pass


def main():
    os.umask(0o077)
    server = None
    finished = threading.Event()

    def watch_parent():
        sys.stdin.buffer.read()
        if server is None:
            # Parent closed during startup; do not leave an orphan process.
            os._exit(0)
        finished.set()
        server.shutdown()

    threading.Thread(target=watch_parent, daemon=True).start()
    token = secrets.token_urlsafe(32)
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', DEBUG='0', LOCAL_MODE='1',
                      CLAREZA_DESKTOP_TOKEN=token, DJANGO_SECRET_KEY=secrets.token_urlsafe(48))
    prepare_database()
    import django
    django.setup()
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    with contextlib.redirect_stdout(sys.stderr):
        call_command('migrate', interactive=False, verbosity=0)
    server = make_server('127.0.0.1', 0, DesktopGate(get_wsgi_application(), token),
                         server_class=DesktopServer, handler_class=QuietHandler)
    # Handshake is read only by the parent, never written to the application log.
    print(json.dumps({'port': server.server_port, 'token': token}), flush=True)
    print('Clareza: serviço local pronto.', file=sys.stderr, flush=True)
    try:
        if not finished.is_set():
            server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        print('Clareza: serviço local encerrado.', file=sys.stderr, flush=True)


if __name__ == '__main__':
    main()
