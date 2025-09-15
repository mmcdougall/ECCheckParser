from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pdfplumber
import pypdfium2 as pdfium

_FUND_UPDATE_PATTERN = re.compile(r"GENERAL\s+FUND\s+BUDGET\s+UPDATE", re.IGNORECASE)
_DATE_PATTERN = re.compile(
    r"\((?:rev\.\s*)?(?P<month>\d{1,2})\.(?P<day>\d{1,2})\.(?P<year>\d{4})\)",
    re.IGNORECASE,
)


def _page_contains_update(text: str) -> bool:
    normalized = " ".join(text.split())
    return bool(_FUND_UPDATE_PATTERN.search(normalized))


def find_fund_update_pages(pdf_path: Path) -> List[int]:
    """Return the 1-indexed pages containing the General Fund Budget Update."""

    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    matches: List[int] = []
    with pdfplumber.open(pdf_path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if _page_contains_update(text):
                matches.append(index)
    if not matches:
        raise ValueError("General Fund Budget Update pages not found")
    return matches


def extract_fund_update_pdf(pdf_path: Path, out_path: Path) -> List[int]:
    """Extract the General Fund Budget Update pages into a standalone PDF."""

    pages = find_fund_update_pages(pdf_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    src = pdfium.PdfDocument(str(pdf_path))
    out_pdf = pdfium.PdfDocument.new()
    out_pdf.import_pages(src, pages=[page - 1 for page in pages])
    out_pdf.save(str(out_path))
    return pages


def default_fund_update_pdf_name(pdf_path: Path) -> Path | None:
    """Return ``YYYY-MM-DD-general-fund-update.pdf`` derived from the packet name."""

    match = _DATE_PATTERN.search(pdf_path.name)
    if not match:
        return None
    month = int(match.group("month"))
    day = int(match.group("day"))
    year = int(match.group("year"))
    return Path(f"{year:04d}-{month:02d}-{day:02d}-general-fund-update.pdf")
