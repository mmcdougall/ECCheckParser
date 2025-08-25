import unittest
from decimal import Decimal

from check_register.models import CheckEntry
from check_register.outputs import build_payee_quadtree_data


class TestPayeeQuadtreeData(unittest.TestCase):
    def test_multi_check_hover_fields(self):
        entries = [
            CheckEntry(6, 2025, "check", "1", "06/01/2025", "Open", "Accounts Payable", "Alpha", "foo", Decimal("100.00"), False),
            CheckEntry(6, 2025, "check", "2", "06/02/2025", "Open", "Accounts Payable", "Alpha", "bar", Decimal("50.00"), False),
            CheckEntry(6, 2025, "check", "3", "06/03/2025", "Open", "Accounts Payable", "Beta", "baz", Decimal("10.00"), False),
        ]
        data = build_payee_quadtree_data(entries)
        alpha_idx = data["payee"].index("Alpha")
        self.assertIn("foo", data["description"][alpha_idx])
        self.assertIn("bar", data["description"][alpha_idx])
        self.assertIn("1: $100.00", data["checks"][alpha_idx])
        self.assertIn("2: $50.00", data["checks"][alpha_idx])
        beta_idx = data["payee"].index("Beta")
        self.assertEqual("", data["checks"][beta_idx])

    def test_label_fits_single_payee(self):
        entries = [
            CheckEntry(6, 2025, "check", "1", "06/01/2025", "Open", "Accounts Payable", "Alpha Co", "desc", Decimal("100.00"), False)
        ]
        data = build_payee_quadtree_data(entries)
        self.assertEqual(data["label"][0], "Alpha Co")


if __name__ == "__main__":
    unittest.main()
