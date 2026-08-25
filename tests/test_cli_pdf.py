import contextlib
import io
import os
import tempfile
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

import pypdfium2 as pdfium

from check_register.models import CheckEntry
from check_register.page_extractor import (
    default_pdf_name,
    find_check_register_page_ranges,
    register_name_prefix,
)
from check_register_parser import main


class TestCliPdf(unittest.TestCase):
    def _empty_pdf(self, path: Path) -> None:
        doc = pdfium.PdfDocument.new()
        doc.new_page(1, 1)
        doc.save(str(path))

    def test_default_pdf_name_multi_month(self):
        entries = [
            CheckEntry(6, 2025, "check", "", "", "", "", "", "", Decimal("0"), False),
            CheckEntry(7, 2025, "check", "", "", "", "", "", "", Decimal("0"), False),
        ]
        out = default_pdf_name(entries)
        self.assertEqual(out, Path("2025-06-07-register.pdf"))

    def test_register_name_prefix(self):
        entries = [
            CheckEntry(12, 2024, "check", "", "", "", "", "", "", Decimal("0"), False),
            CheckEntry(1, 2025, "check", "", "", "", "", "", "", Decimal("0"), False),
        ]
        self.assertEqual(register_name_prefix(entries), "2024-12-2025-01")

    def test_default_pdf_name_single_month(self):
        entries = [
            CheckEntry(6, 2025, "check", "", "", "", "", "", "", Decimal("0"), False)
        ]
        out = default_pdf_name(entries)
        self.assertEqual(out, Path("2025-06-register.pdf"))

    def test_default_pdf_name_empty(self):
        self.assertIsNone(default_pdf_name([]))

    def test_find_check_register_page_ranges_skips_agenda_pages(self):
        class FakePage:
            def __init__(self, text: str):
                self._text = text

            def extract_text(self):
                return self._text

        class FakePdf:
            def __init__(self, pages):
                self.pages = [FakePage(text) for text in pages]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        pages = [
            "\n".join(
                [
                    "City of El Cerrito",
                    "Payment Register",
                    "From Payment Date: 11/1/2025 - To Payment Date: 11/30/2025",
                    "94748 11/06/2025 Open Accounts Payable OLIVERO PLUMBING 1885.00",
                ]
            ),
            "\n".join(["94749 11/06/2025 Open Accounts Payable ACME SUPPLY 99.00"]),
            "\n".join(
                [
                    "Agenda Item No. 6.E.",
                    "Attachments:",
                    "1. Monthly Payment Register December 2025",
                ]
            ),
            "\n".join(
                [
                    "City of El Cerrito",
                    "Payment Register",
                    "From Payment Date: 12/1/2025 - To Payment Date: 12/31/2025",
                    "95041 12/11/2025 Open Accounts Payable CITY OF RICHMOND 72014.17",
                ]
            ),
        ]

        pdf_path = Path(tempfile.mkstemp(suffix=".pdf")[1])
        try:
            with patch("check_register.page_extractor.pdfplumber.open", return_value=FakePdf(pages)):
                ranges = find_check_register_page_ranges(pdf_path)
            self.assertEqual(ranges, [(1, 2), (4, 4)])
        finally:
            if pdf_path.exists():
                pdf_path.unlink()

    def test_multi_section_packet_writes_separate_outputs(self):
        pdf_path = Path(
            "data/originals/city-council/2026/agenda-packets/2026-01-20 Agenda Packet.pdf"
        ).resolve()
        with tempfile.TemporaryDirectory() as td:
            cwd = Path.cwd()
            try:
                os.chdir(td)
                argv = [
                    "check_register_parser.py",
                    str(pdf_path),
                    "--csv",
                    "--chunks-json",
                    "--pdf",
                ]
                with patch("sys.argv", argv):
                    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                        main()
                        output = buf.getvalue()
                td_path = Path(td)
                self.assertTrue((td_path / "2025-11.csv").exists())
                self.assertTrue((td_path / "2025-11-chunks.json").exists())
                self.assertTrue((td_path / "2025-11-register.pdf").exists())
                self.assertTrue((td_path / "2025-12.csv").exists())
                self.assertTrue((td_path / "2025-12-chunks.json").exists())
                self.assertTrue((td_path / "2025-12-register.pdf").exists())
                self.assertFalse((td_path / "2025-11-12.csv").exists())
                self.assertFalse((td_path / "2025-11-12-chunks.json").exists())
                self.assertFalse((td_path / "2025-11-12-register.pdf").exists())
            finally:
                os.chdir(cwd)

        self.assertIn("Section: 2025-11", output)
        self.assertIn("Section: 2025-12", output)
        self.assertIn("PDF: 2025-11-register.pdf (pages 70-76)", output)
        self.assertIn("PDF: 2025-12-register.pdf (pages 79-83)", output)

    def test_pdf_no_register_graceful(self):
        pdf_path = Path(tempfile.mkstemp(suffix=".pdf")[1])
        self._empty_pdf(pdf_path)
        argv = ["check_register_parser.py", str(pdf_path), "--pdf"]
        try:
            with patch("sys.argv", argv):
                with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                    with self.assertRaises(SystemExit) as cm:
                        main()
                    output = buf.getvalue()
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("No check register entries found", output)
        finally:
            if pdf_path.exists():
                pdf_path.unlink()


if __name__ == "__main__":
    unittest.main()
