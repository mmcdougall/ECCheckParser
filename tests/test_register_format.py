import json
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pdfplumber

from check_register.models import PositionedWord, RowChunk
from check_register.parser import CheckRegisterParser, _ExtractState
from payee_splitter.cluster import infer_description_column_x0, split_payee_desc_by_x
from register_format import split_row_header


class TestRegisterFormat(unittest.TestCase):
    def test_optional_source_column(self):
        self.assertEqual(split_row_header(
            '89311 04/02/2024 Open STANTEC CONSULTING SERVICES, INC. (SCSI) ON CALL PLANNING $8,868.25'
        ), ('89311', '04/02/2024', 'Open', '',
            'STANTEC CONSULTING SERVICES, INC. (SCSI) ON CALL PLANNING $8,868.25'))
        self.assertEqual(split_row_header(
            '89462 04/18/2024 Voided Invoice Error 04/18/2024 CCC ANIMAL SERVICES DEPARTMENT $58,418.00'
        ), ('89462', '04/18/2024', 'Voided Invoice Error', '',
            'CCC ANIMAL SERVICES DEPARTMENT $58,418.00'))

    def test_payment_date_can_touch_the_status_column(self):
        fields = split_row_header(
            '89829 05/30/2024Voided/Reissued Invoice Error 06/05/2024 Accounts Payable '
            'BLANCA MARTINEZ-CAMPOS -SENIOR SERVICES PETTY CASH VOID $239.78'
        )
        self.assertEqual(fields[:4], (
            '89829', '05/30/2024', 'Voided/Reissued Invoice Error', 'Accounts Payable',
        ))

    def test_optional_status_column_does_not_invent_status(self):
        for reconciliation_date in ('07/09/2024 ', ''):
            with self.subTest(reconciliation_date=reconciliation_date):
                fields = split_row_header(
                    '90172 07/03/2024 ' + reconciliation_date +
                    'Accounts Payable AMAZON CAPITAL SERVICES, INC. EE/HR HOSTED EVENTS $73.87'
                )
                self.assertEqual(fields[2:4], ('', 'Accounts Payable'))
                self.assertTrue(fields[4].startswith('AMAZON CAPITAL SERVICES, INC.'))

    def test_unrecognized_metadata_is_not_a_payment(self):
        self.assertIsNone(split_row_header('1234 01/01/2025 unrelated agenda text'))

    def test_splitter_imports_without_importing_parser_first(self):
        result = subprocess.run(
            [sys.executable, '-c', 'from payee_splitter.cluster import split_payee_desc_by_x'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_alignment_uses_left_edge_despite_coordinate_jitter(self):
        rows = [[[
            PositionedWord('Accounts', 207.8), PositionedWord('Payable', 231.8),
            PositionedWord('VENDOR', 282.2), PositionedWord('NAME', 310 + i),
            PositionedWord('SHREDDING', x), PositionedWord('$81.79', 650.9),
        ]] for i, x in enumerate((433.64, 433.67, 433.69, 433.71))]
        boundary = infer_description_column_x0(rows)
        for row in rows:
            self.assertEqual(split_payee_desc_by_x(row, boundary), ('VENDOR NAME', 'SHREDDING'))

    def test_separatorless_amount_does_not_leak_into_description(self):
        row = [[
            PositionedWord('Accounts', 236.4), PositionedWord('Payable', 260.6),
            PositionedWord('VENDOR', 310.8), PositionedWord('SERVICES', 528.48),
            PositionedWord('$1,44000', 730.3),
        ]]
        self.assertEqual(split_payee_desc_by_x(row, 528.48), ('VENDOR', 'SERVICES'))

    def test_overlapping_fonts_do_not_split_amounts(self):
        path = Path(__file__).parent / 'fixtures' / 'overlapping_amount_characters.json'
        parser = CheckRegisterParser(Path('unused.pdf'))
        expected = {'92300': ('QUINTO, GABRIEL', '54.20'), '92358': ('SSD ALARM', '932.03')}
        for fixture in json.loads(path.read_text()):
            with self.subTest(number=fixture['number']):
                page = Mock()
                page.extract_words.side_effect = lambda **kw: pdfplumber.utils.extract_words(
                    fixture['chars'], **kw
                )
                state = _ExtractState(month=2, year=2025, mode='check')
                chunks = []
                for line in parser._words_by_line(page):
                    chunks.extend(parser._handle_line(' '.join(w.text for w in line), line, state))
                chunks.extend(parser._flush_chunk(state))
                self.assertEqual(len(chunks), 1)
                entry = parser._parse_chunk(chunks[0], 713.6)
                payee, amount = expected[fixture['number']]
                self.assertEqual(entry.payee, payee)
                self.assertTrue(entry.description)
                self.assertEqual(entry.amount, Decimal(amount))

    def test_wrapped_payee_and_numeric_description_follow_the_amount(self):
        parser = CheckRegisterParser(Path('unused.pdf'))
        state = _ExtractState(month=3, year=2026, mode='check')
        first = [PositionedWord(text, x0) for text, x0 in [
            ('95825', 20), ('03/12/2026', 60), ('Reconciled', 100),
            ('03/16/2026', 160), ('Accounts', 220), ('Payable', 250),
            ('CONTRA', 300), ('COSTA', 330), ('COUNTY', 360),
            ('OFFICE', 395), ('OF', 425), ('SHERIFF-', 440),
            ('CAL-ID', 550), ('FY25-26', 590), ('48,690.00', 700),
        ]]
        lines = [first, [PositionedWord('CORONER', 300)], [PositionedWord('2026', 550)]]
        chunks = []
        for words in lines:
            chunks.extend(parser._handle_line(' '.join(w.text for w in words), words, state))
        chunks.extend(parser._handle_line('user: Clerk', [PositionedWord('user:', 20)], state))
        self.assertEqual(len(chunks), 1)
        entry = parser._parse_chunk(chunks[0], 550)
        self.assertEqual(entry.payee, 'CONTRA COSTA COUNTY OFFICE OF SHERIFF- CORONER')
        self.assertEqual(entry.description, 'CAL-ID FY25-26 2026')
        self.assertEqual(entry.amount, Decimal('48690.00'))

    def test_single_letters_do_not_merge_across_wrapped_lines(self):
        rows = [[
            PositionedWord('Accounts', 200), PositionedWord('Payable', 250),
            PositionedWord('BANK', 300), PositionedWord('A', 320),
            PositionedWord('X', 550), PositionedWord('$1.00', 700),
        ], [PositionedWord('B', 300)]]
        self.assertEqual(split_payee_desc_by_x(rows, 550), ('BANK A B', 'X'))

    def test_wrapped_status_does_not_close_the_description(self):
        parser = CheckRegisterParser(Path('unused.pdf'))
        state = _ExtractState(month=7, year=2025, mode='eft')
        first = [PositionedWord(text, x0) for text, x0 in [
            ('3342', 8), ('06/30/2025', 43), ('Voided', 81),
            ('Enter', 133), ('Correct', 146), ('07/31/2025', 168),
            ('Accounts', 207), ('Payable', 229), ('PG&E', 264), ('$23,076.10', 677),
        ]]
        lines = [first, [PositionedWord('Payment', 133), PositionedWord('Date', 154)],
                 [PositionedWord('VOID', 414)]]
        chunks = []
        for words in lines:
            chunks.extend(parser._handle_line(' '.join(w.text for w in words), words, state))
        chunks.extend(parser._flush_chunk(state))
        self.assertEqual(len(chunks), 1)
        entry = parser._parse_chunk(chunks[0], 414)
        self.assertEqual((entry.payee, entry.description), ('PG&E', 'VOID'))
        self.assertEqual(entry.amount, Decimal('23076.10'))
        self.assertTrue(entry.voided)

    def test_half_height_overlap_keeps_neighboring_status_separate(self):
        page = Mock()
        page.extract_words.return_value = [
            {'text': 'R', 'x0': 146.4, 'top': 127.1, 'bottom': 135.1},
            {'text': '95432', 'x0': 28.0, 'top': 131.1, 'bottom': 139.1},
            {'text': 'Open', 'x0': 146.4, 'top': 131.1, 'bottom': 139.1},
            {'text': '2 NEW TIRES', 'x0': 633.2, 'top': 134.1, 'bottom': 142.1},
        ]
        lines = CheckRegisterParser(Path('unused.pdf'))._words_by_line(page)
        self.assertEqual([[word.text for word in line] for line in lines], [
            ['R'], ['95432', 'Open', '2 NEW TIRES'],
        ])


if __name__ == '__main__':
    unittest.main()
