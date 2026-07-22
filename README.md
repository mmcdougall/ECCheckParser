# ECCheckParser

Utility for extracting the "Monthly Disbursement and Check Register Report"
from City of El Cerrito city council agenda packet PDFs. Source PDFs from
[www.elcerrito.gov](https://www.elcerrito.gov) reside under `data/originals/`,
and parser artifacts (CSV, chunk JSON, payee HTML, and register PDFs) used in
tests live under `data/artifacts/`. Unit tests enforce payee and description
extraction fidelity.
The script `check_register_parser.py` reads a packet PDF and emits a CSV file
containing one row per check along with a couple of simple aggregates. It can
also produce an HTML quadtree showing payees sized by total dollar amount and
optionally extracts the check register pages into a standalone PDF.

ECCheckParser was created and originally architected by **Michael McDougall**
as an independent civic project. It is not an official project or publication
of the City of El Cerrito or its Financial Advisory Board. See the
[civic-purpose statement](docs/CIVIC_PURPOSE.md), [credits](CREDITS.md), and
[copyright and independence notice](NOTICE.md).

Canonical agenda packets live under `data/originals/YYYY/agenda-packets/` with derived
artifacts (CSV, chunk JSON, payee HTML and register PDFs) in `data/artifacts/`.
PDFs are stored through Git LFS.

The parser automates extraction from imperfect PDF source material. Generated
results are not an audit or official accounting and should be verified against
the original City documents. [`PROVENANCE.md`](docs/PROVENANCE.md) describes the
project's approach to traceable, self-identifying outputs.

## Installation

This project supports CPython **3.11 and newer**. Create a virtual environment
with any supported interpreter and install the dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

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
- `--pdf`: `YYYY-MM-register.pdf` (contiguous multi-month registers emit `YYYY-MM-MM-register.pdf`)

Packets with disjoint register sections emit one output set per section instead
of combining separated agenda attachments into a single file range.

## Discovering and caching CivicClerk agendas

Use `civicclerk_documents.py` to discover City Council meetings through the
public CivicClerk API and cache published agenda documents locally:

```bash
python civicclerk_documents.py list --year 2026 --month 6
python civicclerk_documents.py current --scan-registers --extract-registers
python civicclerk_documents.py cache --year 2026 --month 6 --scan-registers
```

`current` selects the next upcoming meeting with published agenda documents, or
the latest recent meeting when no upcoming documents are available. By default
the tool caches only the agenda packet. Canonical files use compact names such
as `2026-07-21 Agenda Packet.pdf` under `agenda-packets/`. Standalone agendas
use the matching `agendas/` directory when requested with `--document agenda`.

Each year has a human-readable `manifest.json` containing CivicClerk file ids,
publication timestamps, official names, source URLs, sizes, and checksums. The
tool skips a download when the current file id and publication timestamp have
not changed. When CivicClerk publishes a new version, the prior canonical file
moves to `agenda-packet-revisions/` or `agenda-revisions/` with a short
publication-date suffix before the replacement is installed.

When `--scan-registers` is set, cached agenda packets are checked with the same
page detection used by `check_register_parser.py`. `--extract-registers` also
writes found register pages to `data/artifacts/pdfs/` using the existing
`YYYY-MM-register.pdf` naming.

The parser requires `pdfplumber` for table extraction.  After running, the script
prints the number of checks parsed and the total disbursed amount as a basic
sanity check.

To audit generated artifacts for missing register months and quarterly General
Fund updates:

```bash
python check_register_parser.py --audit-archive
```

The audit scans `data/artifacts/csv/` and `data/artifacts/fund_updates/` by
default. It reports missing months between the earliest and latest covered
register months, missing fiscal quarters between the earliest and latest covered
General Fund update quarters, and exits nonzero when gaps or invalid artifacts
are found.

## Quarterly financial report extraction

Agenda packets may include either a General Fund Budget Update or a Quarterly
Cash and Investment Report. The `fund_update_parser.py` CLI identifies the
report family and extracts its agenda bill and attachments into a standalone
PDF. General Fund updates are stored under `data/artifacts/fund_updates/`;
cash and investment reports are stored under `data/artifacts/cash_investments/`.
Both use the meeting date embedded in the packet filename:

```bash
python fund_update_parser.py "data/originals/2025/agenda-packets/2025-09-16 Agenda Packet.pdf"
```

You can supply `--out` to override the destination path or `--artifact-dir` to
override the report-specific default directory.

## Tests

Regression and unit tests reside in the `tests/` directory.  Run them with:

```bash
python -m unittest discover -s tests
```

The test suite verifies payee/description splitting and other parsing behavior.

## Citation and attribution

If you use the software or publish analysis produced with it, please preserve
the creator and contributor credits and cite the project. Machine-readable
citation metadata is available in [`CITATION.cff`](CITATION.cff).

Suggested citation while the project retains its working name:

> Michael McDougall, *ECCheckParser: an independent civic software project for
> understanding the City of El Cerrito's published financial records*.

Modified versions should identify their changes and maintainers and should not
imply that they are maintained or endorsed by Michael McDougall, the City of El
Cerrito, or its Financial Advisory Board.

## License

Unless a file says otherwise, the original software and project documentation
are copyright 2025–2026 Michael McDougall and are licensed under the
[GNU Affero General Public License, version 3 or later](LICENSE).

Commercial use is permitted. Distribution of the software and operation of a
modified version as a network service are subject to the license's
corresponding-source requirements. Private use and private modification are
permitted. The license text controls if this summary and the license differ.

City records in `data/originals/`, extracted public-record material, and
third-party dependencies are not relicensed by this project. See
[`NOTICE.md`](NOTICE.md) for the precise scope and origin notice.
