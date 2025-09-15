# ECCheckParser

Utility for extracting the "Monthly Disbursement and Check Register Report"
from City of El Cerrito city council agenda packet PDFs. The project targets
offline parsing: source PDFs from [www.elcerrito.gov](https://www.elcerrito.gov)
reside under `data/originals/`, and parser artifacts (CSV, chunk JSON, payee
HTML, and register PDFs) used in tests live under `data/artifacts/`. Unit tests
enforce payee and description extraction fidelity.
The script `check_register_parser.py` reads a packet PDF and emits a CSV file
containing one row per check along with a couple of simple aggregates. It can
also produce an HTML quadtree showing payees sized by total dollar amount and
optionally extracts the check register pages into a standalone PDF.

Sample agenda packets live under `data/originals/YYYY/` with derived
artifacts (CSV, chunk JSON, payee HTML and register PDFs) in `data/artifacts/`.

## Installation

This project targets CPython **3.11**. If your system provides multiple Python
versions, invoke the `python3.11` interpreter explicitly. The included
`scripts/codex_setup.sh` script creates an offline virtual environment using that
interpreter:

```bash
./scripts/codex_setup.sh
source codex-wheel-build/bin/activate
```

The virtual environment installs dependencies from the `vendor/` wheelhouse
without requiring network access.

## Usage

```bash
python check_register_parser.py path/to/Agenda\ Packet.pdf --csv output.csv --html payees.html --pdf
```

If output flags are supplied without filenames, the parser uses a `YYYY-MM`
prefix so files sort chronologically:

- `--csv`: `YYYY-MM.csv`
- `--json`: `YYYY-MM.json`
- `--html`: `YYYY-MM-payees.html`
- `--chunks-json`: `YYYY-MM-chunks.json`
- `--pdf`: `YYYY-MM-register.pdf` (multi-month registers emit `YYYY-MM-MM-register.pdf`)

The parser requires `pdfplumber` for table extraction.  After running, the script
prints the number of checks parsed and the total disbursed amount as a basic
sanity check.

## General Fund Budget Update extraction

Agenda packets often include a "General Fund Budget Update" section. The
`fund_update_parser.py` CLI extracts each page containing that heading into a
standalone PDF. By default the script stores artifacts under
`data/artifacts/fund_updates/` using the meeting date embedded in the packet
filename:

```bash
python fund_update_parser.py "data/originals/2025/Agenda Packet (rev. 9.25.2025).pdf"
```

You can supply `--out` to override the destination path or `--artifact-dir` to
redirect the default directory.

## Tests

Regression and unit tests reside in the `tests/` directory.  Run them with:

```bash
python -m unittest discover -s tests
```

The test suite verifies payee/description splitting and other parsing behavior.
