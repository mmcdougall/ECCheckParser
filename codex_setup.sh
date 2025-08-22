#!/usr/bin/env bash
set -Eeuo pipefail

VENV_DIR="${VENV_DIR:-codex-wheel-build}"

# --- Pick wheel dir based on OS ---
case "$(uname -s)" in
  Darwin) WHEEL_DIR="vendor/wheels-mac" ;;
  Linux)  WHEEL_DIR="vendor/wheels-linux" ;;
  *)
    echo "ERROR: Unsupported OS $(uname -s)"
    exit 1
    ;;
esac

# --- Robust guard: require CPython 3.11.x ---
python3 - <<'PY'
import sys, platform
if sys.version_info.major != 3 or sys.version_info.minor != 11:
    raise SystemExit(
        f"ERROR: Expected Python 3.11.x, found {sys.version.split()[0]}"
    )
print("Interpreter OK:", sys.version, sys.executable, platform.platform())
PY

# --- Fresh venv ---
rm -rf "$VENV_DIR"
python3.11 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# --- Strict offline pip flags ---
export PIP_NO_INDEX=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_PROGRESS_BAR=off

# --- Install requirements from local wheelhouse only ---
python -m pip install -q \
  --find-links "$WHEEL_DIR" \
  --only-binary=:all: \
  --no-build-isolation \
  -r requirements.txt

# --- Minimal debug info ---
python - <<'PY'
import sys, platform
print("Setup complete with:", sys.version.split()[0], "->", sys.executable, "|", platform.platform())
PY

echo "Activate with: source $VENV_DIR/bin/activate"
