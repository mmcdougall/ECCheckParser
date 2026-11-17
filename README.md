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

Canonical agenda packets live under meeting-type roots such as
`data/originals/city-council/YYYY/agenda-packets/` and
`data/originals/financial-advisory-board/YYYY/agenda-packets/`. Derived artifacts
(CSV, chunk JSON, payee HTML and register PDFs) remain in `data/artifacts/`.
PDFs are stored through Git LFS.

Standalone finance legislation, historical background, and State Auditor records
live in [`data/references/city-finance/`](data/references/city-finance/README.md).
That collection includes original PDFs, searchable text, and source metadata.

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
- `--pdf`: `YYYY-MM-register.pdf`

Packets emit one output set per reporting month, including adjacent monthly
registers. Payment dates and overlapping rows remain as printed in each source
report; deduplicated monthly totals use the payment date.

## Discovering and caching CivicClerk agendas

Use `civicclerk_documents.py` to discover City Council or Financial Advisory
Board meetings through the public CivicClerk API and cache published agenda
documents locally:

```bash
python civicclerk_documents.py list --year 2026 --month 6
python civicclerk_documents.py current --scan-registers --extract-registers
python civicclerk_documents.py cache --year 2026 --month 6 --scan-registers
python civicclerk_documents.py cache --year 2026 --category 'Financial Advisory Board' --document agenda --document agenda-packet
```

`current` selects the next upcoming meeting with published agenda documents, or
the latest recent meeting when no upcoming documents are available. By default
the tool caches only the agenda packet. Canonical files use compact names such
as `2026-07-21 Agenda Packet.pdf` under the meeting type's `agenda-packets/`
directory. Standalone agendas use the matching `agendas/` directory when
requested with `--document agenda`.

Each meeting type/year has a human-readable `manifest.json` containing
CivicClerk file ids, publication timestamps, official names, source URLs,
sizes, and checksums. The tool skips a download when the current file id and
publication timestamp have not changed. When CivicClerk publishes a new
version, the prior canonical file moves to `agenda-packet-revisions/` or
`agenda-revisions/` with a short publication-date suffix before the replacement
is installed.

When `--scan-registers` is set, cached agenda packets are checked with the same
page detection used by `check_register_parser.py`. `--extract-registers` also
writes found register pages to `data/artifacts/pdfs/` using the existing
`YYYY-MM-register.pdf` naming.

## Discovering and caching City Archive Center records

`archivecenter_documents.py` reads selected indexes from the City's
[Archive Center](https://www.elcerrito.gov/Archive.aspx). It supports agendas,
agenda packets, minutes, work plans, and reports for any named board, committee,
council, or other source category. Each `--index KIND=AMID` maps a document kind
to the index ID in an official `Archive.aspx?AMID=...` URL. Repeat the option
to read several kinds. For example, the FAB work-plan index can be listed with:

```bash
python archivecenter_documents.py list --index work-plan=146
```

To cache custom indexes, supply `--meeting-type` with a lowercase folder name
such as `subdivision-committee`, the selected `--index` options, and a date
selection (`--date`, `--year`, or `--start` and `--end`). `--dry-run` prints the
planned paths and actions. Documents go under
`data/originals/<meeting-type>/YYYY/` using the same manifests and revision
layout as the existing archive. `--document` can restrict the selected kinds.

Caching accepts only unambiguous dated PDFs. Multiple same-date records of one
kind are reported as ambiguous. Listings containing only a fiscal year or a
year range remain visible in `list`; they need a verified full source date
before they can be filed in the dated archive. The tool does not derive a
meeting date from a fiscal-year label.

The legacy invocation without `--index` retains FAB agenda/report IDs 62 and 93
and the `financial-advisory-board` destination. Those indexes depend on the
City continuing to publish them. This legacy feed requires one same-date
agenda before an attachment report is accepted as an agenda packet. Custom
indexes can opt into that check with `--require-matching-agenda`.

The tool keeps a CivicClerk canonical file in place. `--include-variants` saves
a differing Archive Center copy as a source-marked revision, while an identical
copy is recorded as equivalent provenance without duplicating bytes. Archive
Center records use `archive_id` and `source_system: "archivecenter"`; CivicClerk
`file_id` values remain reserved for CivicClerk files.


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

To verify that cached source PDFs remain under the correct meeting type/year,
with every manifest path, PDF header, and SHA-256 checksum intact:

```bash
python check_register_parser.py --audit-originals
```

This read-only check discovers the category folders present in the archive,
including additional committees and commissions. It verifies current and
revision copies of agendas, packets, minutes, work plans, and reports, and
reports unreferenced PDFs, missing files, invalid locations, and changed bytes.
It scans all cached source PDFs, so it is best used before a release or after
a source refresh rather than during routine parser work. It checks the
integrity of the local collection; it does not establish that every published
City document has been collected.

## Quarterly financial report extraction

Agenda packets may include either a General Fund Budget Update or a Quarterly
Cash and Investment Report. The `fund_update_parser.py` CLI identifies the
report family and extracts its agenda bill and attachments into a standalone
PDF. General Fund updates are stored under `data/artifacts/fund_updates/`;
cash and investment reports are stored under `data/artifacts/cash_investments/`.
Both use the meeting date embedded in the packet filename:

```bash
python fund_update_parser.py "data/originals/city-council/2025/agenda-packets/2025-09-16 Agenda Packet.pdf"
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
