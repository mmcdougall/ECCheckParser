# -*- coding: utf-8 -*-
"""
Core logic for extracting "Monthly Disbursement and Check Register" entries from City of El Cerrito Agenda Packet PDFs.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Tuple

import pdfplumber

from payee_splitter import split_payee_desc_block
from .models import CheckEntry, RowChunk, PositionedWord


@dataclass
class _ExtractState:
    month: Optional[int] = None
    year: Optional[int] = None
    mode: Optional[str] = None  # "check" or "eft"
    lines: List[str] = field(default_factory=list)
    words: List[List[PositionedWord]] = field(default_factory=list)


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

    def _words_by_line(self, page) -> List[List[PositionedWord]]:
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
                lines.append(
                    [
                        PositionedWord(text=pw["text"], x0=pw["x0"])
                        for pw in sorted(current, key=lambda x: x["x0"])
                    ]
                )
                current = [w]
                current_top = top
        if current:
            lines.append(
                [
                    PositionedWord(text=pw["text"], x0=pw["x0"])
                    for pw in sorted(current, key=lambda x: x["x0"])
                ]
            )
        return lines

    def _handle_line(
        self, line: str, wl: List[PositionedWord], state: _ExtractState
    ) -> List[RowChunk]:
        chunks: List[RowChunk] = []
        if not line or self._skip_line.match(line):
            return chunks

        b = self._block_hdr.match(line)
        if b:
            if state.lines:
                chunks.append(
                    RowChunk(state.month, state.year, state.mode or "check", state.lines, state.words)
                )
                state.lines = []
                state.words = []
            state.month = int(b.group(4))
            state.year = int(b.group(6))
            state.mode = "check"
            return chunks

        if self._checks_hdr.match(line):
            if state.lines:
                chunks.append(
                    RowChunk(state.month, state.year, state.mode or "check", state.lines, state.words)
                )
                state.lines = []
                state.words = []
            state.mode = "check"
            return chunks

        if self._efts_hdr.match(line):
            if state.lines:
                chunks.append(
                    RowChunk(state.month, state.year, state.mode or "check", state.lines, state.words)
                )
                state.lines = []
                state.words = []
            state.mode = "eft"
            return chunks

        if state.month is None or state.year is None:
            return chunks

        if self._row_start.match(line):
            if state.lines:
                chunks.append(
                    RowChunk(state.month, state.year, state.mode or "check", state.lines, state.words)
                )
            state.lines = [line]
            state.words = [wl]
            if self._amount_tail.search(line):
                chunks.append(
                    RowChunk(state.month, state.year, state.mode or "check", state.lines, state.words)
                )
                state.lines = []
                state.words = []
            return chunks

        if state.lines:
            state.lines.append(line)
            state.words.append(wl)
            if self._amount_tail.search(line):
                chunks.append(
                    RowChunk(state.month, state.year, state.mode or "check", state.lines, state.words)
                )
                state.lines = []
                state.words = []
        return chunks

    # ---------- raw extraction ----------
    def extract_raw_chunks(self) -> List[RowChunk]:
        chunks: List[RowChunk] = []
        state = _ExtractState()

        logging.getLogger("pdfminer").setLevel(logging.ERROR)
        with pdfplumber.open(self.pdf_path) as pdf:
            for page in pdf.pages:
                lines = (page.extract_text() or "").splitlines()
                word_lines = self._words_by_line(page)
                for idx, raw in enumerate(lines):
                    line = raw.rstrip()
                    wl = word_lines[idx] if idx < len(word_lines) else []
                    for chunk in self._handle_line(line, wl, state):
                        chunks.append(chunk)

        if state.lines:
            chunks.append(
                RowChunk(state.month, state.year, state.mode or "check", state.lines, state.words)
            )

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
            result = None
            if chunk.line_words:
                try:
                    from payee_splitter.cluster import split_payee_desc_by_x
                    from .models import PositionedWord

                    line_words = chunk.line_words
                    if line_words and isinstance(line_words[0][0], dict):
                        line_words = [
                            [PositionedWord(**w) for w in lw] for lw in line_words
                        ]
                    result = split_payee_desc_by_x(line_words)
                except Exception:
                    result = None
            if result:
                payee, desc = result
            else:
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



