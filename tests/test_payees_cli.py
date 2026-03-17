import contextlib
import io
import os
import tempfile
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

from check_register.models import CheckEntry
from check_register_parser import ParsedSection, main


class TestPayeesCli(unittest.TestCase):
    def _entries(self):
        return [
            CheckEntry(6, 2025, "check", "1", "", "", "", "Alpha", "", Decimal("100"), False),
            CheckEntry(6, 2025, "check", "2", "", "", "", "Beta", "", Decimal("200"), False),
        ]

    def test_payees_default_path(self):
        entries = self._entries()
        with tempfile.TemporaryDirectory() as td:
            argv = ["check_register_parser.py", "in.pdf", "--payees"]
            sections = [ParsedSection(page_range=(1, 1), chunks=[], entries=entries)]
            with patch("check_register_parser.parse_sections", return_value=sections), \
                 patch("sys.argv", argv):
                cwd = os.getcwd()
                os.chdir(td)
                try:
                    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                        main()
                        out = buf.getvalue()
                finally:
                    os.chdir(cwd)
            payee_file = Path(td, "2025-06-payees.txt")
            self.assertTrue(payee_file.exists())
            self.assertEqual(payee_file.read_text().splitlines(), ["Alpha", "Beta"])
            self.assertIn("Payees: 2", out)

    def test_payees_existing_file(self):
        entries = [
            CheckEntry(6, 2025, "check", "1", "", "", "", "Alpha", "", Decimal("50"), False),
            CheckEntry(6, 2025, "check", "2", "", "", "", "Beta", "", Decimal("50"), False),
            CheckEntry(6, 2025, "check", "3", "", "", "", "Gamma", "", Decimal("100"), False),
        ]
        with tempfile.TemporaryDirectory() as td:
            existing = Path(td, "existing.txt")
            existing.write_text("Alpha\n", encoding="utf-8")
            argv = ["check_register_parser.py", "in.pdf", "--payees", str(existing)]
            sections = [ParsedSection(page_range=(1, 1), chunks=[], entries=entries)]
            with patch("check_register_parser.parse_sections", return_value=sections), \
                 patch("sys.argv", argv):
                cwd = os.getcwd()
                os.chdir(td)
                try:
                    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                        main()
                        out = buf.getvalue()
                finally:
                    os.chdir(cwd)
            self.assertEqual(existing.read_text().splitlines(), ["Alpha", "Beta", "Gamma"])
            self.assertIn("Added 2 new payees", out)
            self.assertIn("Beta (25.00%)", out)
            self.assertIn("Gamma (50.00%)", out)


if __name__ == "__main__":
    unittest.main()
