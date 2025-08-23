import json
import os
import sys
import unittest
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from check_register.models import RowChunk
from check_register.parser import CheckRegisterParser
from tests.jul_aug_2025_top_payees import PAYEES_JUL_AUG_2025_TOP


class TestJulAug2025TopPayees(unittest.TestCase):
    """Ensure parser extracts a reasonable number of top payees by amount."""

    def test_minimum_matches(self):
        with open('CheckRegisterArchive/2025/2025-06-07-register.chunks.json') as f:
            chunk_dicts = json.load(f)
        chunks = [RowChunk(**c) for c in chunk_dicts]
        parser = CheckRegisterParser(Path('CheckRegisterArchive/2025/2025-06-07-register.pdf'))
        entries = parser.parse_chunks(chunks)
        entries_sorted = sorted(entries, key=lambda e: e.amount, reverse=True)
        payees = [e.payee for e in entries_sorted[: len(PAYEES_JUL_AUG_2025_TOP)]]
        matches = sum(1 for a, b in zip(PAYEES_JUL_AUG_2025_TOP, payees) if a == b)
        # Baseline as of this commit: 27 matches. Update as heuristics improve.
        self.assertGreaterEqual(matches, 27,
                                f"Only {matches} of {len(PAYEES_JUL_AUG_2025_TOP)} payees matched")


if __name__ == "__main__":
    unittest.main()
