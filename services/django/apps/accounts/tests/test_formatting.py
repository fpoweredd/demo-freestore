from decimal import Decimal

from django.test import SimpleTestCase

from apps.accounts.formatting import format_balance_amount, format_balance_rub_line


class FormatBalanceTests(SimpleTestCase):
    def test_whole_without_decimals(self):
        self.assertEqual(format_balance_amount(Decimal("100")), "100")
        self.assertEqual(format_balance_amount(Decimal("100.00")), "100")

    def test_fractional_always_two_decimals(self):
        self.assertEqual(format_balance_amount(Decimal("123.40")), "123.40")
        self.assertEqual(format_balance_amount(Decimal("123.4500")), "123.45")
        self.assertEqual(format_balance_amount(Decimal("500000.3")), "500000.30")
        self.assertEqual(format_balance_amount(Decimal("10.5")), "10.50")

    def test_none_and_invalid(self):
        self.assertEqual(format_balance_amount(None), "0")
        self.assertEqual(format_balance_amount("bad"), "0")

    def test_rub_line(self):
        self.assertEqual(format_balance_rub_line(Decimal("10")), "$10")
        self.assertEqual(format_balance_rub_line(Decimal("10.50")), "$10.50")
