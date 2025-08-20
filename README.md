# ECCheckParser

Utility for extracting the "Monthly Disbursement and Check Register Report"
from El Camino Healthcare District agenda packet PDFs.  The script
`check_register_parser.py` reads a packet PDF and emits a CSV file containing
one row per check along with a couple of simple aggregates.

## Usage

```bash
python check_register_parser.py path/to/Agenda\ Packet.pdf --csv output.csv
```

The parser requires `pdfplumber` for table extraction.  After running, the script
prints the number of checks parsed and the total disbursed amount as a basic
sanity check.
