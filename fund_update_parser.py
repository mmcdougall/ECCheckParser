#!/usr/bin/env python3
"""CLI for extracting quarterly financial reports from agenda packets."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from fund_update.page_extractor import (
    QuarterlyReport,
    QuarterlyReportKind,
    default_quarterly_report_pdf_name,
    extract_quarterly_report_pdf,
    find_quarterly_report,
)
from project_paths import ARTIFACT_CASH_INVESTMENTS_DIR, ARTIFACT_FUND_UPDATES_DIR


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Extract a quarterly financial report from an agenda packet into a standalone PDF.",
    )
    ap.add_argument("pdf", type=Path, help="Agenda Packet PDF path")
    ap.add_argument("--out", type=Path, default=None, help="Explicit output PDF path")
    ap.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Override the report-specific artifact directory",
    )
    return ap.parse_args(list(argv) if argv is not None else None)


def _default_artifact_dir(kind: QuarterlyReportKind) -> Path:
    if kind == QuarterlyReportKind.CASH_INVESTMENT_REPORT:
        return ARTIFACT_CASH_INVESTMENTS_DIR
    return ARTIFACT_FUND_UPDATES_DIR


def derive_output_path(args: argparse.Namespace, report: QuarterlyReport) -> Path:
    if args.out:
        return args.out

    default_name = default_quarterly_report_pdf_name(args.pdf, report.kind)
    if default_name is None:
        raise SystemExit("Unable to derive default output filename; specify --out")
    artifact_dir = args.artifact_dir or _default_artifact_dir(report.kind)
    return artifact_dir / default_name


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.pdf.exists():
        raise SystemExit(f"PDF not found: {args.pdf}")

    try:
        report = find_quarterly_report(args.pdf)
    except ValueError as exc:
        raise SystemExit(f"No quarterly financial report pages found: {exc}") from exc

    out_path = derive_output_path(args, report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    extract_quarterly_report_pdf(args.pdf, out_path, report)

    page_list = ", ".join(str(page) for page in report.pages)
    print(f"PDF: {out_path} ({report.kind.value}; pages {page_list})")


if __name__ == "__main__":
    main()
