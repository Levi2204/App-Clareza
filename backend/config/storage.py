"""Writable per-user storage, independent of the executable and working directory."""
import os
import sys
from pathlib import Path


def data_directory():
    if os.environ.get('CLAREZA_DATA_DIR'):
        path = Path(os.environ['CLAREZA_DATA_DIR']).expanduser()
    elif sys.platform == 'win32':
        path = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'br.local.clareza'
    elif sys.platform == 'darwin':
        path = Path.home() / 'Library/Application Support/br.local.clareza'
    else:
        path = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'br.local.clareza'
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path.resolve()
