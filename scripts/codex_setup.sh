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
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v pyenv >/dev/null 2>&1; then
    pyenv install -s 3.11 >/dev/null 2>&1 || true
    pyenv local 3.11 >/dev/null 2>&1 || true
  fi
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: python3.11 not found in PATH. Install Python 3.11 and rerun."
  exit 1
fi

"$PYTHON_BIN" - <<'PY'
import sys, platform
if sys.version_info[:2] != (3, 11):
    raise SystemExit(
        f"ERROR: Expected Python 3.11.x, found {sys.version.split()[0]}"
    )
print("Interpreter OK:", sys.version, sys.executable, platform.platform())
PY

# --- Fresh venv ---
rm -rf "$VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"
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
