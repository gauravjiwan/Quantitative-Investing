#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
if [[ -n "${PYTHON_BIN:-}" ]]; then
  exec "$PYTHON_BIN" scripts/reproduce.py
fi

for executable in python3.13 python3.12 python3.11 python3; do
  if command -v "$executable" >/dev/null 2>&1 && "$executable" -c 'import sys; raise SystemExit(not ((3, 11) <= sys.version_info[:2] < (3, 14)))'; then
    exec "$executable" scripts/reproduce.py
  fi
done
echo 'Python 3.11, 3.12, or 3.13 is required. Set PYTHON_BIN if installed elsewhere.' >&2
exit 2
