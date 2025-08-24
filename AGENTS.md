# AGENTS guidelines

This repo contains an offline parser for El Cerrito agenda packets. To work with the code in a Codex sandbox:

## Python environment

This repository includes a `.python-version` file that pins Python `3.11` via `pyenv`. If that version is missing, run `pyenv install -s 3.11` before continuing.

Use the provided `scripts/codex_setup.sh` script to create a Python 3.11 virtual environment and install wheels without network access. When multiple Python versions are installed, prefer the `python3.11` interpreter explicitly:

```bash
./scripts/codex_setup.sh  # uses python3.11 internally
```

The script creates a `codex-wheel-build` environment and installs from `vendor/wheels-linux` (or `vendor/wheels-mac` on macOS).  If you wish to do it manually:

```bash
python -m venv codex-wheel-build
source codex-wheel-build/bin/activate
pip install --no-index --find-links vendor/wheels-linux -r requirements.txt
```

## Running the parser

To generate a CSV from the 2023 statements run:

```bash
    check_register_parser.py data/originals/2025/"Agenda Packet (8.19.2025).pdf" --csv out.csv
```

Each PDF should log `✔ reconciled`.  The resulting CSV confirms the parser still works.

## Running tests

Unit tests live under the `tests/` directory.  Run them with:

```bash
python -m unittest discover -s tests
```

Always execute the test suite before committing changes to ensure payee splitting
and other behavior remain stable.

## Streamlining Codex work

Always set up the `codex-wheel-build` environment and run the parser command when modifying code so you can verify parsing succeeds without network access.
