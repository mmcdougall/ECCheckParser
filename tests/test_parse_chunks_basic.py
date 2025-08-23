import unittest
from pathlib import Path
from decimal import Decimal

from check_register import CheckRegisterParser, RowChunk


class TestParseChunksBasic(unittest.TestCase):
    def test_basic_chunk_parsing(self):
        parser = CheckRegisterParser(Path('dummy'))
        chunk = RowChunk(
            section_month=6,
            section_year=2025,
            ap_type='check',
            lines=['1000 06/01/2025 Open Accounts Payable CITY OF RICHMOND Fire services $1,234.56'],
        )
        entry = parser.parse_chunks([chunk])[0]
        self.assertEqual(entry.number, '1000')
        self.assertEqual(entry.payee, 'CITY OF RICHMOND')
        self.assertEqual(entry.description, 'Fire services')
        self.assertEqual(entry.amount, Decimal('1234.56'))


if __name__ == '__main__':
    unittest.main()
