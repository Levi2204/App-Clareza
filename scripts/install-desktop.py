"""Register the already built local application in the user's Linux application menu."""
from pathlib import Path
import os
import shutil
import subprocess

root = Path(__file__).resolve().parent.parent
binary = root / 'dist/Clareza-linux-x86_64.run'
if not binary.is_file():
    raise SystemExit('Execute ./build-desktop.sh antes de instalar o atalho.')

data_home = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
installed = data_home / 'clareza-app'
installed.mkdir(parents=True, exist_ok=True)
shutil.copyfile(binary, installed / binary.name)
binary = installed / binary.name
binary.chmod(0o755)
applications = data_home / 'applications'
icons = data_home / 'icons/hicolor/256x256/apps'
applications.mkdir(parents=True, exist_ok=True)
icons.mkdir(parents=True, exist_ok=True)
shutil.copyfile(root / 'frontend/src-tauri/icons/128x128@2x.png', icons / 'br.local.clareza.png')

def exec_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'

launcher = applications / 'br.local.clareza.desktop'
launcher.write_text('\n'.join([
    '[Desktop Entry]', 'Version=1.0', 'Type=Application', 'Name=Clareza',
    'Comment=Suas finanças pessoais, com mais clareza',
    'Exec=' + exec_quote(binary),
    'Icon=br.local.clareza', 'Terminal=false', 'Categories=Office;Finance;',
    'StartupNotify=true', 'StartupWMClass=clareza', '',
]))
launcher.chmod(0o644)
if shutil.which('update-desktop-database'):
    subprocess.run(['update-desktop-database', str(applications)], check=False)
print(f'Clareza disponível no menu de aplicativos. Atalho: {launcher}')
