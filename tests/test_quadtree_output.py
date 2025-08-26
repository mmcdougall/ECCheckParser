import unittest
from decimal import Decimal

from check_register.models import CheckEntry
from check_register.outputs import build_payee_quadtree_data, build_payee_quadtree_title


class TestPayeeQuadtreeData(unittest.TestCase):
    def test_multi_check_hover_fields(self):
        entries = [
            CheckEntry(6, 2025, "check", "1", "06/01/2025", "Open", "Accounts Payable", "Alpha", "foo", Decimal("100.00"), False),
            CheckEntry(6, 2025, "check", "2", "06/02/2025", "Open", "Accounts Payable", "Alpha", "bar", Decimal("50.00"), False),
            CheckEntry(6, 2025, "check", "3", "06/03/2025", "Open", "Accounts Payable", "Beta", "baz", Decimal("1000.00"), False),
        ]
        data = build_payee_quadtree_data(entries)
        alpha_idx = data["payee"].index("Alpha")
        self.assertIn("foo", data["description"][alpha_idx])
        self.assertIn("bar", data["description"][alpha_idx])
        self.assertIn("1: $100.00", data["checks"][alpha_idx])
        self.assertIn("2: $50.00", data["checks"][alpha_idx])
        beta_idx = data["payee"].index("Beta")
        self.assertIn("3: $1,000.00", data["checks"][beta_idx])

    def test_label_fits_single_payee(self):
        entries = [
            CheckEntry(6, 2025, "check", "1", "06/01/2025", "Open", "Accounts Payable", "Alpha Co", "desc", Decimal("100.00"), False)
        ]
        data = build_payee_quadtree_data(entries)
        self.assertEqual(data["label"][0], "Alpha Co")

    def test_drop_top_payees(self):
        entries = [
            CheckEntry(6, 2025, "check", "1", "06/01/2025", "Open", "Accounts Payable", "CalPERS", "a", Decimal("100.00"), False),
            CheckEntry(6, 2025, "check", "2", "06/02/2025", "Open", "Accounts Payable", "Alpha", "b", Decimal("60.00"), False),
            CheckEntry(6, 2025, "check", "3", "06/03/2025", "Open", "Accounts Payable", "Beta", "c", Decimal("50.00"), False),
        ]
        data = build_payee_quadtree_data(entries, drop=1)
        self.assertNotIn("CalPERS", data["payee"])
        self.assertCountEqual(sorted(data["payee"]), ["Alpha", "Beta"])

    def test_title_with_drop(self):
        entries = [
            CheckEntry(6, 2025, "check", "1", "06/01/2025", "Open", "Accounts Payable", "A", "a", Decimal("500.00"), False),
            CheckEntry(6, 2025, "check", "2", "06/02/2025", "Open", "Accounts Payable", "B", "b", Decimal("450.00"), False),
            CheckEntry(6, 2025, "check", "3", "06/03/2025", "Open", "Accounts Payable", "C", "c", Decimal("100.00"), False),
            CheckEntry(6, 2025, "check", "4", "06/04/2025", "Open", "Accounts Payable", "D", "d", Decimal("90.00"), False),
            CheckEntry(6, 2025, "check", "5", "06/05/2025", "Open", "Accounts Payable", "E", "e", Decimal("10.00"), False),
        ]
        data = build_payee_quadtree_data(entries, drop=3)
        title = build_payee_quadtree_title(entries, data, drop=3)
        self.assertEqual(
            title,
            "June 2025 Checks/EFT Report: $1,150.00 ($100.00 shown, top 3 payees excluded)",
        )

    def test_title_no_drop_multi_month(self):
        entries = [
            CheckEntry(6, 2025, "check", "1", "06/01/2025", "Open", "Accounts Payable", "Alpha", "a", Decimal("50.00"), False),
            CheckEntry(7, 2025, "check", "2", "07/01/2025", "Open", "Accounts Payable", "Beta", "b", Decimal("75.00"), False),
        ]
        data = build_payee_quadtree_data(entries)
        title = build_payee_quadtree_title(entries, data)
        self.assertEqual(title, "June–July 2025 Checks/EFT Report: $125.00")


if __name__ == "__main__":
    unittest.main()
