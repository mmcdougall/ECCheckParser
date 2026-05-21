from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import re

import pypdfium2 as pdfium


Month = tuple[int, int]
Quarter = tuple[int, int]

_PAGE_COUNT_PATTERN = re.compile(
    r"Page\s+(?P<current>\d{1,2})\s+of\s+(?P<total>\d{1,2})", re.IGNORECASE
)
_FUND_UPDATE_PATTERN = re.compile(r"GENERAL\s+FUND(?:\s+\w+){0,3}\s+UPDATE", re.IGNORECASE)
_FISCAL_QUARTER_PATTERN = re.compile(
    r"\b(?:Quarter|Q)\s*(?P<quarter>[1-4])\b.*?\b(?:FY|Fiscal\s+Year)\s*"
    r"(?P<start>\d{4})\s*[-\u2013]\s*(?P<end>\d{2,4})",
    re.IGNORECASE,
)


@dataclass
class ArchiveAudit:
    csv_dir: Path
    fund_update_dir: Path
    csv_files: list[Path]
    fund_update_files: list[Path]
    covered_months: list[Month]
    covered_quarters: list[Quarter]
    missing_months: list[Month]
    missing_quarters: list[Quarter]
    problems: list[str]


def month_label(month: Month) -> str:
    year, month_number = month
    return f"{year:04d}-{month_number:02d}"


def quarter_label(quarter: Quarter) -> str:
    fiscal_year, quarter_number = quarter
    return f"FY {fiscal_year:04d}-{(fiscal_year + 1) % 100:02d} Q{quarter_number}"


def _next_month(month: Month) -> Month:
    year, month_number = month
    if month_number == 12:
        return year + 1, 1
    return year, month_number + 1


def _month_range(start: Month, end: Month) -> list[Month]:
    months: list[Month] = []
    current = start
    while current <= end:
        months.append(current)
        current = _next_month(current)
    return months


def _next_quarter(quarter: Quarter) -> Quarter:
    fiscal_year, quarter_number = quarter
    if quarter_number == 4:
        return fiscal_year + 1, 1
    return fiscal_year, quarter_number + 1


def _quarter_range(start: Quarter, end: Quarter) -> list[Quarter]:
    quarters: list[Quarter] = []
    current = start
    while current <= end:
        quarters.append(current)
        current = _next_quarter(current)
    return quarters


def _row_month(row: dict[str, str], path: Path, line_number: int) -> Month:
    try:
        month = int(row["section_month"])
        year = int(row["section_year"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"{path}:{line_number}: invalid section month/year") from exc
    if month < 1 or month > 12:
        raise ValueError(f"{path}:{line_number}: invalid section month {month}")
    return year, month


def _csv_months(path: Path) -> tuple[set[Month], list[str]]:
    months: set[Month] = set()
    problems: list[str] = []
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for line_number, row in enumerate(reader, start=2):
            try:
                months.add(_row_month(row, path, line_number))
            except ValueError as exc:
                problems.append(str(exc))
    if not months:
        problems.append(f"{path}: no check register rows found")
    return months, problems


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _pdf_page_texts(path: Path) -> list[str]:
    doc = pdfium.PdfDocument(str(path))
    texts: list[str] = []
    try:
        for page_index in range(len(doc)):
            page = doc.get_page(page_index)
            text_page = page.get_textpage()
            texts.append(_normalize(text_page.get_text_range() or ""))
            text_page.close()
            page.close()
    finally:
        doc.close()
    return texts


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


def _text_quarter(text: str) -> Quarter | None:
    match = _FISCAL_QUARTER_PATTERN.search(text)
    if not match:
        return None
    quarter = int(match.group("quarter"))
    fiscal_year = int(match.group("start"))
    return fiscal_year, quarter


def _fund_update_quarter(path: Path) -> tuple[Quarter | None, list[str]]:
    problems: list[str] = []
    texts = _pdf_page_texts(path)

    anchor_index: int | None = None
    anchor_total: int | None = None
    for index, text in enumerate(texts):
        count = _anchor_page_count(text)
        if count is not None:
            anchor_index = index
            anchor_total = count
            break

    if anchor_index is None or anchor_total is None:
        return None, [f"{path}: no fund update report anchor found"]

    if anchor_index == 0:
        problems.append(f"{path}: agenda bill wrapper missing")
    else:
        preface = texts[:anchor_index]
        if not all(_is_preface_page(text) for text in preface):
            problems.append(f"{path}: agenda bill wrapper failed validation")

    expected_pages = anchor_index + anchor_total
    if len(texts) != expected_pages:
        problems.append(
            f"{path}: expected {expected_pages} pages from report count, found {len(texts)}"
        )

    quarter = _text_quarter(texts[anchor_index])
    if quarter is None:
        problems.append(f"{path}: unable to identify fiscal quarter")

    return quarter, problems


def audit_register_archive(csv_dir: Path, fund_update_dir: Path) -> ArchiveAudit:
    csv_files = sorted(csv_dir.glob("*.csv"))
    fund_update_files = sorted(fund_update_dir.glob("*.pdf"))
    problems: list[str] = []
    covered: set[Month] = set()
    covered_quarters: set[Quarter] = set()

    for path in csv_files:
        months, file_problems = _csv_months(path)
        covered.update(months)
        problems.extend(file_problems)

    for path in fund_update_files:
        quarter, file_problems = _fund_update_quarter(path)
        if quarter is not None:
            covered_quarters.add(quarter)
        problems.extend(file_problems)

    covered_months = sorted(covered)
    expected = _month_range(covered_months[0], covered_months[-1]) if covered_months else []
    missing = [month for month in expected if month not in covered]
    quarters = sorted(covered_quarters)
    expected_quarters = _quarter_range(quarters[0], quarters[-1]) if quarters else []
    missing_quarters = [quarter for quarter in expected_quarters if quarter not in covered_quarters]

    if not csv_files:
        problems.append(f"No CSV artifacts found in {csv_dir}")
    if not fund_update_files:
        problems.append(f"No fund update artifacts found in {fund_update_dir}")

    return ArchiveAudit(
        csv_dir=csv_dir,
        fund_update_dir=fund_update_dir,
        csv_files=csv_files,
        fund_update_files=fund_update_files,
        covered_months=covered_months,
        covered_quarters=quarters,
        missing_months=missing,
        missing_quarters=missing_quarters,
        problems=problems,
    )


def format_archive_audit(audit: ArchiveAudit) -> list[str]:
    lines = [
        f"CSV artifacts: {len(audit.csv_files)} in {audit.csv_dir}",
    ]
    if audit.covered_months:
        first = month_label(audit.covered_months[0])
        last = month_label(audit.covered_months[-1])
        expected_count = len(audit.covered_months) + len(audit.missing_months)
        lines.append(
            f"Covered months: {first} through {last} "
            f"({len(audit.covered_months)} of {expected_count} expected)",
        )
    else:
        lines.append("Covered months: none")

    if audit.missing_months:
        lines.append("Missing check register months:")
        lines.extend(f"  {month_label(month)}" for month in audit.missing_months)
    else:
        lines.append("Missing check register months: none")

    lines.append(f"Fund update artifacts: {len(audit.fund_update_files)} in {audit.fund_update_dir}")
    if audit.covered_quarters:
        first = quarter_label(audit.covered_quarters[0])
        last = quarter_label(audit.covered_quarters[-1])
        expected_count = len(audit.covered_quarters) + len(audit.missing_quarters)
        lines.append(
            f"Covered fund update quarters: {first} through {last} "
            f"({len(audit.covered_quarters)} of {expected_count} expected)",
        )
    else:
        lines.append("Covered fund update quarters: none")

    if audit.missing_quarters:
        lines.append("Missing quarterly fund updates:")
        lines.extend(f"  {quarter_label(quarter)}" for quarter in audit.missing_quarters)
    else:
        lines.append("Missing quarterly fund updates: none")

    if audit.problems:
        lines.append("Artifact problems:")
        lines.extend(f"  {problem}" for problem in audit.problems)

    return lines
