#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x dist/Clareza-linux-x86_64.run ]]; then
  printf 'Compile o aplicativo primeiro com ./build-desktop.sh\n' >&2
  exit 1
fi
exec dist/Clareza-linux-x86_64.run "$@"
