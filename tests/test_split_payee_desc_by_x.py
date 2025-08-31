import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from check_register.models import PositionedWord
from payee_splitter.cluster import split_payee_desc_by_x


class SplitPayeeDescByXTests(unittest.TestCase):
    # (1) 93284 06/05/2025 Open Accounts Payable AMAZON CAPITAL SERVICES, INC. OFFICE SUPPLIES $89.26
    # (2) payee="AMAZON CAPITAL SERVICES, INC.", desc="OFFICE SUPPLIES"
    def test_amazon_office_supplies(self):
        line_words = [[
            PositionedWord(text="93284", x0=7.6799),
            PositionedWord(text="06/05/2025", x0=50.038340000000005),
            PositionedWord(text="Open", x0=81.47822000000001),
            PositionedWord(text="Accounts", x0=214.91582),
            PositionedWord(text="Payable", x0=237.833444),
            PositionedWord(text="AMAZON", x0=285.11762),
            PositionedWord(text="CAPITAL", x0=308.51306),
            PositionedWord(text="SERVICES,", x0=331.546784),
            PositionedWord(text="INC.", x0=360.69562399999995),
            PositionedWord(text="OFFICE", x0=446.76),
            PositionedWord(text="SUPPLIES", x0=468.473652),
            PositionedWord(text="$89.26", x0=741.84),
        ]]
        payee, desc = split_payee_desc_by_x(line_words)
        self.assertEqual(payee, "AMAZON CAPITAL SERVICES, INC.")
        self.assertEqual(desc, "OFFICE SUPPLIES")

    # (1) 3192 03/07/2025 Open Accounts Payable P E R S PE1% - PERS SEIU* $213,803.82
    # (2) payee="PERS", desc="PE1% - PERS SEIU*"
    def test_pers_contributions(self):
        line_words = [[
            PositionedWord(text="3192", x0=7.680860000000052),
            PositionedWord(text="03/07/2025", x0=45.23894000000005),
            PositionedWord(text="Open", x0=76.19966000000005),
            PositionedWord(text="Accounts", x0=210.71726000000007),
            PositionedWord(text="Payable", x0=232.68460400000006),
            PositionedWord(text="P", x0=279.71486000000004),
            PositionedWord(text="E", x0=284.51797999999997),
            PositionedWord(text="R", x0=289.3211),
            PositionedWord(text="S", x0=294.362612),
            PositionedWord(text="PE1%", x0=431.2799),
            PositionedWord(text="-", x0=448.20035599999994),
            PositionedWord(text="PERS", x0=451.919084),
            PositionedWord(text="SEIU*", x0=467.51992399999995),
            PositionedWord(text="$213,803.82", x0=677.64),
        ]]
        payee, desc = split_payee_desc_by_x(line_words)
        self.assertEqual(payee, "PERS")
        self.assertEqual(desc, "PE1% - PERS SEIU*")

    # (1) 93286 06/05/2025 Open Accounts Payable BERTRAND, FOX, ELLIOT, OSMAN & WENZEL LLP
    #     PERSONNEL MATTER 02/03/25 - 02/28/25 $8,076.25
    # (2) payee="BERTRAND, FOX, ELLIOT, OSMAN & WENZEL LLP", desc="PERSONNEL MATTER 02/03/25 - 02/28/25"
    def test_long_payee_with_dates(self):
        line_words = [[
            PositionedWord(text="93286", x0=7.68),
            PositionedWord(text="06/05/2025", x0=50.03844),
            PositionedWord(text="Open", x0=81.47832),
            PositionedWord(text="Accounts", x0=214.91592),
            PositionedWord(text="Payable", x0=237.833544),
            PositionedWord(text="BERTRAND,", x0=285.1177200000001),
            PositionedWord(text="FOX,", x0=316.43118000000004),
            PositionedWord(text="ELLIOT,", x0=329.86885200000006),
            PositionedWord(text="OSMAN", x0=350.5062720000001),
            PositionedWord(text="&", x0=370.7819760000001),
            PositionedWord(text="WENZEL", x0=375.69945600000005),
            PositionedWord(text="LLP", x0=398.8539240000001),
            PositionedWord(text="PERSONNEL", x0=446.76),
            PositionedWord(text="MATTER", x0=482.7575519999999),
            PositionedWord(text="02/03/25", x0=508.67459999999994),
            PositionedWord(text="-", x0=537.35214),
            PositionedWord(text="02/28/25", x0=541.069848),
            PositionedWord(text="$8,076.25", x0=734.64),
        ]]
        payee, desc = split_payee_desc_by_x(line_words)
        self.assertEqual(payee, "BERTRAND, FOX, ELLIOT, OSMAN & WENZEL LLP")
        self.assertEqual(desc, "PERSONNEL MATTER 02/03/25 - 02/28/25")


if __name__ == "__main__":
    unittest.main()
