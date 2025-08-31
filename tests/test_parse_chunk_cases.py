import unittest
from pathlib import Path
from decimal import Decimal

from check_register import CheckRegisterParser, RowChunk
from check_register.models import PositionedWord


class TestParseChunkCases(unittest.TestCase):
    def test_missing_amount_warns_and_defaults_to_zero(self):
        parser = CheckRegisterParser(Path('dummy'))
        # Original row from ``data/artifacts/chunks/2025-04.json`` entry 92736:
        # 1000 06/01/2025 Open Accounts Payable CITY OF RICHMOND Fire services $1,234.56
        # The "$1,234.56" amount is removed for this test so the parser receives no amount:
        # 1000 06/01/2025 Open Accounts Payable CITY OF RICHMOND Fire services
        line_words = [
            [
                PositionedWord(text='1000', x0=7.8),
                PositionedWord(text='06/01/2025', x0=52.0),
                PositionedWord(text='Open', x0=85.0),
                PositionedWord(text='Accounts', x0=214.2),
                PositionedWord(text='Payable', x0=238.2),
                PositionedWord(text='CITY', x0=287.6),
                PositionedWord(text='OF', x0=300.0),
                PositionedWord(text='RICHMOND', x0=314.0),
                PositionedWord(text='Fire', x0=444.2),
                PositionedWord(text='services', x0=460.3),
                # amount intentionally removed
            ]
        ]
        chunk = RowChunk(
            section_month=6,
            section_year=2025,
            ap_type='check',
            lines=['1000 06/01/2025 Open Accounts Payable CITY OF RICHMOND Fire services'],
            line_words=line_words,
        )
        with self.assertLogs(level='WARNING') as logs:
            entry = parser.parse_chunks([chunk])[0]
        self.assertIn('Missing amount in row', logs.output[0])
        self.assertEqual(entry.amount, Decimal('0'))


if __name__ == '__main__':
    unittest.main()
