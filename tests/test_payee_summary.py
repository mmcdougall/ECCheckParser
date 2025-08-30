import tempfile
from decimal import Decimal
from pathlib import Path
import unittest

from check_register.models import CheckEntry
from check_register.payees import update_payees, payee_summary


class TestPayeeSummary(unittest.TestCase):
    def test_default(self):
        entries = [
            CheckEntry(6, 2025, "check", "1", "", "", "", "Alpha", "", Decimal("100"), False),
            CheckEntry(6, 2025, "check", "2", "", "", "", "Beta", "", Decimal("200"), False),
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td, "payees.txt")
            info = update_payees(entries, path)
            lines = payee_summary(entries, path, info, default=True)
            self.assertEqual(path.read_text().splitlines(), ["Alpha", "Beta"])
            self.assertEqual(lines, [f"Payees: 2 (written to {path})"])

    def test_update(self):
        entries = [
            CheckEntry(6, 2025, "check", "1", "", "", "", "Alpha", "", Decimal("50"), False),
            CheckEntry(6, 2025, "check", "2", "", "", "", "Beta", "", Decimal("50"), False),
            CheckEntry(6, 2025, "check", "3", "", "", "", "Gamma", "", Decimal("100"), False),
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td, "existing.txt")
            path.write_text("Alpha\n", encoding="utf-8")
            info = update_payees(entries, path)
            lines = payee_summary(entries, path, info, default=False)
            self.assertEqual(path.read_text().splitlines(), ["Alpha", "Beta", "Gamma"])
            self.assertEqual(lines[0], f"Added 2 new payees to {path} (total 3)")
            self.assertIn("Beta (25.00%)", lines[1])
            self.assertIn("Gamma (50.00%)", lines[2])


if __name__ == "__main__":
    unittest.main()
