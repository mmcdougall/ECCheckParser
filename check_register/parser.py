# -*- coding: utf-8 -*-
"""
Core logic for extracting "Monthly Disbursement and Check Register" entries from City of El Cerrito Agenda Packet PDFs.
"""

from __future__ import annotations

import re
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Tuple

import pdfplumber

from payee_splitter import split_payee_desc_block
from payee_splitter.cluster import infer_description_column_x0, split_payee_desc_by_x
from register_format import AMOUNT_RE, ROW_START_RE, split_row_header
from .models import CheckEntry, RowChunk, PositionedWord


@dataclass
class _ExtractState:
    """Current reporting section and payment row awaiting continuation lines."""

    month: Optional[int] = None
    year: Optional[int] = None
    mode: Optional[str] = None  # "check" or "eft"
    lines: List[str] = field(default_factory=list)
    words: List[List[PositionedWord]] = field(default_factory=list)
    metadata_x0: Optional[float] = None
    payload_x0: Optional[float] = None


# ------------------------------
# Parser
# ------------------------------
class CheckRegisterParser:
    # Match the single line that contains both From/To dates.
    # Example: "From Payment Date: 6/1/2025 - To Payment Date: 6/30/2025"
    _block_hdr = re.compile(
        r"^From Payment Date:?\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*-\s*To Payment Date:?\s*(\d{1,2})/(\d{1,2})/(\d{4})$",
        re.IGNORECASE
    )

    # Subsection headings can vary slightly in punctuation/spacing
    _checks_hdr = re.compile(r"^(?:Accounts Payable\s*-?\s*)?Checks?$", re.IGNORECASE)
    _efts_hdr   = re.compile(r"^(?:Accounts Payable\s*-?\s*)?EFT'?s?$", re.IGNORECASE)

    _row_start = ROW_START_RE

    # Lines containing a VOID marker anywhere
    _void_marker = re.compile(r"\bVOID(?:ED|ED/REISSUED)?\b", re.IGNORECASE)

    # Amount is last token (with optional minus) like $12,345.67 or 12,345.67
    _amount_tail = AMOUNT_RE

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
        if "." in s or len(s) <= 2:
            return Decimal(s)
        return Decimal(s) / Decimal(100)

    @staticmethod
    def _split_payee_desc_block(block: str) -> Tuple[str, str]:
        return split_payee_desc_block(block)

    @staticmethod
    def _positioned_line(words: List[dict]) -> List[PositionedWord]:
        return [
            PositionedWord(text=word["text"], x0=word["x0"])
            for word in sorted(words, key=lambda word: word["x0"])
        ]

    def _words_by_line(self, page) -> List[List[PositionedWord]]:
        """Group words sharing more than half their height into reading lines.

        Font-specific word extraction separates overlapping text layers. Row
        grouping scales with the font height to include offset descriptions.
        """
        words = sorted(
            page.extract_words(y_tolerance=1, extra_attrs=["fontname"]),
            key=lambda word: word["top"],
        )
        lines: List[List[PositionedWord]] = []
        current: List[dict] = []
        line_top = line_height = 0.0
        for word in words:
            height = word["bottom"] - word["top"]
            tolerance = min(line_height, height) / 2
            if current and word["top"] - line_top >= tolerance:
                lines.append(self._positioned_line(current))
                current = []
            if not current:
                line_top = word["top"]
                line_height = height
            current.append(word)
        if current:
            lines.append(self._positioned_line(current))
        return lines

    @staticmethod
    def _flush_chunk(state: _ExtractState) -> List[RowChunk]:
        if not state.lines:
            return []
        chunk = RowChunk(
            state.month, state.year, state.mode or "check", state.lines, state.words
        )
        state.lines = []
        state.words = []
        state.metadata_x0 = None
        state.payload_x0 = None
        return [chunk]

    def _handle_line(
        self, line: str, wl: List[PositionedWord], state: _ExtractState
    ) -> List[RowChunk]:
        header = self._block_hdr.match(line)
        checks = self._checks_hdr.match(line)
        efts = self._efts_hdr.match(line)
        if header or checks or efts:
            chunks = self._flush_chunk(state)
            if header:
                month, year = int(header.group(4)), int(header.group(6))
                if (state.month, state.year) != (month, year):
                    state.mode = "check"
                state.month, state.year = month, year
            else:
                state.mode = "eft" if efts else "check"
            return chunks
        if not line or self._skip_line.match(line):
            return self._flush_chunk(state)
        if state.month is None or state.year is None:
            return []

        fields = split_row_header(line)
        if fields:
            chunks = self._flush_chunk(state)
            state.lines, state.words = [line], [wl]
            payload_length = len(fields[4].split())
            if wl and payload_length:
                state.metadata_x0 = wl[2].x0
                state.payload_x0 = wl[-payload_length].x0
            return chunks
        if state.lines and wl and state.metadata_x0 is not None:
            if all(word.x0 >= state.metadata_x0 - 1 for word in wl):
                payload = [word for word in wl if word.x0 >= state.payload_x0 - 1]
                if payload:
                    state.lines.append(" ".join(word.text for word in payload))
                    state.words.append(payload)
                return []
        return self._flush_chunk(state)

    # ---------- raw extraction ----------
    def extract_raw_chunks(
        self, page_range: Tuple[int, int] | None = None,
    ) -> List[RowChunk]:
        chunks: List[RowChunk] = []
        state = _ExtractState()
        if not self.pdf_path.is_file():
            raise FileNotFoundError(f"PDF not found: {self.pdf_path}")

        logging.getLogger("pdfminer").setLevel(logging.ERROR)
        with pdfplumber.open(self.pdf_path) as pdf:
            pages = pdf.pages
            if page_range is not None:
                start_page, end_page = page_range
                pages = pages[start_page - 1:end_page]
            for page in pages:
                for words in self._words_by_line(page):
                    line = " ".join(word.text for word in words)
                    chunks.extend(self._handle_line(line, words, state))
                chunks.extend(self._flush_chunk(state))

        return chunks

    # ---------- chunk parsing ----------
    def _parse_chunk(
        self,
        chunk: RowChunk,
        description_x0: Optional[float] = None,
    ) -> CheckEntry:
        first = chunk.lines[0]
        fields = split_row_header(first)
        if fields is None:
            raise ValueError(f"Chunk does not start with row pattern: {first}")

        number, date, status, source, rest = fields

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
            m_amt = self._amount_tail.search(line) if amount is None else None
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
                result = split_payee_desc_by_x(
                    self._chunk_word_lines(chunk), description_x0
                )
            if result:
                payee, desc = result
            else:
                payee, desc = self._split_payee_desc_block(block)

        if amount is None:
            logging.warning("Missing amount in row: %s", " | ".join(chunk.lines))
            amount = Decimal("0.00")

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
            amount=amount,
            voided=voided,
        )

    @staticmethod
    def _chunk_word_lines(chunk: RowChunk) -> List[List[PositionedWord]]:
        return [
            [PositionedWord(**word) if isinstance(word, dict) else word for word in line]
            for line in chunk.line_words
        ]

    def parse_chunks(self, chunks: List[RowChunk]) -> List[CheckEntry]:
        month_rows = defaultdict(list)
        for chunk in chunks:
            month_rows[(chunk.section_year, chunk.section_month)].append(
                self._chunk_word_lines(chunk)
            )
        columns = {
            month: infer_description_column_x0(rows)
            for month, rows in month_rows.items()
        }
        entries = [
            self._parse_chunk(c, columns[(c.section_year, c.section_month)])
            for c in chunks
        ]
        if not self.keep_voided:
            entries = [e for e in entries if not e.voided]
        return entries

    # ---------- main extraction ----------
    def extract(self, page_range: Tuple[int, int] | None = None) -> List[CheckEntry]:
        chunks = self.extract_raw_chunks(page_range=page_range)
        return self.parse_chunks(chunks)
