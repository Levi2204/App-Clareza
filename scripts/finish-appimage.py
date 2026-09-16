"""Compatibility fallback for GdkPixbuf 2.44 (no legacy loader directory).

Uses a workspace copy of Tauri's GTK deploy plugin; never changes host libraries.
The normal Ubuntu release workflow uses the unmodified Tauri packager.
"""
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent.parent
cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'tauri'
appdir = root / 'frontend/src-tauri/target/release/bundle/appimage/Clareza.AppDir'
build_log = root / '.desktop/tauri-build.log'
if not build_log.exists() or 'failed to run linuxdeploy' not in build_log.read_text():
    raise SystemExit('Falha anterior ao empacotamento; não será usado um executável antigo.')
legacy = subprocess.check_output(['pkg-config', '--variable=gdk_pixbuf_binarydir', 'gdk-pixbuf-2.0'], text=True).strip()
if not legacy or Path(legacy).exists() or not appdir.exists():
    raise SystemExit('Falha de empacotamento não reconhecida; consulte o log.')
source = (cache / 'linuxdeploy-plugin-gtk.sh').read_text()
start = source.index('copy_tree "$gdk_pixbuf_binarydir"')
end = source.index('\necho "Copying more libraries"', start)
source = source[:start] + '# GdkPixbuf 2.44 has no legacy modules to copy.\n' + source[end:]
plugin = root / '.desktop/linuxdeploy-plugin-gtk-compat.sh'
plugin.write_text(source)
plugin.chmod(0o755)
env = {**os.environ, 'LINUXDEPLOY': str(cache / 'linuxdeploy-x86_64.AppImage'),
       'APPIMAGE_EXTRACT_AND_RUN': '1', 'NO_STRIP': '1',
       'OUTPUT': str(appdir.parent / 'Clareza_1.0.0_amd64.AppImage'),
       'ARCH': 'x86_64'}
subprocess.run([str(plugin), '--appdir', str(appdir)], env=env, check=True)
subprocess.run([env['LINUXDEPLOY'], '--appimage-extract-and-run',
               '--appdir', str(appdir), '--output', 'appimage'], env=env, cwd=appdir.parent, check=True)
