from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import pdfplumber
import pypdfium2 as pdfium

from .parser import CheckRegisterParser
from .models import CheckEntry


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


def default_pdf_name(
    entries: List[CheckEntry], archive_root: Path | None = Path("CheckRegisterArchive")
) -> Path:
    """Generate a default path for an extracted register PDF.

    The file name begins with ``YYYY-MM``. For registers spanning multiple
    months within the same year the ending month is appended with a dash
    (e.g. ``2025-06-07`` for a June/July register). Registers spanning
    different years receive a ``YYYY-MM-YYYY-MM`` prefix. A neutral
    ``-register.pdf`` suffix keeps filenames consistent. When ``archive_root``
    is provided the file is written under ``archive_root/<year>/`` similar to
    the Agenda Packet hierarchy; otherwise the file is placed in the current
    directory without creating subdirectories.
    """

    months = sorted({(e.section_year, e.section_month) for e in entries})
    if months:
        start_y, start_m = months[0]
        end_y, end_m = months[-1]
        if start_y == end_y and start_m == end_m:
            prefix = f"{start_y:04d}-{start_m:02d}"
        elif start_y == end_y:
            prefix = f"{start_y:04d}-{start_m:02d}-{end_m:02d}"
        else:
            prefix = f"{start_y:04d}-{start_m:02d}-{end_y:04d}-{end_m:02d}"
    else:
        prefix = "unknown"

    filename = Path(f"{prefix}-register.pdf")

    if archive_root is None:
        return filename

    if months:
        year_dir = archive_root / f"{start_y:04d}"
    else:
        year_dir = archive_root / "unknown"

    year_dir.mkdir(parents=True, exist_ok=True)
    return year_dir / filename
