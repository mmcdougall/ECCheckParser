#!/usr/bin/env python3
"""Generate archived register artifacts from an agenda packet PDF.

Given an agenda packet, this script extracts the check register pages,
parses them, and writes the resulting register PDF, CSV, and raw chunk
JSON under ``CheckRegisterArchive/<year>``.

Example:
    python scripts/build_register_archive.py ECPackets/2025/"Agenda Packet (6.24.2025).pdf"
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from check_register import CheckRegisterParser, write_csv, write_chunks
from check_register.page_extractor import extract_check_register_pdf, default_pdf_name


def build_from_packet(packet_pdf: Path, archive_root: Path) -> Path:
    packet_pdf = Path(packet_pdf)
    archive_root = Path(archive_root)
    archive_root.mkdir(parents=True, exist_ok=True)

    temp_pdf = archive_root / "_tmp_register.pdf"
    extract_check_register_pdf(packet_pdf, temp_pdf)

    parser = CheckRegisterParser(temp_pdf)
    chunks = parser.extract_raw_chunks()
    entries = parser.parse_chunks(chunks)

    out_name = default_pdf_name(entries) or temp_pdf.name
    year = entries[0].section_year if entries else 0
    year_dir = archive_root / f"{year}"
    year_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = year_dir / out_name
    temp_pdf.rename(pdf_path)

    stem = pdf_path.stem
    write_csv(entries, year_dir / f"{stem}.csv")
    write_chunks(chunks, year_dir / f"{stem}.chunks.json")
    return pdf_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract and archive register artifacts from an agenda packet PDF")
    ap.add_argument("packet_pdf", type=Path, help="Agenda packet PDF path")
    ap.add_argument("--archive-root", type=Path, default=Path("CheckRegisterArchive"), help="Archive root directory")
    args = ap.parse_args()

    out_pdf = build_from_packet(args.packet_pdf, args.archive_root)
    print(f"Artifacts written under {out_pdf.parent}")


if __name__ == "__main__":
    main()
