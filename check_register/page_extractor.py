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
    """Locate check register page ranges, separating reporting months."""
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    ranges: List[Tuple[int, int]] = []
    section_month = None

    _quiet_pdfminer()
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            page_month, has_register = _register_page_info(page.extract_text() or "")
            if not has_register:
                section_month = None
                continue
            if page_month is not None:
                if page_month != section_month:
                    ranges.append((i, i))
                section_month = page_month
            if section_month is not None:
                ranges[-1] = (ranges[-1][0], i)

    if not ranges:
        raise ValueError("Check register pages not found")
    return ranges


def _register_page_info(text: str) -> tuple[tuple[int, int] | None, bool]:
    """Read the reporting month and continuation markers on a page."""
    month = None
    has_rows = False
    for line in text.splitlines():
        line = line.strip()
        header = CheckRegisterParser._block_hdr.match(line)
        if header:
            month = (int(header.group(6)), int(header.group(4)))
        if CheckRegisterParser._row_start.match(line) or CheckRegisterParser._skip_line.match(line):
            has_rows = True
    return month, month is not None or has_rows


def find_check_register_page_range(pdf_path: Path) -> Tuple[int, int]:
    """Find one contiguous register range, combining adjacent monthly sections.

    Raises
    ------
    ValueError
        If no register is found or its sections are separated by other pages.
    """
    ranges = find_check_register_page_ranges(pdf_path)
    if any(right[0] != left[1] + 1 for left, right in zip(ranges, ranges[1:])):
        raise ValueError("Multiple disjoint check register sections found")
    return ranges[0][0], ranges[-1][1]


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
