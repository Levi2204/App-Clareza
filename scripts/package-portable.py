"""A single Linux download that runs AppImage without requiring FUSE."""
from pathlib import Path
import hashlib
import shutil

root = Path(__file__).resolve().parent.parent
output = root / 'dist'
output.mkdir(exist_ok=True)
appimages = list((root / 'frontend/src-tauri/target/release/bundle/appimage').glob('*.AppImage'))
if len(appimages) != 1:
    raise SystemExit('Esperado exatamente um AppImage compilado.')
appimage = output / 'Clareza-linux-x86_64.AppImage'
shutil.copyfile(appimages[0], appimage)
appimage.chmod(0o755)
header = b"""#!/bin/sh
set -eu
clareza_tmp=$(mktemp -d "${TMPDIR:-/tmp}/clareza.XXXXXXXX")
trap 'rm -rf "$clareza_tmp"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
tail -n +13 "$0" > "$clareza_tmp/Clareza.AppImage"
chmod 700 "$clareza_tmp/Clareza.AppImage"
export APPIMAGE_EXTRACT_AND_RUN=1
"$clareza_tmp/Clareza.AppImage" "$@"
exit $?
# Payload
"""
assert len(header.splitlines()) == 12
portable = output / 'Clareza-linux-x86_64.run'
with portable.open('wb') as target, appimage.open('rb') as source:
    target.write(header)
    shutil.copyfileobj(source, target)
portable.chmod(0o755)
with (output / 'SHA256SUMS').open('w') as checksums:
    for path in [appimage, portable]:
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        checksums.write(f'{digest}  {path.name}\n')
print(f'Arquivo para distribuição: {portable}')
