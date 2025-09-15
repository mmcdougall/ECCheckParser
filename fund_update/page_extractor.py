from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pypdfium2 as pdfium

_FUND_UPDATE_PATTERN = re.compile(r"GENERAL\s+FUND(?:\s+\w+){0,3}\s+UPDATE", re.IGNORECASE)
_PAGE_COUNT_PATTERN = re.compile(
    r"Page\s+(?P<current>\d{1,2})\s+of\s+(?P<total>\d{1,2})", re.IGNORECASE
)
_DATE_PATTERN = re.compile(
    r"\((?:rev\.?\s*)?(?P<month>\d{1,2})\.(?P<day>\d{1,2})\.(?P<year>\d{4})\)",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _anchor_page_count(text: str) -> int | None:
    match = _PAGE_COUNT_PATTERN.search(text)
    if not match:
        return None
    if int(match.group("current")) != 1:
        return None
    if not _FUND_UPDATE_PATTERN.search(text):
        return None
    return int(match.group("total"))


def find_fund_update_pages(pdf_path: Path) -> List[int]:
    """Return the 1-indexed pages containing the General Fund Budget Update."""

    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    doc = pdfium.PdfDocument(str(pdf_path))
    normalized_pages: List[str] = []
    anchor_index: int | None = None
    anchor_total: int | None = None

    try:
        total_pages = len(doc)
        for page_number in range(total_pages):
            page = doc.get_page(page_number)
            text_page = page.get_textpage()
            normalized = _normalize(text_page.get_text_range() or "")
            normalized_pages.append(normalized)
            text_page.close()
            page.close()

            if anchor_index is None:
                count = _anchor_page_count(normalized)
                if count is not None:
                    anchor_index = page_number + 1
                    anchor_total = count
                    break

        if anchor_index is not None and anchor_total is not None:
            pages = set(range(anchor_index, min(anchor_index + anchor_total, total_pages + 1)))
            previous = anchor_index - 1
            while previous >= 1:
                prev_text = normalized_pages[previous - 1].lower()
                if "general fund" not in prev_text or "update" not in prev_text:
                    break
                pages.add(previous)
                previous -= 1
            return sorted(pages)

        for page_number in range(len(normalized_pages), total_pages):
            page = doc.get_page(page_number)
            text_page = page.get_textpage()
            normalized_pages.append(_normalize(text_page.get_text_range() or ""))
            text_page.close()
            page.close()
    finally:
        doc.close()

    matches = [index + 1 for index, text in enumerate(normalized_pages) if _FUND_UPDATE_PATTERN.search(text)]
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
