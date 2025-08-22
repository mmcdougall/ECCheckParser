# ECCheckParser

Utility for extracting the "Monthly Disbursement and Check Register Report"
from El Camino Healthcare District agenda packet PDFs.  The script
`check_register_parser.py` reads a packet PDF and emits a CSV file containing
one row per check along with a couple of simple aggregates.  It can also
produce an HTML quadtree showing payees sized by total dollar amount.

## Usage

```bash
python check_register_parser.py path/to/Agenda\ Packet.pdf --csv output.csv --html payees.html
```

The parser requires `pdfplumber` for table extraction.  After running, the script
prints the number of checks parsed and the total disbursed amount as a basic
sanity check.

## Setup

This project targets CPython **3.11**. If your system provides multiple Python
versions, invoke the `python3.11` interpreter explicitly. The included
`codex_setup.sh` script creates an offline virtual environment using that
interpreter:

```bash
./codex_setup.sh
source codex-wheel-build/bin/activate
```

The virtual environment installs dependencies from the `vendor/` wheelhouse
without requiring network access.

## Tests

Regression and unit tests reside in the `tests/` directory.  Run them with:

```bash
python -m unittest discover -s tests
```

The test suite verifies payee/description splitting and other parsing behavior.
