import json
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from check_register.models import PositionedWord, RowChunk
from check_register.parser import CheckRegisterParser, _ExtractState


FIXTURES = Path(__file__).parent / 'fixtures' / 'register_word_rows.json'


class TestRegisterGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = json.loads(FIXTURES.read_text())

    def setUp(self):
        self.parser = CheckRegisterParser(Path('unused.pdf'))

    def chunks(self, fixture, scale=1):
        words = [
            {key: value if key == 'text' else value * scale for key, value in word.items()}
            for word in fixture['words']
        ]
        page = Mock()
        page.extract_words.return_value = words
        year, month = map(int, fixture['month'].split('-'))
        state = _ExtractState(year=year, month=month, mode='check')
        chunks = []
        for line in self.parser._words_by_line(page):
            chunks.extend(self.parser._handle_line(' '.join(w.text for w in line), line, state))
        chunks.extend(self.parser._flush_chunk(state))
        return chunks

    def september_entries(self, scale=1):
        chunks = [
            chunk for fixture in self.fixtures if fixture['month'] == '2026-09'
            for chunk in self.chunks(fixture, scale)
        ]
        return {entry.number: entry for entry in self.parser.parse_chunks(chunks)}

    def test_offset_descriptions_keep_their_payment_rows_at_different_scales(self):
        for scale in (0.5, 1, 2):
            with self.subTest(scale=scale):
                entries = self.september_entries(scale)
                self.assertEqual(len(entries), 7)
                entry = entries['97369']
                self.assertEqual(entry.payee, 'AMERICAN MECHANICAL SERVICES, INC.')
                self.assertEqual(entry.description, 'CITY HALL HVAC MAINTENANCE MAY-JULY 2026')
                self.assertEqual(entry.amount, Decimal('2760.00'))
                self.assertEqual(entries['97370'].description, 'FIBER DATA LINE 7/13/26-8/12/26')
                self.assertEqual(entries['97371'].description, 'PARKEC MAILER POSTCARDS')

    def test_blank_description_does_not_borrow_the_next_row(self):
        entries = self.september_entries()
        self.assertEqual(entries['97379'].payee, 'ENGBERG, GERI')
        self.assertEqual(entries['97379'].description, '')
        self.assertTrue(entries['97379'].voided)
        self.assertEqual(entries['97380'].payee, 'FLEET MANAGEMENT HOLDINGS, LLC')
        self.assertEqual(
            entries['97380'].description,
            'R3: FUEL + AIR FILTERS + OIL CHANGE + WATER SEPARATOR',
        )

    def test_repeated_vendor_keeps_identical_description_and_separate_amounts(self):
        entries = self.september_entries()
        for number, amount in [('3918', '137.45'), ('3919', '815.02')]:
            self.assertEqual(entries[number].payee, 'FIRST DATA MERCHANT SERVICES INC')
            self.assertEqual(entries[number].description, 'MERCHANT FEE EXPENSE - AUG2026')
            self.assertEqual(entries[number].amount, Decimal(amount))

    def test_wrapped_source_does_not_corrupt_the_following_payment(self):
        fixture = next(f for f in self.fixtures if f['month'] == '2026-07')
        chunks = self.chunks(fixture)
        entries = self.parser.parse_chunks(chunks)
        self.assertEqual([entry.number for entry in entries], ['96937', '96938', '96939'])
        entry = entries[1]
        self.assertEqual(entry.source, 'Accounts Payable')
        self.assertEqual(entry.payee, 'ODP BUSINESS SOLUTIONS, LLC')
        self.assertEqual(entry.description, 'OFFICE SUPPLIES REC')
        self.assertEqual(entry.amount, Decimal('158.34'))
        self.assertEqual(entries[2].description, 'FIRE PLAN REVIEW SERVICES JUN 2026')

    def test_positioned_rows_do_not_need_name_heuristics(self):
        with patch.object(self.parser, '_split_payee_desc_block', side_effect=AssertionError):
            self.assertEqual(len(self.september_entries()), 7)

    def test_column_inference_is_independent_for_each_month(self):
        chunks = []
        for month, payee_x, description_x in [(6, 100, 200), (7, 200, 400)]:
            for index in range(4):
                words = [
                    PositionedWord('1000', 1),
                    PositionedWord('06/01/2025', 20),
                    PositionedWord('Open', 40),
                    PositionedWord('Accounts', 50),
                    PositionedWord('Payable', 70),
                    PositionedWord('SAMPLE', payee_x),
                    PositionedWord('VENDOR', payee_x + 20 + index),
                    PositionedWord('Service', description_x),
                    PositionedWord('fee', description_x + 20 + index),
                    PositionedWord('$1.00', description_x + 80),
                ]
                chunks.append(RowChunk(month, 2025, 'check', [
                    ' '.join(w.text for w in words)
                ], [words]))
        entries = self.parser.parse_chunks(chunks)
        self.assertEqual([(e.payee, e.description) for e in entries], [
            ('SAMPLE VENDOR', 'Service fee')
        ] * 8)

    def test_empty_serialized_word_line_uses_text_fallback(self):
        chunk = RowChunk(9, 2026, 'check', [
            '97369 09/03/2026 Open Accounts Payable ACME INC. SERVICES $1.00'
        ], [[]])
        self.assertEqual(self.parser.parse_chunks([chunk])[0].amount, Decimal('1.00'))


if __name__ == '__main__':
    unittest.main()
