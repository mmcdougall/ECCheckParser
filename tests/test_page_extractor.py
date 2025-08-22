import tempfile
import unittest
from pathlib import Path

import pdfplumber

from check_register.page_extractor import extract_check_register_pdf
from check_register.parser import CheckRegisterParser


class TestPageExtractor(unittest.TestCase):
    def test_extract_range(self):
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

