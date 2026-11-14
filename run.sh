#!/usr/bin/env bash
set -euo pipefail

# Run from the script's own directory so paths resolve regardless of the caller's cwd.
cd "$(dirname "$0")"

# Create the venv if the interpreter is missing (a half-created venv gets repaired).
if [ ! -e .venv/bin/python ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install -r requirements.txt

export FEATUREFORGE_PORT="${FEATUREFORGE_PORT:-7466}"

exec .venv/bin/python server/app.py
