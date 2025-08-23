import os
import sys
import unittest
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from check_register.parser import CheckRegisterParser
from tests.june_2025_payees import PAYEES_JUNE_2025


class TestJune2025Payees(unittest.TestCase):
    """Ensure parser extracts a reasonable number of known June 2025 payees."""

    def test_minimum_matches(self):
        parser = CheckRegisterParser(Path('CheckRegisterArchive/2025/2025-06-07-register.pdf'))
        entries = parser.extract()
        payees = [e.payee for e in entries if e.section_month == 6 and e.section_year == 2025]
        payees = payees[: len(PAYEES_JUNE_2025)]
        matches = sum(1 for a, b in zip(PAYEES_JUNE_2025, payees) if a == b)
        # Baseline as of this commit: 102 matches. Update as heuristics improve.
        self.assertGreaterEqual(matches, 102, f"Only {matches} of {len(PAYEES_JUNE_2025)} payees matched")


if __name__ == "__main__":
    unittest.main()
