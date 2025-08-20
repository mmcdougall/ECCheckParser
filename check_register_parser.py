"""Parser for extracting Monthly Disbursement and Check Register reports from agenda packet PDFs.

This module defines a small utility for pulling the check register table from
PDF agenda packets, writing the result to a CSV file and performing a few
sanity checks on the totals.  It relies on ``pdfplumber`` for text extraction.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, List

import csv
import re

try:
    import pdfplumber  # type: ignore
except Exception as exc:  # pragma: no cover - dependency may be missing in CI
    pdfplumber = None  # type: ignore
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


@dataclass
class CheckEntry:
    """Single row within the check register."""

    check_number: str
    date: str
    payee: str
    amount: Decimal


class CheckRegisterParser:
    """Extract the check register table from a packet PDF."""

    heading_re = re.compile(r"Monthly Disbursement and Check Register Report", re.I)

    def __init__(self, pdf_path: Path):
        self.pdf_path = Path(pdf_path)
        if pdfplumber is None:  # pragma: no cover - executed only when dependency missing
            raise RuntimeError(
                "pdfplumber is required to parse PDF files"  # noqa: EM101
            ) from _IMPORT_ERROR

    def extract_checks(self) -> List[CheckEntry]:
        """Parse ``self.pdf_path`` and return the list of check entries."""

        checks: List[CheckEntry] = []
        with pdfplumber.open(self.pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if not self.heading_re.search(text):
                    continue

                tables = page.extract_tables() or []
                for table in tables:
                    for row in table:
                        if not row or not row[0]:
                            continue
                        # Assume a row structure like: [check no, date, payee, amount]
                        if row[0].strip().lower().startswith("check"):
                            # Skip header row
                            continue
                        try:
                            amount = Decimal(row[3].replace(",", ""))
                        except Exception:
                            continue
                        checks.append(
                            CheckEntry(
                                check_number=row[0].strip(),
                                date=row[1].strip(),
                                payee=row[2].strip(),
                                amount=amount,
                            )
                        )
        return checks

    @staticmethod
    def write_csv(checks: Iterable[CheckEntry], output_path: Path) -> None:
        """Write ``checks`` to ``output_path`` in CSV format."""

        with open(output_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["check_number", "date", "payee", "amount"])
            for entry in checks:
                writer.writerow(
                    [entry.check_number, entry.date, entry.payee, f"{entry.amount:.2f}"]
                )

    @staticmethod
    def sanity_checks(checks: Iterable[CheckEntry]) -> dict[str, Decimal | int]:
        """Return simple aggregates for the check list."""

        count = 0
        total = Decimal("0")
        for entry in checks:
            count += 1
            total += entry.amount
        return {"count": count, "total": total}


if __name__ == "__main__":  # pragma: no cover - simple CLI
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract Monthly Disbursement and Check Register Report from a PDF"
    )
    parser.add_argument("pdf", type=Path, help="Path to agenda packet PDF")
    parser.add_argument(
        "--csv", type=Path, default=Path("checks.csv"), help="Output CSV path"
    )

    args = parser.parse_args()

    cr_parser = CheckRegisterParser(args.pdf)
    checks = cr_parser.extract_checks()
    CheckRegisterParser.write_csv(checks, args.csv)
    stats = CheckRegisterParser.sanity_checks(checks)
    print(
        f"Extracted {stats['count']} checks totaling ${stats['total']:.2f} \n"
        f"CSV written to {args.csv}"
    )
