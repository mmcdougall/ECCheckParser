import tempfile
import unittest
from pathlib import Path

from project_paths import ORIGINALS_DIR

import pdfplumber
import pypdfium2 as pdfium

from check_register.page_extractor import extract_check_register_pdf
from check_register.parser import CheckRegisterParser


class TestPageExtractor(unittest.TestCase):
    def test_extract_range_august(self):
        src = ORIGINALS_DIR / '2025' / 'Agenda Packet (8.19.2025).pdf'
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / 'register.pdf'
            start, end = extract_check_register_pdf(src, out)
            self.assertEqual((start, end), (7, 21))
            with pdfplumber.open(out) as pdf:
                self.assertEqual(len(pdf.pages), 15)
                first_text = pdf.pages[0].extract_text() or ''
                lines = [ln.strip() for ln in first_text.splitlines()]
                self.assertTrue(
                    any(CheckRegisterParser._block_hdr.match(ln) for ln in lines),
                    "start page should contain payment date header",
                )

    def test_no_check_register(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            src = tmp / 'empty.pdf'
            doc = pdfium.PdfDocument.new()
            doc.new_page(1, 1)
            doc.save(str(src))
            out = tmp / 'register.pdf'
            with self.assertRaises(ValueError):
                extract_check_register_pdf(src, out)

    def test_extract_range_february(self):
        src = ORIGINALS_DIR / '2025' / 'Agenda Packet (rev. 3.18.2025).pdf'
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / 'register.pdf'
            start, end = extract_check_register_pdf(src, out)
            self.assertEqual((start, end), (9, 15))
            with pdfplumber.open(out) as pdf:
                self.assertEqual(len(pdf.pages), 7)

