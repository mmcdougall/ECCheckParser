import csv
import unittest

from project_paths import ARTIFACT_CSV_DIR
from check_register.payee_shortener import name_length_stats


class TestPayeeNameStats(unittest.TestCase):
    def test_name_shortening_thresholds(self):
        payees = []
        paths = [
            ARTIFACT_CSV_DIR / "2024-12.csv",
            ARTIFACT_CSV_DIR / "2025-01.csv",
            ARTIFACT_CSV_DIR / "2025-02.csv",
        ]
        for path in paths:
            with path.open() as f:
                reader = csv.DictReader(f)
                for row in reader:
                    payees.append(row["payee"])
        lengths = [len(p) for p in payees]
        original_mean = sum(lengths) / len(lengths)
        original_over_30 = sum(1 for l in lengths if l > 30)
        stats = name_length_stats(payees)
        self.assertLess(stats["mean"], original_mean * 0.95)
        self.assertLessEqual(stats["over_30"], original_over_30 * 0.6)
