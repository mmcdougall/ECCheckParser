import os
import sys
import unittest
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from check_register.parser import CheckRegisterParser
from tests.jul_aug_2025_top_payees import PAYEES_JUL_AUG_2025_TOP


class TestJulAug2025TopPayees(unittest.TestCase):
    """Ensure parser extracts a reasonable number of top payees by amount."""

    def test_minimum_matches(self):
        parser = CheckRegisterParser(Path('ECPackets/2025/Agenda Packet (8.19.2025).pdf'))
        entries = parser.extract()
        entries_sorted = sorted(entries, key=lambda e: e.amount, reverse=True)
        payees = [e.payee for e in entries_sorted[: len(PAYEES_JUL_AUG_2025_TOP)]]
        matches = sum(1 for a, b in zip(PAYEES_JUL_AUG_2025_TOP, payees) if a == b)
        # Baseline as of this commit: 27 matches. Update as heuristics improve.
        self.assertGreaterEqual(matches, 27,
                                f"Only {matches} of {len(PAYEES_JUL_AUG_2025_TOP)} payees matched")


if __name__ == "__main__":
    unittest.main()
