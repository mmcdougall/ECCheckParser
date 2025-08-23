import tempfile
import unittest
from pathlib import Path

import pdfplumber

from check_register.page_extractor import extract_check_register_pdf, default_pdf_name
from check_register.parser import CheckRegisterParser


class TestPageExtractor(unittest.TestCase):
    def test_extract_range_august(self):
        src = Path('ECPackets/2025/Agenda Packet (8.19.2025).pdf')
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
        src = Path('ECPackets/2025/Agenda Packet (rev. 4.2.2025).pdf')
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / 'register.pdf'
            with self.assertRaises(ValueError):
                extract_check_register_pdf(src, out)

    def test_extract_range_february(self):
        src = Path('ECPackets/2025/Agenda Packet (rev. 3.18.2025).pdf')
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / 'register.pdf'
            start, end = extract_check_register_pdf(src, out)
            self.assertEqual((start, end), (9, 15))
            with pdfplumber.open(out) as pdf:
                self.assertEqual(len(pdf.pages), 7)

    def test_default_pdf_name_current_dir(self):
        parser = CheckRegisterParser(Path('ECPackets/2025/Agenda Packet (8.19.2025).pdf'))
        entries = parser.extract()
        name = default_pdf_name(entries, None)
        self.assertEqual(name, Path('2025-06-07-register.pdf'))

