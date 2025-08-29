import unittest

from check_register import shorten_payee


class TestPayeeShortener(unittest.TestCase):
    def test_suffix_removed(self):
        name = "COMMUNITY CONSERVATION CENTERS, INC."
        self.assertEqual(shorten_payee(name), "COMMUNITY CONSERVATION CENTERS")

    def test_suffix_and_contraction(self):
        name = "AMAZON CAPITAL SERVICES, INC."
        self.assertEqual(shorten_payee(name), "AMAZON CAPITAL SVCS")

    def test_contraction_only(self):
        name = "WILLDAN FINANCIAL SERVICES"
        self.assertEqual(shorten_payee(name), "WILLDAN FINANCIAL SVCS")

    def test_parenthetical_removed(self):
        name = "MIssionSquare (name chg 03-2021 formerly ICMA)"
        self.assertEqual(shorten_payee(name), "MIssionSquare")

    def test_suffix_llp(self):
        name = "REDWOOD PUBLIC LAW, LLP"
        self.assertEqual(shorten_payee(name), "REDWOOD PUBLIC LAW")


if __name__ == "__main__":
    unittest.main()
