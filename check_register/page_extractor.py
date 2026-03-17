from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

import pdfplumber
import pypdfium2 as pdfium

from .parser import CheckRegisterParser
from .models import CheckEntry


def _quiet_pdfminer() -> None:
    logging.getLogger("pdfminer").setLevel(logging.ERROR)


def find_check_register_page_ranges(pdf_path: Path) -> List[Tuple[int, int]]:
    """Locate contiguous check register page ranges within a packet."""
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    ranges: List[Tuple[int, int]] = []
    start_page = None
    end_page = None
    in_section = False

    _quiet_pdfminer()
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            lines = (page.extract_text() or "").splitlines()
            has_block = False
            has_rows = False
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if CheckRegisterParser._block_hdr.match(line):
                    has_block = True
                if (
                    CheckRegisterParser._row_start.match(line)
                    or CheckRegisterParser._skip_line.match(line)
                ):
                    has_rows = True
            page_has_register = has_block or has_rows
            if not in_section:
                if has_block:
                    start_page = i
                    end_page = i
                    in_section = True
            elif page_has_register:
                end_page = i
            elif in_section:
                ranges.append((start_page, end_page))
                start_page = None
                end_page = None
                in_section = False

    if in_section and start_page is not None and end_page is not None:
        ranges.append((start_page, end_page))
    if not ranges:
        raise ValueError("Check register pages not found")
    return ranges


def find_check_register_page_range(pdf_path: Path) -> Tuple[int, int]:
    """Locate the start and end pages of the check register within a packet.

    Raises
    ------
    ValueError
        If no check register page range can be determined.
    """
    ranges = find_check_register_page_ranges(pdf_path)
    if len(ranges) != 1:
        raise ValueError("Multiple disjoint check register sections found")
    return ranges[0]


def extract_check_register_pdf_range(
    pdf_path: Path, out_path: Path, start: int, end: int,
) -> Tuple[int, int]:
    """Extract an inclusive page range into a separate PDF."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    src = pdfium.PdfDocument(str(pdf_path))
    out_pdf = pdfium.PdfDocument.new()
    out_pdf.import_pages(src, pages=range(start - 1, end))
    out_pdf.save(str(out_path))
    return start, end


def extract_check_register_pdf(pdf_path: Path, out_path: Path) -> Tuple[int, int]:
    """Extract the check register pages into a separate PDF.

    Returns the 1-indexed (start_page, end_page) tuple.
    """
    start, end = find_check_register_page_range(pdf_path)
    return extract_check_register_pdf_range(pdf_path, out_path, start, end)


def register_name_prefix(entries: List[CheckEntry]) -> str | None:
    """Return a sortable ``YYYY-MM`` style prefix for output filenames.

    Prefixes start with the year and month so an alphanumeric directory
    listing orders files chronologically, which is often desirable.
    Multi-month or multi-year spans append additional ``-MM`` or
    ``-YYYY-MM`` segments.
    """

    months = sorted({(e.section_year, e.section_month) for e in entries})
    if not months:
        return None

    start_y, start_m = months[0]
    end_y, end_m = months[-1]
    if start_y == end_y and start_m == end_m:
        return f"{start_y:04d}-{start_m:02d}"
    if start_y == end_y:
        return f"{start_y:04d}-{start_m:02d}-{end_m:02d}"
    return f"{start_y:04d}-{start_m:02d}-{end_y:04d}-{end_m:02d}"


def default_pdf_name(entries: List[CheckEntry]) -> Path | None:
    """Generate a default filename for an extracted register PDF."""

    prefix = register_name_prefix(entries)
    return None if prefix is None else Path(f"{prefix}-register.pdf")
