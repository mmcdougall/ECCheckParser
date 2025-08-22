from __future__ import annotations

from pathlib import Path
from typing import Tuple

import pdfplumber
import pypdfium2 as pdfium

from .parser import CheckRegisterParser


def find_check_register_page_range(pdf_path: Path) -> Tuple[int | None, int | None]:
    """Locate the start and end pages of the check register within a packet."""
    start_page = None
    end_page = None
    in_section = False

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            lines = (page.extract_text() or "").splitlines()
            has_block = False
            page_has_data = False
            has_section_hdr = False
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if CheckRegisterParser._block_hdr.match(line):
                    has_block = True
                if (
                    CheckRegisterParser._checks_hdr.match(line)
                    or CheckRegisterParser._efts_hdr.match(line)
                    or "CHECK REGISTER" in line.upper()
                ):
                    has_section_hdr = True
                    page_has_data = True
                elif in_section and (
                    CheckRegisterParser._row_start.match(line)
                    or CheckRegisterParser._skip_line.match(line)
                ):
                    page_has_data = True
            if start_page is None:
                if has_block and has_section_hdr:
                    start_page = i
                    end_page = i
                    in_section = True
            elif in_section:
                if page_has_data:
                    end_page = i
                else:
                    break
    return start_page, end_page


def extract_check_register_pdf(pdf_path: Path, out_path: Path) -> Tuple[int, int]:
    """Extract the check register pages into a separate PDF.

    Returns the 1-indexed (start_page, end_page) tuple.
    """
    start, end = find_check_register_page_range(pdf_path)
    if start is None or end is None:
        raise ValueError("Check register pages not found")

    src = pdfium.PdfDocument(str(pdf_path))
    out_pdf = pdfium.PdfDocument.new()
    out_pdf.import_pages(src, pages=range(start - 1, end))
    out_pdf.save(str(out_path))
    return start, end
