from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

_FUND_UPDATE_PATTERN = re.compile(r"GENERAL\s+FUND(?:\s+\w+){0,3}\s+UPDATE", re.IGNORECASE)
_CASH_INVESTMENT_PATTERN = re.compile(
    r"(?:FIRST|SECOND|THIRD|FOURTH|Q[1-4]|QUARTERLY)"
    r"(?:\s+QUARTER)?\s+CASH\s+(?:AND|&)\s+INVESTMENT\s+REPORT",
    re.IGNORECASE,
)
_PAGE_COUNT_PATTERN = re.compile(
    r"Page\s+(?P<current>\d{1,2})\s+of\s+(?P<total>\d{1,2})", re.IGNORECASE
)
_DATE_PATTERN = re.compile(
    r"\((?:rev\.?\s*)?(?P<month>\d{1,2})\.(?P<day>\d{1,2})\.(?P<year>\d{2,4})\)",
    re.IGNORECASE,
)
_CANONICAL_DATE_PATTERN = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})(?:\s+\d{4})?\s+Agenda Packet",
    re.IGNORECASE,
)


class QuarterlyReportKind(str, Enum):
    GENERAL_FUND_UPDATE = "general-fund-update"
    CASH_INVESTMENT_REPORT = "cash-investment-report"


@dataclass(frozen=True)
class QuarterlyReport:
    kind: QuarterlyReportKind
    pages: List[int]


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _pdf_page_texts(pdf_path: Path) -> List[str]:
    doc = pdfium.PdfDocument(str(pdf_path))
    normalized_pages: List[str] = []
    try:
        for page_number in range(len(doc)):
            page = doc.get_page(page_number)
            text_page = page.get_textpage()
            normalized_pages.append(_normalize(text_page.get_text_range() or ""))
            text_page.close()
            page.close()
    finally:
        doc.close()
    return normalized_pages


def _anchor_page_count(text: str) -> int | None:
    match = _PAGE_COUNT_PATTERN.search(text)
    if not match:
        return None
    if int(match.group("current")) != 1:
        return None
    if not _FUND_UPDATE_PATTERN.search(text):
        return None
    return int(match.group("total"))


def _is_preface_page(text: str) -> bool:
    lowered = text.lower()
    if "general fund" not in lowered or "update" not in lowered:
        return False
    return "agenda bill" in lowered or "agenda item" in lowered


def _fund_update_pages(
    normalized_pages: List[str],
    anchor_index: int,
    anchor_total: int,
    total_pages: int,
) -> List[int]:
    pages = set(range(anchor_index, min(anchor_index + anchor_total, total_pages + 1)))
    previous = anchor_index - 1
    while previous >= 1:
        if not _is_preface_page(normalized_pages[previous - 1]):
            break
        pages.add(previous)
        previous -= 1
    return sorted(pages)


def _validate_fund_update_pages(
    pages: List[int],
    normalized_pages: List[str],
    anchor_index: int,
    anchor_total: int,
) -> None:
    if pages != list(range(pages[0], pages[-1] + 1)):
        raise ValueError("General Fund Budget Update pages are not contiguous")
    if pages[0] == anchor_index:
        raise ValueError("General Fund Budget Update agenda bill pages not found")

    preface_pages = pages[: pages.index(anchor_index)]
    if not all(_is_preface_page(normalized_pages[page - 1]) for page in preface_pages):
        raise ValueError("General Fund Budget Update preface pages failed validation")

    report_pages = pages[pages.index(anchor_index):]
    if len(report_pages) != anchor_total:
        raise ValueError("General Fund Budget Update page count mismatch")


def _find_fund_update_report(normalized_pages: List[str]) -> QuarterlyReport | None:
    total_pages = len(normalized_pages)
    for index, text in enumerate(normalized_pages, start=1):
        count = _anchor_page_count(text)
        if count is None:
            continue
        pages = _fund_update_pages(normalized_pages, index, count, total_pages)
        _validate_fund_update_pages(pages, normalized_pages, index, count)
        return QuarterlyReport(QuarterlyReportKind.GENERAL_FUND_UPDATE, pages)
    return None


def _is_cash_investment_preface(text: str) -> bool:
    lowered = text.lower()
    if not _CASH_INVESTMENT_PATTERN.search(text):
        return False
    return "agenda bill" in lowered or "agenda item" in lowered


def _is_cash_investment_attachment(text: str) -> bool:
    lowered = text.lower()
    if not _CASH_INVESTMENT_PATTERN.search(text):
        return False
    return any(
        anchor in lowered
        for anchor in ("quarter ending", "total cash and investments", "trustee/broker")
    )


def _find_cash_investment_report(normalized_pages: List[str]) -> QuarterlyReport | None:
    for start, text in enumerate(normalized_pages):
        if "agenda bill" not in text.lower() or not _is_cash_investment_preface(text):
            continue

        pages: List[int] = []
        has_attachment = False
        for index in range(start, len(normalized_pages)):
            candidate = normalized_pages[index]
            if _is_cash_investment_preface(candidate):
                pages.append(index + 1)
                continue
            if _is_cash_investment_attachment(candidate):
                pages.append(index + 1)
                has_attachment = True
                continue
            break

        if has_attachment:
            return QuarterlyReport(QuarterlyReportKind.CASH_INVESTMENT_REPORT, pages)
    return None


def find_quarterly_report(pdf_path: Path) -> QuarterlyReport:
    """Return the report family and 1-indexed pages for a quarterly report."""

    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    normalized_pages = _pdf_page_texts(pdf_path)
    report = _find_fund_update_report(normalized_pages)
    if report is not None:
        return report

    report = _find_cash_investment_report(normalized_pages)
    if report is not None:
        return report

    raise ValueError("quarterly financial report pages not found")


def find_fund_update_pages(pdf_path: Path) -> List[int]:
    """Return the 1-indexed pages containing the General Fund Budget Update."""

    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    report = _find_fund_update_report(_pdf_page_texts(pdf_path))
    if report is not None:
        return report.pages
    raise ValueError("General Fund Budget Update pages not found")


def _remove_page_annotations(doc: pdfium.PdfDocument) -> None:
    for page_index in range(len(doc)):
        page = doc.get_page(page_index)
        count = pdfium_c.FPDFPage_GetAnnotCount(page)
        for annotation_index in reversed(range(count)):
            if not pdfium_c.FPDFPage_RemoveAnnot(page, annotation_index):
                page.close()
                raise ValueError(f"Unable to remove annotation from page {page_index + 1}")
        page.close()


def _extract_pages(pdf_path: Path, out_path: Path, pages: List[int]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    src = pdfium.PdfDocument(str(pdf_path))
    out_pdf = pdfium.PdfDocument.new()
    try:
        out_pdf.import_pages(src, pages=[page - 1 for page in pages])
        _remove_page_annotations(out_pdf)
        out_pdf.save(str(out_path))
    finally:
        src.close()
        out_pdf.close()


def extract_quarterly_report_pdf(
    pdf_path: Path,
    out_path: Path,
    report: QuarterlyReport | None = None,
) -> QuarterlyReport:
    """Extract a detected quarterly financial report into a standalone PDF."""

    report = report or find_quarterly_report(pdf_path)
    _extract_pages(pdf_path, out_path, report.pages)
    return report


def extract_fund_update_pdf(pdf_path: Path, out_path: Path) -> List[int]:
    """Extract the General Fund Budget Update pages into a standalone PDF."""

    pages = find_fund_update_pages(pdf_path)
    _extract_pages(pdf_path, out_path, pages)
    return pages


def _packet_date(pdf_path: Path) -> tuple[int, int, int] | None:
    match = _CANONICAL_DATE_PATTERN.search(pdf_path.name) or _DATE_PATTERN.search(pdf_path.name)
    if not match:
        return None
    month = int(match.group("month"))
    day = int(match.group("day"))
    year_text = match.group("year")
    year = int(year_text)
    if len(year_text) == 2:
        year += 2000
    return year, month, day


def default_quarterly_report_pdf_name(
    pdf_path: Path,
    kind: QuarterlyReportKind,
) -> Path | None:
    """Return a dated artifact name for the detected quarterly report family."""

    packet_date = _packet_date(pdf_path)
    if packet_date is None:
        return None
    year, month, day = packet_date
    return Path(f"{year:04d}-{month:02d}-{day:02d}-{kind.value}.pdf")


def default_fund_update_pdf_name(pdf_path: Path) -> Path | None:
    """Return ``YYYY-MM-DD-general-fund-update.pdf`` derived from the packet name."""

    return default_quarterly_report_pdf_name(
        pdf_path,
        QuarterlyReportKind.GENERAL_FUND_UPDATE,
    )
