"""Freeze the backend, SQLite and Python; never include user databases or .env."""
import os
from pathlib import Path
import subprocess
import sys
import shutil

root = Path(__file__).resolve().parent.parent
env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'config.settings',
       'CLAREZA_DATA_DIR': str(root / '.desktop/build-data'),
       'PYTHONPATH': str(root / 'backend')}
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
    '--onedir', '--name', 'clareza-service',
    '--distpath', str(root / 'frontend/src-tauri/service'),
    '--workpath', str(root / '.desktop/pyinstaller'),
    '--specpath', str(root / '.desktop'),
    '--paths', str(root / 'backend'),
    '--collect-submodules', 'finance', '--collect-submodules', 'config',
    '--collect-submodules', 'django', '--collect-all', 'rest_framework',
    '--collect-all', 'corsheaders', '--hidden-import', 'django.db.backends.sqlite3',
    '--exclude-module', 'psycopg', '--exclude-module', 'psycopg2',
    '--exclude-module', 'django.db.backends.postgresql',
    '--exclude-module', 'django.db.backends.mysql',
    '--exclude-module', 'django.db.backends.oracle',
    str(root / 'backend/desktop_runtime.py')], env=env, check=True)

# WebKit probes appsink even without video. Ship this small plugin with the GUI.
if sys.platform == 'linux':
    plugins = subprocess.check_output(['pkg-config', '--variable=pluginsdir', 'gstreamer-1.0'], text=True).strip()
    shutil.copyfile(Path(plugins) / 'libgstapp.so', root / 'frontend/src-tauri/service/libgstapp.so')
