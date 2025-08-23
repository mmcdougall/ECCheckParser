import contextlib
import io
import tempfile
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

import pypdfium2 as pdfium

from check_register.models import CheckEntry
from check_register.page_extractor import default_pdf_name
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

    def test_default_pdf_name_single_month(self):
        entries = [
            CheckEntry(6, 2025, "check", "", "", "", "", "", "", Decimal("0"), False)
        ]
        out = default_pdf_name(entries)
        self.assertEqual(out, Path("2025-06-register.pdf"))

    def test_default_pdf_name_empty(self):
        self.assertIsNone(default_pdf_name([]))

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

