#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
if [[ ! -x .venv/bin/python ]]; then python3 -m venv .venv; .venv/bin/pip install -r backend/requirements.txt; fi
if [[ ! -d frontend/node_modules ]]; then npm --prefix frontend ci; fi
.venv/bin/python backend/manage.py migrate
.venv/bin/python backend/manage.py runserver 127.0.0.1:8000 --noreload &
backend_pid=$!
trap 'kill "$backend_pid" 2>/dev/null || true' EXIT INT TERM
npm --prefix frontend run dev -- --port 5173 --strictPort
