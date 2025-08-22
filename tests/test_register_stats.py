import unittest
from decimal import Decimal

from check_register import CheckEntry, month_rollups, sanity


class TestRegisterStats(unittest.TestCase):
    def setUp(self):
        self.entries = [
            CheckEntry(6, 2025, "check", "1", "06/01/2025", "Open", "Accounts Payable", "A", "", Decimal("100.00"), False),
            CheckEntry(6, 2025, "eft", "2", "06/02/2025", "Open", "Accounts Payable", "B", "", Decimal("200.00"), False),
            CheckEntry(7, 2025, "check", "3", "07/01/2025", "Open", "Accounts Payable", "C", "", Decimal("300.00"), True),
        ]

    def test_sanity(self):
        stats = sanity(self.entries)
        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["by_type"], {"check": 2, "eft": 1})
        self.assertEqual(stats["total_nonvoid"], Decimal("300.00"))

    def test_month_rollups(self):
        roll = month_rollups(self.entries)
        self.assertIn((6, 2025), roll)
        self.assertIn((7, 2025), roll)
        self.assertEqual(roll[(6, 2025)]["checks"], Decimal("100.00"))
        self.assertEqual(roll[(6, 2025)]["efts"], Decimal("200.00"))
        self.assertEqual(roll[(6, 2025)]["grand"], Decimal("300.00"))
        self.assertEqual(roll[(7, 2025)]["grand"], Decimal("0.00"))
