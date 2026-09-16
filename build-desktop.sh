#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$PWD/.venv/bin:${CARGO_HOME:-$HOME/.cargo}/bin:$PATH"
.venv/bin/python scripts/build-service.py
export APPIMAGE_EXTRACT_AND_RUN=1
export NO_STRIP=1
if ! npm --prefix frontend run tauri -- build --bundles appimage 2>&1 | tee .desktop/tauri-build.log; then
  .venv/bin/python scripts/finish-appimage.py
fi
.venv/bin/python scripts/package-portable.py
