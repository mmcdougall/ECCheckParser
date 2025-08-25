#!/usr/bin/env bash
set -euo pipefail

# --- Config (override by exporting PY) ---
: "${PY:=python3.11}"
MAC_DIR="vendor/wheels-mac"
LIN_DIR="vendor/wheels-linux"

# --- Find repo root (prefer Git), else the script's dir ---
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || echo "$SCRIPT_DIR")"
cd "$REPO_ROOT"

echo "[debug] PWD=$(pwd)"
test -f requirements.txt || { echo "requirements.txt not found in $(pwd)"; exit 1; }

# --- Ensure venv and up-to-date build tooling ---
if [[ ! -d "codex-wheel-build" ]]; then
  "$PY" -m venv codex-wheel-build
fi
source codex-wheel-build/bin/activate
python -m pip install --upgrade pip setuptools wheel

# --- Fresh wheel dirs ---
rm -rf "$MAC_DIR" "$LIN_DIR"
mkdir -p "$MAC_DIR" "$LIN_DIR"

echo "[1/3] Building macOS wheels..."
pip wheel -r requirements.txt -w "$MAC_DIR"

echo "[2/3] Downloading manylinux2014 cp311 wheels..."
pip download \
  -r requirements.txt \
  -d "$LIN_DIR" \
  --only-binary=:all: \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --abi cp311 \
  --python-version 311

echo "[3/3] Listing results..."
echo "== mac wheels ==";   ls -1 "$MAC_DIR" || true
echo "== linux wheels =="; ls -1 "$LIN_DIR" || true

echo "Done."
