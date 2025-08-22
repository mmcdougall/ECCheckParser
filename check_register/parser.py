# -*- coding: utf-8 -*-
"""
Core logic for extracting "Monthly Disbursement and Check Register" entries from City of El Cerrito Agenda Packet PDFs.
"""

from __future__ import annotations

import re
import logging
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Tuple

import pdfplumber

from payee_splitter import split_payee_desc_block
from .models import CheckEntry


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
        return split_payee_desc_block(block)

    # ---------- main extraction ----------
    def extract(self) -> List[CheckEntry]:
        entries: List[CheckEntry] = []

        current_month: Optional[int] = None
        current_year: Optional[int] = None
        mode: Optional[str] = None  # "check" or "eft"
        current_row: Optional[CheckEntry] = None
        current_block: str = ""

        logging.getLogger("pdfminer").setLevel(logging.ERROR)
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



