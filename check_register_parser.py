#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_register_parser.py

Extracts "Monthly Disbursement and Check Register" entries from City of El Cerrito
Agenda Packet PDFs and writes a CSV.

Key features
- Robust header detection even when "City of El Cerrito / Payment Register" is split across lines.
- Parses both Accounts Payable Checks and EFTs subsections.
- Handles wrapped descriptions and amounts that land on the next line.
- Flags VOID / Voided / Voided/Reissued rows and excludes them from subtotal by default.
- Emits CSV with explicit schema, plus prints basic sanity totals.

Usage:
    python check_register_parser.py "Agenda Packet (8.19.2025).pdf" --csv out.csv

Dependencies:
    pip install pdfplumber
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass, asdict
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Tuple, Dict

import pdfplumber


# ------------------------------
# Data model
# ------------------------------
@dataclass
class CheckEntry:
    section_month: int           # e.g., 6 for June, 7 for July
    section_year: int            # e.g., 2025
    ap_type: str                 # "check" or "eft"
    number: str                  # keep as str to preserve leading zeros
    date: str                    # MM/DD/YYYY as text (packet uses this)
    status: str                  # Open / Voided / Voided/Reissued / etc.
    source: str                  # usually "Accounts Payable"
    payee: str
    description: str
    amount: Decimal
    voided: bool                 # True if VOID/Voided appears


# ------------------------------
# Parser
# ------------------------------
class CheckRegisterParser:
    # Match the single line that contains both From/To dates.
    # Example: "From Payment Date: 6/1/2025 - To Payment Date: 6/30/2025"
    _block_hdr = re.compile(
        r"^From Payment Date:\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*-\s*To Payment Date:\s*(\d{1,2})/(\d{1,2})/(\d{4})$",
        re.IGNORECASE
    )

    # Subsection headings can vary slightly in punctuation/spacing
    _checks_hdr = re.compile(r"^Accounts Payable\s*-?\s*Checks$", re.IGNORECASE)
    _efts_hdr   = re.compile(r"^Accounts Payable\s*-?\s*EFT'?s$", re.IGNORECASE)

    # Typical data row start pattern:
    # "<num> <MM/DD/YYYY> <Status> Accounts Payable <tail>"
    # Example:
    # "93336 06/12/2025 Open Accounts Payable Dixon Resources Unlimited ... $6,847.50"
    _row_start = re.compile(
        r"^\s*(\d{3,7})\s+(\d{2}/\d{2}/\d{4})\s+([A-Za-z /]+?)\s+(Accounts Payable)\s+(.*)$"
    )

    # Lines containing a VOID marker anywhere
    _void_marker = re.compile(r"\bVOID(?:ED|ED/REISSUED)?\b", re.IGNORECASE)

    # Amount is last token (with optional minus) like $12,345.67
    _amount_tail = re.compile(r"\$-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?$")

    # Obvious non-data lines to skip
    _skip_line = re.compile(
        r"^(?:TOTAL CHECKS|TOTAL EFT|TOTAL EFT'S|TOTAL EFT’S|Checks & EFT'?s|All Status|GRAND TOTAL|"
        r"ACCOUNTS PAYABLE|PAYROLL|City of El Cerrito|Payment Register|Open\s+\d+|Voided|Total\s+\d+)$",
        re.IGNORECASE
    )

    def __init__(self, pdf_path: Path, keep_voided: bool = True):
        self.pdf_path = Path(pdf_path)
        self.keep_voided = keep_voided

    # ---------- helpers ----------
    @staticmethod
    def _money_to_decimal(s: str) -> Decimal:
        s = s.strip().replace("$", "").replace(",", "")
        if s == "":
            return Decimal("0.00")
        return Decimal(s)

    @staticmethod
    def _split_payee_desc_block(block: str) -> Tuple[str, str]:
        """Split a block containing payee and description into components."""
        block = block.replace("\r", " ").replace("\n", " ").strip()
        if not block:
            return "", ""

        # Known multi-word payees where the description immediately follows
        KNOWN_PREFIXES = [
            "ALAMEDA COUNTY FIRE DEPARTMENT",
            "BAY AREA NEWS GROUP",
            "CITY OF OAKLEY",
            "DIEGO TRUCK REPAIR",
            "L.N. CURTIS & SONS",
        ]
        for prefix in KNOWN_PREFIXES:
            if block.upper().startswith(prefix):
                return prefix, block[len(prefix) :].strip()

        fd_match = re.search(r"\bFD\s+\d+\b", block)
        if fd_match:
            idx = fd_match.start()
            return block[:idx].rstrip(), block[idx:].lstrip()

        parts = re.split(r"\s{2,}", block, maxsplit=1)
        if len(parts) == 2:
            payee, desc = parts
        else:
            suffix_match = None
            for m in re.finditer(r"\b(?:LLP|LLC|INC|CORP|CO|COMPANY|LTD)(?:[.,])?(?=\s|$)", block):
                suffix_match = m
            if suffix_match:
                payee = block[: suffix_match.end()]
                desc = block[suffix_match.end() :]
            else:
                parts = block.split(" ", 1)
                if len(parts) == 2:
                    payee, desc = parts
                else:
                    payee, desc = block, ""

        while payee.endswith(",") and desc:
            first, *rest = desc.split(" ")
            payee = f"{payee} {first}".rstrip()
            desc = " ".join(rest)

        return payee.strip(), desc.strip()

    # ---------- main extraction ----------
    def extract(self) -> List[CheckEntry]:
        entries: List[CheckEntry] = []

        current_month: Optional[int] = None
        current_year: Optional[int] = None
        mode: Optional[str] = None  # "check" or "eft"
        current_row: Optional[CheckEntry] = None
        current_block: str = ""

        with pdfplumber.open(self.pdf_path) as pdf:
            for page in pdf.pages:
                lines = (page.extract_text() or "").splitlines()
                for line in lines:
                    line = line.rstrip()

                    if not line or self._skip_line.match(line):
                        continue

                    # Section boundary with explicit dates
                    b = self._block_hdr.match(line)
                    if b:
                        # Use the "To Payment Date" month/year as section label
                        current_month = int(b.group(4))
                        current_year = int(b.group(6))
                        mode = "check"  # checks typically listed first; will switch when EFT header appears
                        current_row = None
                        continue

                    # Subsection switches
                    if self._checks_hdr.match(line):
                        mode = "check"
                        current_row = None
                        continue

                    if self._efts_hdr.match(line):
                        mode = "eft"
                        current_row = None
                        continue

                    # If we're not inside a recognized section, ignore lines
                    if current_month is None or current_year is None:
                        continue

                    # New data row?
                    m = self._row_start.match(line)
                    if m:
                        if current_row and current_row.amount is not None:
                            entries.append(current_row)
                            current_row = None

        
                        number, date, status, source, rest = m.groups()
                        voided = bool(self._void_marker.search(line)) or "VOID" in status.upper() or "VOIDED" in status.upper()

                        m_amt = self._amount_tail.search(rest)
                        amt = None
                        block = rest.strip()
                        if m_amt:
                            amt = self._money_to_decimal(m_amt.group())
                            block = rest[: m_amt.start()].rstrip()

                        this_mode = mode or "check"

                        payee = desc = ""
                        if amt is not None:
                            payee, desc = self._split_payee_desc_block(block)

                        current_row = CheckEntry(
                            section_month=current_month,
                            section_year=current_year,
                            ap_type=this_mode,
                            number=number.strip(),
                            date=date.strip(),
                            status=status.strip(),
                            source=source.strip(),
                            payee=payee,
                            description=desc,
                            amount=amt if amt is not None else Decimal("0.00"),
                            voided=voided,
                        )

                        if amt is not None:
                            entries.append(current_row)
                            current_row = None
                        else:
                            current_block = block
                        continue

                    if current_row is not None:
                        m_amt = self._amount_tail.search(line)
                        if m_amt:
                            lead = line[: m_amt.start()].strip()
                            if lead:
                                current_block = (current_block + " " + lead).strip()
                            current_row.amount = self._money_to_decimal(m_amt.group())
                            payee, desc = self._split_payee_desc_block(current_block)
                            current_row.payee = payee
                            current_row.description = desc
                            entries.append(current_row)
                            current_row = None
                            current_block = ""
                        else:
                            if line and not self._row_start.match(line):
                                current_block = (current_block + " " + line.strip()).strip()

            # Flush dangling row if it somehow has an amount already
            if current_row and current_row.amount is not None:
                entries.append(current_row)

        # Optionally drop voided entries from the dataset (but keep them by default)
        if not self.keep_voided:
            entries = [e for e in entries if not e.voided]

        return entries

    # ---------- output utilities ----------
    @staticmethod
    def write_csv(entries: List[CheckEntry], out_path: Path) -> None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow([
                "section_month", "section_year", "ap_type", "number", "date",
                "status", "source", "payee", "description", "amount", "voided"
            ])
            for e in entries:
                w.writerow([
                    e.section_month, e.section_year, e.ap_type, e.number, e.date,
                    e.status, e.source, e.payee, e.description,
                    f"{e.amount:.2f}", "Y" if e.voided else "N"
                ])

    @staticmethod
    def write_json(entries: List[CheckEntry], out_path: Path) -> None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        **asdict(e),
                        "amount": float(e.amount)  # JSON-friendly
                    } for e in entries
                ],
                f,
                ensure_ascii=False,
                indent=2
            )

    @staticmethod
    def sanity(entries: List[CheckEntry]) -> Dict[str, object]:
        """
        Basic stats by type, and total excluding voided rows.
        """
        cnt = len(entries)
        by_type = {"check": 0, "eft": 0}
        total = Decimal("0.00")
        for e in entries:
            by_type[e.ap_type] = by_type.get(e.ap_type, 0) + 1
            if not e.voided:
                total += e.amount
        return {"count": cnt, "by_type": by_type, "total_nonvoid": total}

    @staticmethod
    def month_rollups(entries: List[CheckEntry]) -> Dict[Tuple[int, int], Dict[str, Decimal]]:
        """
        Returns {(month, year): {"checks": Decimal, "efts": Decimal, "grand": Decimal}}
        excluding voided rows in sums.
        """
        out: Dict[Tuple[int, int], Dict[str, Decimal]] = {}
        for e in entries:
            key = (e.section_month, e.section_year)
            if key not in out:
                out[key] = {"checks": Decimal("0.00"), "efts": Decimal("0.00"), "grand": Decimal("0.00")}
            if not e.voided:
                if e.ap_type == "check":
                    out[key]["checks"] += e.amount
                elif e.ap_type == "eft":
                    out[key]["efts"] += e.amount
                out[key]["grand"] += e.amount
        return out


# ------------------------------
# CLI
# ------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Parse El Cerrito Agenda Packet check/EFT registers into CSV/JSON.")
    ap.add_argument("pdf", type=Path, help="Agenda Packet PDF path")
    ap.add_argument("--csv", type=Path, default=Path("checks.csv"), help="Output CSV path")
    ap.add_argument("--json", type=Path, default=None, help="Optional JSON output path")
    ap.add_argument("--drop-voided", action="store_true", help="Exclude voided/voided-reissued rows from output")
    ap.add_argument("--print-rollups", action="store_true", help="Print per-month rollups after parsing")
    args = ap.parse_args()

    parser = CheckRegisterParser(args.pdf, keep_voided=not args.drop_voided)
    entries = parser.extract()

    # Write outputs
    CheckRegisterParser.write_csv(entries, args.csv)
    if args.json:
        CheckRegisterParser.write_json(entries, args.json)

    # Stats
    stats = CheckRegisterParser.sanity(entries)
    print(f"Rows: {stats['count']}  (checks={stats['by_type'].get('check', 0)}, efts={stats['by_type'].get('eft', 0)})")
    print(f"Total (non-void): ${stats['total_nonvoid']:.2f}")
    print(f"CSV: {args.csv}")
    if args.json:
        print(f"JSON: {args.json}")

    if args.print_rollups:
        roll = CheckRegisterParser.month_rollups(entries)
        if not roll:
            print("No month rollups to display.")
        else:
            print("\nPer-month rollups (non-void totals):")
            for (m, y), sums in sorted(roll.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                print(f"  {m:02d}/{y}: checks=${sums['checks']:.2f}  efts=${sums['efts']:.2f}  grand=${sums['grand']:.2f}")


if __name__ == "__main__":
    main()
