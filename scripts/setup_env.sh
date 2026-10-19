#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${PYTHON_BIN:-}" ]]; then
  python_executable="$PYTHON_BIN"
elif command -v python3.13 >/dev/null 2>&1; then
  python_executable="$(command -v python3.13)"
elif command -v python3.12 >/dev/null 2>&1; then
  python_executable="$(command -v python3.12)"
elif command -v python3.11 >/dev/null 2>&1; then
  python_executable="$(command -v python3.11)"
else
  echo "Python 3.11, 3.12, or 3.13 is required. Set PYTHON_BIN to its executable." >&2
  exit 2
fi

"$python_executable" - <<'PY'
import sys
if sys.version_info < (3, 11) or sys.version_info >= (3, 14):
    raise SystemExit("Use Python 3.11, 3.12, or 3.13 for this workspace.")
print(f"Creating environment with Python {sys.version.split()[0]}")
PY

"$python_executable" -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install . -c requirements.lock
python -c 'import ps1; print("Installed PS1 package:", ps1.__file__)'
echo "Environment ready. Activate it with: source .venv/bin/activate"
