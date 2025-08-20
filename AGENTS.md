# AGENTS guidelines

This repo contains an offline parser for El Cerrito agenda packets. To work with the code in a Codex sandbox:

## Python environment

Use the provided `codex_setup.sh` script to create a Python 3.11 virtual environment and install wheels without network access:

```bash
./codex_setup.sh
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
    check_register_parser.py ECPackets/2025/"Agenda Packet (8.19.2025).pdf" --csv out.csv
```

Each PDF should log `✔ reconciled`.  The resulting CSV confirms the parser still works.

## Streamlining Codex work

Always set up the `codex-wheel-build` environment and run the parser command when modifying code so you can verify parsing succeeds without network access.
