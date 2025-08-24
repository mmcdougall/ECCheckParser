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
from .models import CheckEntry, RowChunk, PositionedWord


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

    # ---------- raw extraction ----------
    def extract_raw_chunks(self) -> List[RowChunk]:
        chunks: List[RowChunk] = []

        current_month: Optional[int] = None
        current_year: Optional[int] = None
        mode: Optional[str] = None  # "check" or "eft"
        current_lines: List[str] = []
        current_words: List[List[PositionedWord]] = []

        def words_by_line(page) -> List[List[PositionedWord]]:
            """Group pdfplumber words into lines preserving x positions."""
            words = page.extract_words()
            words.sort(key=lambda w: w["top"])  # top-to-bottom
            lines: List[List[PositionedWord]] = []
            current: List[dict] = []
            current_top: Optional[float] = None
            for w in words:
                top = w["top"]
                if current_top is None or abs(top - current_top) < 3:  # y tolerance
                    current.append(w)
                    if current_top is None:
                        current_top = top
                else:
                    lines.append([PositionedWord(text=pw["text"], x0=pw["x0"]) for pw in sorted(current, key=lambda x: x["x0"])])
                    current = [w]
                    current_top = top
            if current:
                lines.append([PositionedWord(text=pw["text"], x0=pw["x0"]) for pw in sorted(current, key=lambda x: x["x0"])])
            return lines

        logging.getLogger("pdfminer").setLevel(logging.ERROR)
        with pdfplumber.open(self.pdf_path) as pdf:
            for page in pdf.pages:
                lines = (page.extract_text() or "").splitlines()
                word_lines = words_by_line(page)
                for idx, raw in enumerate(lines):
                    line = raw.rstrip()
                    wl = word_lines[idx] if idx < len(word_lines) else []

                    if not line or self._skip_line.match(line):
                        continue

                    b = self._block_hdr.match(line)
                    if b:
                        if current_lines:
                            chunks.append(
                                RowChunk(current_month, current_year, mode or "check", current_lines, current_words)
                            )
                            current_lines = []
                            current_words = []
                        current_month = int(b.group(4))
                        current_year = int(b.group(6))
                        mode = "check"
                        continue

                    if self._checks_hdr.match(line):
                        if current_lines:
                            chunks.append(
                                RowChunk(current_month, current_year, mode or "check", current_lines, current_words)
                            )
                            current_lines = []
                            current_words = []
                        mode = "check"
                        continue

                    if self._efts_hdr.match(line):
                        if current_lines:
                            chunks.append(
                                RowChunk(current_month, current_year, mode or "check", current_lines, current_words)
                            )
                            current_lines = []
                            current_words = []
                        mode = "eft"
                        continue

                    if current_month is None or current_year is None:
                        continue

                    if self._row_start.match(line):
                        if current_lines:
                            chunks.append(
                                RowChunk(current_month, current_year, mode or "check", current_lines, current_words)
                            )
                        current_lines = [line]
                        current_words = [wl]
                        if self._amount_tail.search(line):
                            chunks.append(
                                RowChunk(current_month, current_year, mode or "check", current_lines, current_words)
                            )
                            current_lines = []
                            current_words = []
                    else:
                        if current_lines:
                            current_lines.append(line)
                            current_words.append(wl)
                            if self._amount_tail.search(line):
                                chunks.append(
                                    RowChunk(current_month, current_year, mode or "check", current_lines, current_words)
                                )
                                current_lines = []
                                current_words = []

        if current_lines:
            chunks.append(RowChunk(current_month, current_year, mode or "check", current_lines, current_words))

        return chunks

    # ---------- chunk parsing ----------
    def _parse_chunk(self, chunk: RowChunk) -> CheckEntry:
        first = chunk.lines[0]
        m = self._row_start.match(first)
        if not m:
            raise ValueError(f"Chunk does not start with row pattern: {first}")

        number, date, status, source, rest = m.groups()

        voided = (
            bool(self._void_marker.search(first))
            or "VOID" in status.upper()
            or "VOIDED" in status.upper()
        )

        block_parts: List[str] = []
        m_amt = self._amount_tail.search(rest)
        amount: Optional[Decimal] = None
        if m_amt:
            amount = self._money_to_decimal(m_amt.group())
            block_parts.append(rest[: m_amt.start()].strip())
        else:
            block_parts.append(rest.strip())

        for line in chunk.lines[1:]:
            m_amt = self._amount_tail.search(line)
            if m_amt:
                lead = line[: m_amt.start()].strip()
                if lead:
                    block_parts.append(lead)
                amount = self._money_to_decimal(m_amt.group())
            else:
                block_parts.append(line.strip())

        block = " ".join(part for part in block_parts if part).strip()

        payee = desc = ""
        if amount is not None:
            payee, desc = self._split_payee_desc_block(block)

        return CheckEntry(
            section_month=chunk.section_month,
            section_year=chunk.section_year,
            ap_type=chunk.ap_type,
            number=number.strip(),
            date=date.strip(),
            status=status.strip(),
            source=source.strip(),
            payee=payee,
            description=desc,
            amount=amount if amount is not None else Decimal("0.00"),
            voided=voided,
        )

    def parse_chunks(self, chunks: List[RowChunk]) -> List[CheckEntry]:
        entries = [self._parse_chunk(c) for c in chunks]
        if not self.keep_voided:
            entries = [e for e in entries if not e.voided]
        return entries

    # ---------- main extraction ----------
    def extract(self) -> List[CheckEntry]:
        chunks = self.extract_raw_chunks()
        return self.parse_chunks(chunks)



