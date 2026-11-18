import json
import unittest
from collections import defaultdict
from decimal import Decimal

from project_paths import ARTIFACT_CHUNKS_DIR

from check_register.parser import CheckRegisterParser
from check_register.models import RowChunk
from check_register.stats import month_totals


class TestMonthTotalsJune2025(unittest.TestCase):
    def test_month_totals_dedup(self):
        chunks = []
        for month in ('2025-06', '2025-07'):
            chunk_path = ARTIFACT_CHUNKS_DIR / f'{month}-chunks.json'
            self.assertTrue(chunk_path.exists(), f"Missing chunk file: {chunk_path}")
            with chunk_path.open() as f:
                chunks.extend(RowChunk(**c) for c in json.load(f))
        parser = CheckRegisterParser(chunk_path)
        entries = parser.parse_chunks(chunks)

        # 6/30/2025 appears in both the June and July registers; ensure
        # duplicates are only counted once and attributed to June.
        seen_sections = defaultdict(set)
        for e in entries:
            key = (e.ap_type, e.number, e.date, e.amount)
            seen_sections[key].add(e.section_month)

        dup_keys = [k for k, months in seen_sections.items() if len(months) > 1]
        self.assertEqual(len(dup_keys), 63)
        self.assertTrue(all(k[0] == "check" and k[2] == "06/30/2025" for k in dup_keys))
        self.assertTrue(all(seen_sections[k] == {6, 7} for k in dup_keys))

        eft_630 = [e for e in entries if e.ap_type == "eft" and e.date == "06/30/2025"]
        june_efts = [e for e in eft_630 if e.section_month == 6]
        july_voids = [e for e in eft_630 if e.section_month == 7]
        self.assertEqual(len(eft_630), 20)
        self.assertEqual(len(june_efts), 17)
        self.assertEqual({e.number for e in july_voids}, {'3342', '3343', '3344'})
        self.assertTrue(all(e.voided for e in july_voids))

        totals = month_totals(entries)
        self.assertEqual(totals[(6, 2025)], Decimal("4569023.17"))
        self.assertEqual(totals[(7, 2025)], Decimal("14296239.84"))


if __name__ == "__main__":
    unittest.main()

