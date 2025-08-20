#!/usr/bin/env bash
# Set up Python environment for offline Codex use
python3.11 -m venv codex-wheel-build
source codex-wheel-build/bin/activate
case "$(uname)" in
  Linux*) wheel_dir="wheels-linux" ;;
  Darwin*) wheel_dir="wheels-mac" ;;
  *) echo "Unsupported OS"; exit 1 ;;
esac
pip install --no-index --find-links "vendor/${wheel_dir}" -r requirements.txt
