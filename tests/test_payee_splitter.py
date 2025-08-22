import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from payee_splitter import split_payee_desc_block
from tests.payee_desc_cases import CASES


class PayeeSplitTests(unittest.TestCase):
    def test_cases(self):
        for text, payee, desc in CASES:
            with self.subTest(text=text):
                got_payee, got_desc = split_payee_desc_block(text)
                self.assertEqual(got_payee, payee)
                self.assertEqual(got_desc, desc)


if __name__ == "__main__":
    unittest.main()
