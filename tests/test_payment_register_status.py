import unittest
from decimal import Decimal
from pathlib import Path

from check_register.models import PositionedWord
from check_register.parser import CheckRegisterParser, _ExtractState
from payee_splitter.cluster import infer_description_column_x0, split_payee_desc_by_x


class TestPaymentRegisterStatus(unittest.TestCase):
    def parse_lines(self, lines):
        parser = CheckRegisterParser(Path('unused.pdf'))
        state = _ExtractState()
        chunks = []
        for line in lines:
            chunks.extend(parser._handle_line(line, [], state))
        chunks.extend(parser._flush_chunk(state))
        for chunk in chunks:
            chunk.line_words = []
        return parser.parse_chunks(chunks)

    def test_reconciled_row_keeps_payment_date_and_amount(self):
        entries = self.parse_lines([
            'From Payment Date: 3/1/2026 - To Payment Date: 3/31/2026',
            'Check',
            '95738 03/05/2026 Reconciled 03/11/2026 Accounts Payable SONIC TELECOM RELEASE OF BONDS 761.65',
        ])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].date, '03/05/2026')
        self.assertEqual(entries[0].status, 'Reconciled')
        self.assertEqual(entries[0].amount, Decimal('761.65'))
        self.assertFalse(entries[0].voided)

    def test_void_reason_and_void_date_do_not_hide_row(self):
        entries = self.parse_lines([
            'From Payment Date: 11/1/2025 - To Payment Date: 11/30/2025',
            'Check',
            '94835 11/20/2025 Voided Test Error 11/20/2025 Accounts Payable BADGE FRAME, INC. #N/A 108.05',
        ])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].number, '94835')
        self.assertTrue(entries[0].voided)
        self.assertEqual(entries[0].amount, Decimal('108.05'))

    def test_standalone_eft_heading_survives_repeated_page_header(self):
        entries = self.parse_lines([
            'From Payment Date: 3/1/2026 - To Payment Date: 3/31/2026',
            'EFT',
            '3686 03/31/2026 Open Accounts Payable FIRST DATA MERCHANT SERVICES INC FEES 950.89',
            'From Payment Date: 3/1/2026 - To Payment Date: 3/31/2026',
            '3687 03/31/2026 Open Accounts Payable FIRST DATA MERCHANT SERVICES INC FEES 57.18',
            'Check',
            '95738 03/05/2026 Reconciled 03/11/2026 Accounts Payable SONIC TELECOM BONDS 761.65',
        ])
        self.assertEqual([entry.ap_type for entry in entries], ['eft', 'eft', 'check'])

    def test_new_month_resets_payment_type_to_check(self):
        entries = self.parse_lines([
            'From Payment Date: 3/1/2026 - To Payment Date: 3/31/2026',
            'EFT',
            '3686 03/31/2026 Open Accounts Payable FIRST DATA MERCHANT SERVICES INC FEES 950.89',
            'From Payment Date: 4/1/2026 - To Payment Date: 4/30/2026',
            '95973 04/02/2026 Open Accounts Payable TERRA NOVA ENGINEERING INC BONDS 1871.00',
        ])
        self.assertEqual([entry.ap_type for entry in entries], ['eft', 'check'])
        self.assertEqual([entry.section_month for entry in entries], [3, 4])

    def test_miscellaneous_billing_refund_is_a_register_row(self):
        entries = self.parse_lines([
            'From Payment Date: 6/1/2026 - To Payment Date: 6/30/2026',
            '96601 06/15/2026 Open Miscellaneous Billing Refund Burger King-Sohrabi Enterprises II, Inc. Refund 634.00',
        ])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].source, 'Miscellaneous Billing Refund')
        self.assertEqual(entries[0].amount, Decimal('634.00'))

    def test_refund_source_is_excluded_from_payee(self):
        words = [[PositionedWord(text, x0) for text, x0 in [
            ('96601', 34.29), ('06/15/2026', 91.5), ('Open', 152.79),
            ('Miscellaneous', 376.5), ('Billing', 427.92), ('Refund', 450.41),
            ('Burger', 497.57), ('King-Sohrabi', 523.49), ('Enterprises', 571.27),
            ('II,', 612.84), ('Inc.', 620.98), ('Refund', 744.21), ('634.00', 1188.81),
        ]]]
        payee, description = split_payee_desc_by_x(words, 744.21)
        self.assertEqual(payee, 'Burger King-Sohrabi Enterprises II, Inc.')
        self.assertEqual(description, 'Refund')

    def test_blank_descriptions_do_not_make_payee_column_the_boundary(self):
        rows = []
        for index in range(4):
            words = [
                PositionedWord('Accounts', 376.2),
                PositionedWord('Payable', 410.6),
                PositionedWord('VENDOR', 468.2),
                PositionedWord('INC.', 503.6 + index),
            ]
            if index < 3:
                words.append(PositionedWord('SERVICES', 762.0))
            words.append(PositionedWord('100.00', 1188.6))
            rows.append([words])
        self.assertEqual(infer_description_column_x0(rows), 762.0)
        self.assertEqual(split_payee_desc_by_x(rows[0], 762.0), ('VENDOR INC.', 'SERVICES'))



if __name__ == '__main__':
    unittest.main()
