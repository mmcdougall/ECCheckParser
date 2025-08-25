import unittest
from pathlib import Path
from decimal import Decimal

from check_register import CheckRegisterParser, RowChunk
from check_register.models import PositionedWord


class TestParseChunksBasic(unittest.TestCase):
    def test_basic_chunk_parsing(self):
        parser = CheckRegisterParser(Path('dummy'))
        # ``x0`` positions approximate values from
        # ``data/artifacts/chunks/2025-04.json`` entry 92736 (VELOCITY LOCK AND
        # KEY KEYS - CUSTODIAL CLOSET).  Payee tokens cluster around ~290-340 and
        # description tokens around ~440+.  These synthetic coordinates ensure
        # tests remain stable even if artifacts are regenerated.
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
                PositionedWord(text='$1,234.56', x0=728.8),
            ]
        ]
        chunk = RowChunk(
            section_month=6,
            section_year=2025,
            ap_type='check',
            lines=['1000 06/01/2025 Open Accounts Payable CITY OF RICHMOND Fire services $1,234.56'],
            line_words=line_words,
        )
        entry = parser.parse_chunks([chunk])[0]
        self.assertEqual(entry.number, '1000')
        self.assertEqual(entry.payee, 'CITY OF RICHMOND')
        self.assertEqual(entry.description, 'Fire services')
        self.assertEqual(entry.amount, Decimal('1234.56'))

    def test_letter_run_squeezed(self):
        parser = CheckRegisterParser(Path('dummy'))
        # ``x0`` positions approximate values from
        # ``data/artifacts/chunks/2025-06-07.json`` entry
        # "3306 06/13/2025 Open Accounts Payable P E R S PE1% - PERS SEIU*".
        # The payee letters are extracted individually and should be merged
        # into "PERS" before splitting the description column.
        line_words = [
            [
                PositionedWord(text='1001', x0=7.8),
                PositionedWord(text='06/13/2025', x0=52.0),
                PositionedWord(text='Open', x0=85.0),
                PositionedWord(text='Accounts', x0=214.2),
                PositionedWord(text='Payable', x0=238.2),
                PositionedWord(text='P', x0=285.1),
                PositionedWord(text='E', x0=290.0),
                PositionedWord(text='R', x0=295.0),
                PositionedWord(text='S', x0=300.1),
                PositionedWord(text='PE1%', x0=446.7),
                PositionedWord(text='$1.00', x0=728.8),
            ]
        ]
        chunk = RowChunk(
            section_month=6,
            section_year=2025,
            ap_type='check',
            lines=['1001 06/13/2025 Open Accounts Payable P E R S PE1% $1.00'],
            line_words=line_words,
        )
        entry = parser.parse_chunks([chunk])[0]
        self.assertEqual(entry.payee, 'PERS')
        self.assertEqual(entry.description, 'PE1%')


if __name__ == '__main__':
    unittest.main()
