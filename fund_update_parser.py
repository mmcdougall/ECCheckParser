#!/usr/bin/env python3
"""CLI for extracting General Fund Budget Update pages from agenda packets."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from fund_update.page_extractor import (
    default_fund_update_pdf_name,
    extract_fund_update_pdf,
)
from project_paths import ARTIFACT_FUND_UPDATES_DIR


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Extract General Fund Budget Update pages from an agenda packet into a standalone PDF.",
    )
    ap.add_argument("pdf", type=Path, help="Agenda Packet PDF path")
    ap.add_argument("--out", type=Path, default=None, help="Explicit output PDF path")
    ap.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACT_FUND_UPDATES_DIR,
        help="Directory for artifact output when --out is not provided",
    )
    return ap.parse_args(list(argv) if argv is not None else None)


def derive_output_path(args: argparse.Namespace) -> Path:
    if args.out:
        return args.out

    default_name = default_fund_update_pdf_name(args.pdf)
    if default_name is None:
        raise SystemExit("Unable to derive default output filename; specify --out")
    return args.artifact_dir / default_name


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.pdf.exists():
        raise SystemExit(f"PDF not found: {args.pdf}")

    out_path = derive_output_path(args)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        pages = extract_fund_update_pdf(args.pdf, out_path)
    except ValueError as exc:
        raise SystemExit(f"No General Fund Budget Update pages found: {exc}") from exc

    page_list = ", ".join(str(page) for page in pages)
    print(f"PDF: {out_path} (pages {page_list})")


if __name__ == "__main__":
    main()
