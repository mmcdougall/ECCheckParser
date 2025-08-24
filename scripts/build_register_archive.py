#!/usr/bin/env python3
"""Generate archive artifacts for a single agenda packet PDF.

Given an agenda packet PDF containing a "Monthly Disbursement and Check
Register" section, this script extracts the register pages, parses them,
and writes the resulting register PDF, raw row chunks JSON, and CSV entries
under ``CheckRegisterArchive``.

Example
-------
    python scripts/build_register_archive.py ECPackets/2025/"Agenda Packet (8.19.2025).pdf"
"""
from __future__ import annotations

import argparse
from pathlib import Path
import tempfile

import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from check_register import CheckRegisterParser, write_csv, write_chunks
from check_register.page_extractor import extract_check_register_pdf, default_pdf_name


def build_archive(packet_pdf: Path, archive_dir: Path = Path("CheckRegisterArchive")) -> Path:
    packet_pdf = Path(packet_pdf)
    archive_dir = Path(archive_dir)

    archive_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_pdf = Path(tmpdir) / "register.pdf"
        extract_check_register_pdf(packet_pdf, tmp_pdf)

        parser = CheckRegisterParser(tmp_pdf)
        chunks = parser.extract_raw_chunks()
        entries = parser.parse_chunks(chunks)

        name = default_pdf_name(entries)
        if name is None:
            raise RuntimeError("Could not determine default register PDF name")
        year_dir = archive_dir / str(entries[0].section_year)
        year_dir.mkdir(parents=True, exist_ok=True)

        pdf_out = year_dir / name
        tmp_pdf.replace(pdf_out)

        prefix = name.stem.replace("-register", "")
        chunk_out = year_dir / "chunks" / f"{prefix}.json"
        csv_out = year_dir / "csv" / f"{prefix}.csv"
        write_chunks(chunks, chunk_out)
        write_csv(entries, csv_out)

        return pdf_out


def main() -> None:
    ap = argparse.ArgumentParser(description="Archive check register artifacts from an agenda packet PDF")
    ap.add_argument("pdf", type=Path, help="Agenda packet PDF path")
    ap.add_argument("--archive-dir", type=Path, default=Path("CheckRegisterArchive"), help="Archive output directory")
    args = ap.parse_args()

    pdf_out = build_archive(args.pdf, args.archive_dir)
    print(f"Archive updated: {pdf_out}")


if __name__ == "__main__":
    main()
