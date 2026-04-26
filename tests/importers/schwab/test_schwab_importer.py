import unittest
from unittest.mock import patch
from datetime import date, timedelta
from decimal import Decimal

from opensteuerauszug.importers.schwab.schwab_importer import (
    SchwabImporter,
    _get_configured_account_info,
    _pick_primary_client_number,
    _resolve_cash_account_identity,
    _resolve_security_depot_display_name,
    _schwab_security_display_name,
    next_business_day,
    settlement_date,
    split_unsettled_cash,
)
from opensteuerauszug.model.ech0196 import (
    SecurityPayment,
    SecurityStock,
)
from opensteuerauszug.model.position import CashPosition, SecurityPosition
from opensteuerauszug.config.models import SchwabAccountSettings


class TestGetConfiguredAccountInfo(unittest.TestCase):
    def test_awards_depot(self):
        acc_num, display_id = _get_configured_account_info(
            depot_short_id="XYZ123",
            account_settings_list=[],
            is_awards_depot=True
        )
        self.assertIsNone(acc_num)
        self.assertEqual(display_id, "Equity Awards XYZ123")

    def test_non_awards_unique_match(self):
        settings = [
            SchwabAccountSettings(account_number="CH123456789", account_name_alias="main", broker_name="schwab", canton="ZH", full_name="Test User")
        ]
        acc_num, display_id = _get_configured_account_info(
            depot_short_id="789",
            account_settings_list=settings,
            is_awards_depot=False
        )
        self.assertEqual(acc_num, "CH123456789")
        self.assertEqual(display_id, "CH123456789")

    def test_non_awards_no_match(self):
        settings = [
            SchwabAccountSettings(account_number="CH123456789", account_name_alias="main", broker_name="schwab", canton="ZH", full_name="Test User")
        ]
        acc_num, display_id = _get_configured_account_info(
            depot_short_id="000",
            account_settings_list=settings,
            is_awards_depot=False
        )
        self.assertIsNone(acc_num)
        self.assertEqual(display_id, "...000")

    def test_non_awards_multiple_matches_uses_first(self):
        settings = [
            SchwabAccountSettings(account_number="FR987654321", account_name_alias="secondary", broker_name="schwab", canton="ZH", full_name="Test User"),
            SchwabAccountSettings(account_number="CH123454321", account_name_alias="primary", broker_name="schwab", canton="ZH", full_name="Test User")
        ]
        acc_num, display_id = _get_configured_account_info(
            depot_short_id="321",
            account_settings_list=settings,
            is_awards_depot=False
        )
        self.assertEqual(acc_num, "FR987654321")
        self.assertEqual(display_id, "FR987654321")

        # Check if a warning was logged
        with self.assertLogs('opensteuerauszug.importers.schwab.schwab_importer', level='WARNING') as cm:
            _get_configured_account_info(
                depot_short_id="321",
                account_settings_list=settings,
                is_awards_depot=False
            )
            self.assertEqual(len(cm.output), 1)
            self.assertIn("Multiple configured Schwab accounts end with '...321'", cm.output[0])
            self.assertIn("'FR987654321' (alias: 'secondary')", cm.output[0])


    def test_non_awards_empty_settings(self):
        acc_num, display_id = _get_configured_account_info(
            depot_short_id="123",
            account_settings_list=[],
            is_awards_depot=False
        )
        self.assertIsNone(acc_num)
        self.assertEqual(display_id, "...123")

    # The case for non_awards_match_with_no_alias_in_setting is implicitly covered
    # by test_non_awards_unique_match, as account_name_alias is mandatory.
    # The warning message for multiple matches also correctly references the alias.


class TestSchwabImporterAccountResolution(unittest.TestCase):
    """Exercise the Schwab-specific display-name / client resolution helpers.

    These helpers back the ``DepotNumber`` / ``BankAccountName`` /
    ``BankAccountNumber`` / ``TaxStatement.client`` fields that the shared
    post-processing stage in ``importers.common.postprocess`` writes to the
    TaxStatement.  The shared stage itself is covered by tests in
    ``tests/importers/common/test_postprocess.py``; here we only verify
    Schwab's "awards" special case and the ``...<short_id>`` fallback.
    """

    def setUp(self):
        self.default_settings_args = {
            "broker_name": "schwab",
            "canton": "ZH",
            "full_name": "Test User",
        }

    # --- _resolve_cash_account_identity ---

    def test_cash_identity_unique_match(self):
        settings = [
            SchwabAccountSettings(
                account_number="CH123-789",
                account_name_alias="main",
                **self.default_settings_args,
            )
        ]
        pos = CashPosition(
            depot="789", currentCy="USD", cash_account_id="cash789", type="cash"
        )
        name, number = _resolve_cash_account_identity(pos, settings)
        self.assertEqual(name, "CH123-789")
        self.assertEqual(number, "CH123-789")

    def test_cash_identity_no_match_uses_currency_prefix(self):
        settings = [
            SchwabAccountSettings(
                account_number="CH123-000",
                account_name_alias="other",
                **self.default_settings_args,
            )
        ]
        pos = CashPosition(
            depot="789", currentCy="USD", cash_account_id="cash789", type="cash"
        )
        name, number = _resolve_cash_account_identity(pos, settings)
        self.assertEqual(name, "USD Account ...789")
        self.assertIsNone(number)

    def test_cash_identity_awards_ignores_settings(self):
        settings = [
            SchwabAccountSettings(
                account_number="CH123-IGNORE",
                account_name_alias="main_ignore",
                **self.default_settings_args,
            )
        ]
        pos = CashPosition(
            depot="AWARDS",
            cash_account_id="AWARD123",
            currentCy="USD",
            type="cash",
        )
        name, number = _resolve_cash_account_identity(pos, settings)
        self.assertEqual(name, "Equity Awards AWARD123")
        self.assertIsNone(number)

    def test_cash_identity_empty_settings(self):
        pos = CashPosition(
            depot="789", currentCy="USD", cash_account_id="cash789", type="cash"
        )
        name, number = _resolve_cash_account_identity(pos, [])
        self.assertEqual(name, "USD Account ...789")
        self.assertIsNone(number)

    def test_cash_identity_unsettled_suffix_truncates_to_40_chars(self):
        pos = CashPosition(
            depot="AWARDS",
            cash_account_id="VERYLONGAWARDACCOUNTIDENTIFIER",
            currentCy="USD",
            is_unsettled_balance=True,
            type="cash",
        )
        name, _ = _resolve_cash_account_identity(pos, [])
        self.assertLessEqual(len(name), 40)
        self.assertTrue(name.endswith(" (Unsettled)"))

    # --- _resolve_security_depot_display_name ---

    def test_security_depot_unique_match(self):
        settings = [
            SchwabAccountSettings(
                account_number="CH999-123",
                account_name_alias="sec_main",
                **self.default_settings_args,
            )
        ]
        self.assertEqual(
            _resolve_security_depot_display_name("123", settings), "CH999-123"
        )

    def test_security_depot_no_match_falls_back_to_dots(self):
        settings = [
            SchwabAccountSettings(
                account_number="CH999-000",
                account_name_alias="sec_other",
                **self.default_settings_args,
            )
        ]
        self.assertEqual(
            _resolve_security_depot_display_name("123", settings), "...123"
        )

    def test_security_depot_awards_stays_verbatim(self):
        settings = [
            SchwabAccountSettings(
                account_number="CH999-IGNORE",
                account_name_alias="sec_ignore",
                **self.default_settings_args,
            )
        ]
        self.assertEqual(
            _resolve_security_depot_display_name("AWARDS", settings), "AWARDS"
        )

    # --- _pick_primary_client_number ---

    def test_pick_primary_skips_awards(self):
        settings = [
            SchwabAccountSettings(
                account_number="AWARDS-NUM",
                account_name_alias="awards",
                **self.default_settings_args,
            ),
            SchwabAccountSettings(
                account_number="CH123-FIRST",
                account_name_alias="main",
                **self.default_settings_args,
            ),
            SchwabAccountSettings(
                account_number="CH456-SECOND",
                account_name_alias="secondary",
                **self.default_settings_args,
            ),
        ]
        self.assertEqual(_pick_primary_client_number(settings), "CH123-FIRST")

    def test_pick_primary_all_awards_returns_none(self):
        settings = [
            SchwabAccountSettings(
                account_number="AWARDS-NUM1",
                account_name_alias="awards",
                **self.default_settings_args,
            ),
            SchwabAccountSettings(
                account_number="AWARDS-NUM2",
                account_name_alias="awards",
                **self.default_settings_args,
            ),
        ]
        self.assertIsNone(_pick_primary_client_number(settings))

    def test_pick_primary_empty_settings_returns_none(self):
        self.assertIsNone(_pick_primary_client_number([]))

    def test_pick_primary_no_awards_returns_first(self):
        settings = [
            SchwabAccountSettings(
                account_number="CH123-MAIN",
                account_name_alias="main",
                **self.default_settings_args,
            ),
            SchwabAccountSettings(
                account_number="CH456-ALT",
                account_name_alias="alternative",
                **self.default_settings_args,
            ),
        ]
        self.assertEqual(_pick_primary_client_number(settings), "CH123-MAIN")


class TestSchwabImporterProcessing(unittest.TestCase):

    def test_security_display_name_description_plus_symbol(self):
        pos = SecurityPosition(
            depot="DEPOT1", symbol="MOCKSYM1", description="DESC1", type="security"
        )
        self.assertEqual(_schwab_security_display_name(pos), "DESC1 (MOCKSYM1)")

    def test_security_display_name_symbol_only(self):
        pos = SecurityPosition(
            depot="DEPOT1", symbol="MOCKSYM2", description=None, type="security"
        )
        self.assertEqual(_schwab_security_display_name(pos), "MOCKSYM2")

    def test_transaction_with_multiple_stock_items_does_not_duplicate_payments(self):
        """
        Tests that if TransactionExtractor returns a single transaction with multiple
        SecurityStock items but a single list of SecurityPayment items, these payments
        are not duplicated in the final TaxStatement for the security.
        """
        # 1. Setup mock data
        test_depot_str = "DP1"
        test_symbol = "TESTETF"
        period_from_date = date(2023, 1, 1)
        period_to_date = date(2023, 12, 31)

        # Mock SecurityPosition
        mock_position = SecurityPosition(depot=test_depot_str, symbol=test_symbol, type="security")

        # Mock SecurityStock items (multiple)
        mock_stock_item_1_balance = SecurityStock(
            referenceDate=period_from_date,
            mutation=False, # This is a balance
            balanceCurrency="CHF",
            quotationType="PIECE",
            quantity=Decimal('10'),
            name="Opening Balance Lot"
        )
        # This item from the transaction should represent a change or a different lot
        # If it's a different lot existing at the same time, the total starting balance would be sum.
        # For simplicity and consistency, let's make the second item a mutation.
        mock_stock_item_2_mutation = SecurityStock(
            referenceDate=period_from_date, # Same day as balance, but mutation
            mutation=True, # This is a mutation
            balanceCurrency="CHF",
            quotationType="PIECE",
            quantity=Decimal('20'), # e.g., an acquisition of 20 more
            name="Acquired Lot on same day"
        )
        # TransactionExtractor returns a list of stocks related to the transaction.
        # Let's assume the transaction resulted in the acquisition.
        # The initial_stocks list for PositionReconciler will combine this with StatementExtractor's data.
        mock_transaction_stocks_list = [mock_stock_item_2_mutation]
    
        # Mock SecurityPayment items (a list of unique payments)
        # Ensure all required fields for SecurityPayment are present.
        # Required: paymentDate, quotationType, quantity, amountCurrency
        mock_payment_1 = SecurityPayment(
            name="Dividend Payment 1",
            paymentDate=date(2023, 6, 15),
            amountCurrency="CHF", 
            quotationType="PIECE", 
            quantity=Decimal('1'), # Example quantity for payment
            amount=Decimal("50.00"), # Optional, but good for testing
            grossRevenueB=Decimal("50.00") # Optional
        )
        mock_payment_2 = SecurityPayment(
            name="Interest Payment 1",
            paymentDate=date(2023, 7, 20),
            amountCurrency="CHF", 
            quotationType="PIECE", 
            quantity=Decimal('1'), # Example
            amount=Decimal("25.00"), # Optional
            grossRevenueB=Decimal("25.00") # Optional
        )
        mock_payments_list = [mock_payment_1, mock_payment_2]

        # Mock return value for TransactionExtractor.extract_transactions
        # (position, stocks, payments, depot, (start_date, end_date))
        mock_transaction_data = [
            (mock_position, mock_transaction_stocks_list, mock_payments_list, test_depot_str, (period_from_date, period_to_date))
        ]

        # 2. Patch TransactionExtractor and depot_position_dates
        with patch('opensteuerauszug.importers.schwab.schwab_importer.TransactionExtractor') as MockTransactionExtractor:
            mock_extractor_instance = MockTransactionExtractor.return_value
            mock_extractor_instance.extract_transactions.return_value = mock_transaction_data

            # Patch StatementExtractor.extract_positions to return a dummy statement for the same depot and date
            # This should be the starting balance before the transaction's effects.
            dummy_positions_pdf = [
                (mock_position, mock_stock_item_1_balance)
            ]
            dummy_depot_pdf = test_depot_str
            dummy_open_date_pdf = period_from_date
            # Use a date that ensures this statement is considered for initial balance
            dummy_close_date_plus1_pdf = period_from_date
            with patch('opensteuerauszug.importers.schwab.schwab_importer.StatementExtractor') as MockStatementExtractor:
                mock_statement_instance = MockStatementExtractor.return_value
                mock_statement_instance.extract_positions.return_value = (dummy_positions_pdf, dummy_open_date_pdf, dummy_close_date_plus1_pdf, dummy_depot_pdf)

                # Provide a setting for DP1 to resolve correctly
                importer_settings = [
                    SchwabAccountSettings(account_number="DP1", account_name_alias="dp1_alias", broker_name="schwab", canton="ZH", full_name="Test User")
                ]
                importer = SchwabImporter(period_from=period_from_date, period_to=period_to_date, account_settings_list=importer_settings)
                tax_statement = importer.import_files(['dummy.json', 'dummy.pdf'])

                # 4. Assertions
                self.assertIsNotNone(tax_statement)
                self.assertIsNotNone(tax_statement.listOfSecurities, "listOfSecurities should not be None")
                
                # Explicit if check to help linter with type narrowing
                if tax_statement.listOfSecurities is not None:
                    list_of_securities = tax_statement.listOfSecurities
                    self.assertEqual(len(list_of_securities.depot), 1, "Should be one depot") # type: ignore

                    depot_data = list_of_securities.depot[0] # type: ignore
                    self.assertIsNotNone(depot_data.depotNumber, "Depot number should not be None")
                    # DepotNumber is a str subclass, can be compared directly or cast to str
                    self.assertEqual(depot_data.depotNumber, test_depot_str)

                    self.assertEqual(len(depot_data.security), 1, "Should be one security entry for TESTETF")

                    security_entry = depot_data.security[0]
                    self.assertEqual(security_entry.symbol, test_symbol) # Test symbol is populated
                    self.assertEqual(security_entry.securityName, test_symbol) # Assuming no description for this mock

                    # Key Assertion: Check the number of payments
                    self.assertIsNotNone(security_entry.payment, "Payments list should not be None")
                    self.assertEqual(len(security_entry.payment), len(mock_payments_list),
                                     f"Expected {len(mock_payments_list)} payments, but got {len(security_entry.payment)}. Payments found: {security_entry.payment}")
                else:
                    # This else block should not be reached if the assertIsNotNone above works
                    self.fail("tax_statement.listOfSecurities was None after assertIsNotNone, which is unexpected.") # type: ignore

    def test_statement_date_one_day_after_range_is_accepted(self):
        """
        Tests that a statement date exactly one day after the covered range is accepted.
        """
        test_depot_str = "DP2"
        test_symbol = "TESTETF2"
        period_from_date = date(2023, 1, 1)
        period_to_date = date(2023, 12, 31)
        covered_range_end = period_to_date
        statement_date = covered_range_end + timedelta(days=1)

        # Mock SecurityPosition
        mock_position = SecurityPosition(depot=test_depot_str, symbol=test_symbol, type="security")
        mock_stock_item = SecurityStock(
            referenceDate=period_from_date,
            mutation=False,
            balanceCurrency="CHF",
            quotationType="PIECE",
            quantity=Decimal('10'),
            name="Test Stock Lot"
        )
        mock_stocks_list = [mock_stock_item]
        mock_payments_list = []
        mock_transaction_data = [
            (mock_position, mock_stocks_list, mock_payments_list, test_depot_str, (period_from_date, period_to_date))
        ]
        with patch('opensteuerauszug.importers.schwab.schwab_importer.TransactionExtractor') as MockTransactionExtractor:
            mock_extractor_instance = MockTransactionExtractor.return_value
            mock_extractor_instance.extract_transactions.return_value = mock_transaction_data
            # Patch StatementExtractor.extract_positions to return a statement date one day after the range
            dummy_positions = [(mock_position, mock_stock_item)]
            dummy_depot = test_depot_str
            dummy_open_date = period_from_date
            dummy_close_date_plus1 = statement_date
            with patch('opensteuerauszug.importers.schwab.schwab_importer.StatementExtractor') as MockStatementExtractor:
                mock_statement_instance = MockStatementExtractor.return_value
                mock_statement_instance.extract_positions.return_value = (dummy_positions, dummy_open_date, dummy_close_date_plus1, dummy_depot)
                # Provide a setting for DP2 to resolve correctly, though this test isn't about the name itself
                importer_settings = [
                    SchwabAccountSettings(account_number="DP2", account_name_alias="dp2_alias", broker_name="schwab", canton="ZH", full_name="Test User")
                ]
                importer = SchwabImporter(period_from=period_from_date, period_to=period_to_date, account_settings_list=importer_settings)
                # Should not raise
                tax_statement = importer.import_files(['dummy.json', 'dummy.pdf'])
                self.assertIsNotNone(tax_statement)

    def test_mutation_only_security_history_does_not_fail_initial_reconciliation(self):
        test_depot_str = "DP3"
        period_from_date = date(2025, 1, 1)
        period_to_date = date(2025, 12, 31)

        vt_pos = SecurityPosition(depot=test_depot_str, symbol="VT", type="security")
        vt_buy = SecurityStock(
            referenceDate=date(2025, 11, 19),
            mutation=True,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("10"),
            name="Buy",
        )
        vt_transfer_out = SecurityStock(
            referenceDate=date(2025, 12, 1),
            mutation=True,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("-10"),
            name="Transfer (Shares)",
        )
        mock_transaction_data = [
            (vt_pos, [vt_buy, vt_transfer_out], None, test_depot_str, (period_from_date, period_to_date))
        ]

        # Provide at least one statement date in range for depot coverage validation,
        # without providing a VT balance snapshot.
        statement_pos = SecurityPosition(depot=test_depot_str, symbol="QQQ", type="security")
        statement_stock = SecurityStock(
            referenceDate=period_from_date,
            mutation=False,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("1"),
            name="Opening Balance",
        )
        statement_result = ([(statement_pos, statement_stock)], period_from_date, period_from_date, test_depot_str)

        with patch('opensteuerauszug.importers.schwab.schwab_importer.TransactionExtractor') as MockTransactionExtractor:
            mock_extractor_instance = MockTransactionExtractor.return_value
            mock_extractor_instance.extract_transactions.return_value = mock_transaction_data

            with patch('opensteuerauszug.importers.schwab.schwab_importer.StatementExtractor') as MockStatementExtractor:
                mock_statement_instance = MockStatementExtractor.return_value
                mock_statement_instance.extract_positions.return_value = statement_result

                importer_settings = [
                    SchwabAccountSettings(account_number="DP3", account_name_alias="dp3_alias", broker_name="schwab", canton="ZH", full_name="Test User")
                ]
                importer = SchwabImporter(period_from=period_from_date, period_to=period_to_date, account_settings_list=importer_settings, strict_consistency=True)
                tax_statement = importer.import_files(['dummy.json', 'dummy.pdf'])

        self.assertIsNotNone(tax_statement)
        self.assertIsNotNone(tax_statement.listOfSecurities)
        assert tax_statement.listOfSecurities is not None

        vt_securities = [
            sec
            for depot in tax_statement.listOfSecurities.depot
            for sec in depot.security
            if sec.symbol == "VT"
        ]
        self.assertEqual(len(vt_securities), 1)
        vt_stock_quantities = [stock.quantity for stock in vt_securities[0].stock]
        self.assertIn(Decimal("-10"), vt_stock_quantities)

class TestNextBusinessDay(unittest.TestCase):
    """Unit tests for the next_business_day / settlement_date helpers."""

    def test_monday_to_tuesday(self):
        self.assertEqual(next_business_day(date(2025, 12, 29)), date(2025, 12, 30))  # Mon → Tue

    def test_friday_to_monday(self):
        self.assertEqual(next_business_day(date(2025, 12, 26)), date(2025, 12, 29))  # Fri → Mon

    def test_saturday_to_monday(self):
        self.assertEqual(next_business_day(date(2025, 12, 27)), date(2025, 12, 29))  # Sat → Mon

    def test_sunday_to_monday(self):
        self.assertEqual(next_business_day(date(2025, 12, 28)), date(2025, 12, 29))  # Sun → Mon

    def test_wednesday_before_new_years_skips_holiday(self):
        # Dec 31 2025 is a Wednesday; Jan 1 2026 is a NYSE holiday (New Year's Day)
        # so the next trading day is Jan 2 2026 (Friday)
        self.assertEqual(next_business_day(date(2025, 12, 31)), date(2026, 1, 2))   # Wed → Fri (skip holiday)

    def test_christmas_eve_skips_christmas(self):
        # Dec 24 2025 is a Wednesday; Dec 25 is a NYSE holiday (Christmas)
        # so the next trading day is Dec 26 2025 (Friday)
        self.assertEqual(next_business_day(date(2025, 12, 24)), date(2025, 12, 26))  # Wed → Fri (skip holiday)

    def test_day_before_thanksgiving_skips_holiday(self):
        # Thanksgiving 2025 is Nov 27 (Thursday); next trading day after Nov 26 is Nov 28 (Friday)
        self.assertEqual(next_business_day(date(2025, 11, 26)), date(2025, 11, 28))  # Wed → Fri (skip holiday)

    def test_regular_trading_day_not_affected(self):
        # Jan 2 2025 is a regular Thursday trading day
        self.assertEqual(next_business_day(date(2025, 1, 2)), date(2025, 1, 3))     # Thu → Fri

    def test_settlement_date_aliases_next_business_day(self):
        d = date(2025, 12, 30)
        self.assertEqual(settlement_date(d), next_business_day(d))


class TestSplitUnsettledCash(unittest.TestCase):
    """Unit tests for split_unsettled_cash."""

    def _bal(self, d: str, qty: str) -> SecurityStock:
        return SecurityStock(
            referenceDate=date.fromisoformat(d),
            mutation=False,
            quantity=Decimal(qty),
            balanceCurrency="USD",
            quotationType="PIECE",
        )

    def _mut(self, d: str, qty: str, requires_settlement: bool = True) -> SecurityStock:
        """Create a trade cash mutation (requires_settlement=True by default)."""
        return SecurityStock(
            referenceDate=date.fromisoformat(d),
            mutation=True,
            quantity=Decimal(qty),
            balanceCurrency="USD",
            quotationType="PIECE",
            requires_settlement=requires_settlement,
        )

    def test_no_mutations(self):
        stocks = [self._bal("2025-01-01", "0"), self._bal("2026-01-01", "0")]
        settled, unsettled = split_unsettled_cash(stocks, date(2025, 12, 31))
        self.assertEqual(len(settled), 2)
        self.assertEqual(len(unsettled), 0)

    def test_settled_trade_before_period_end(self):
        # Dec 29 (Mon) trade settles Dec 30 (Tue) ≤ Dec 31 → settled
        stocks = [self._bal("2025-01-01", "0"), self._mut("2025-12-29", "500"), self._bal("2026-01-01", "500")]
        settled, unsettled = split_unsettled_cash(stocks, date(2025, 12, 31))
        self.assertEqual(len(unsettled), 0)
        self.assertEqual(len(settled), 3)

    def test_unsettled_trade_on_period_end_weekday(self):
        # Dec 31 2025 is a Wednesday; settlement is Jan 2 2026 (skip Jan 1 NYSE holiday) > Dec 31 → unsettled
        stocks = [self._bal("2025-01-01", "0"), self._mut("2025-12-31", "1000"), self._bal("2026-01-01", "0")]
        settled, unsettled = split_unsettled_cash(stocks, date(2025, 12, 31))
        self.assertEqual(len(unsettled), 1)
        self.assertEqual(unsettled[0].quantity, Decimal("1000"))

    def test_split_mixed(self):
        stocks = [
            self._bal("2025-01-01", "0"),
            self._mut("2025-12-29", "500"),   # settles Dec 30 — settled
            self._mut("2025-12-31", "1000"),  # settles Jan 2 2026 (skip Jan 1 holiday) — unsettled
            self._bal("2026-01-01", "500"),
        ]
        settled, unsettled = split_unsettled_cash(stocks, date(2025, 12, 31))
        self.assertEqual(len(settled), 3)   # opening bal + Dec29 mutation + closing bal
        self.assertEqual(len(unsettled), 1)  # Dec31 mutation
        self.assertEqual(unsettled[0].referenceDate, date(2025, 12, 31))

    def test_non_trade_mutation_never_unsettled(self):
        """A mutation without requires_settlement=True (e.g. dividend, interest) is
        always placed in the settled bucket even if it occurs on the last day."""
        dividend = self._mut("2025-12-31", "50", requires_settlement=False)
        stocks = [self._bal("2025-01-01", "0"), dividend, self._bal("2026-01-01", "50")]
        settled, unsettled = split_unsettled_cash(stocks, date(2025, 12, 31))
        self.assertEqual(len(unsettled), 0)
        self.assertEqual(len(settled), 3)

    def test_balance_entries_always_settled(self):
        """Balance (non-mutation) entries always go to the settled bucket."""
        stocks = [self._bal("2025-12-31", "999")]
        settled, unsettled = split_unsettled_cash(stocks, date(2025, 12, 31))
        self.assertEqual(len(settled), 1)
        self.assertEqual(len(unsettled), 0)

    def test_intra_period_checkpoint_shifts_date(self):
        """A trade on the last day of a quarterly period (Sep 30) settles Oct 1.
        The Oct 1 balance snapshot (Q3 close_date_plus1) does NOT yet include it,
        so split_unsettled_cash must shift the mutation's referenceDate to Oct 1
        (settlement date) so it appears AFTER the Oct 1 balance checkpoint in the
        reconciler's sorted sequence.  The trade is NOT put in the unsettled bucket."""
        # Q3 close: Oct 1 balance present; period ends Dec 31
        q3_close = self._bal("2025-10-01", "1000")  # Q3 settled balance (no T+1)
        q4_close = self._bal("2026-01-01", "1500")  # year-end balance (includes settlement)
        trade = self._mut("2025-09-30", "500")       # settles Oct 1 — intra-period unsettled
        stocks = [q3_close, trade, q4_close]

        settled, unsettled = split_unsettled_cash(stocks, date(2025, 12, 31))

        self.assertEqual(len(unsettled), 0, "Intra-period unsettled trade must NOT go to separate account")
        self.assertEqual(len(settled), 3)
        # The trade's referenceDate must have been shifted to the settlement date (Oct 1)
        mutations = [s for s in settled if s.mutation]
        self.assertEqual(len(mutations), 1)
        self.assertEqual(mutations[0].referenceDate, date(2025, 10, 1),
                         "Trade referenceDate must be shifted to settlement date (Oct 1)")

    def test_settled_trade_always_shifted_to_settlement_date(self):
        """ALL T+1 mutations are unconditionally re-dated to settlement_date.
        A Sep 29 trade settles Sep 30; even though Sep 30 < Oct 1 checkpoint,
        the referenceDate is still shifted to Sep 30 (cash moves on settlement day)."""
        q3_close = self._bal("2025-10-01", "1500")
        trade = self._mut("2025-09-29", "500")  # settles Sep 30
        stocks = [q3_close, trade]

        settled, unsettled = split_unsettled_cash(stocks, date(2025, 12, 31))

        self.assertEqual(len(unsettled), 0)
        mutations = [s for s in settled if s.mutation]
        self.assertEqual(mutations[0].referenceDate, date(2025, 9, 30),
                         "referenceDate must be shifted to settlement date (Sep 30)")


class TestUnsettledCashAccountGeneration(unittest.TestCase):
    """End-to-end tests for the unsettled cash account generation."""

    def _make_importer_with_mocks(self, mock_tx, mock_stmt, settings=None):
        """Helper that sets up the mock patching and returns the tax statement."""
        period_from = date(2025, 1, 1)
        period_to = date(2025, 12, 31)
        if settings is None:
            settings = [SchwabAccountSettings(
                account_number="AWARDS", account_name_alias="awards_alias",
                broker_name="schwab", canton="ZH", full_name="Test User"
            )]
        with patch('opensteuerauszug.importers.schwab.schwab_importer.TransactionExtractor') as MockTX:
            MockTX.return_value.extract_transactions.return_value = mock_tx
            with patch('opensteuerauszug.importers.schwab.schwab_importer.StatementExtractor') as MockStmt:
                MockStmt.return_value.extract_positions.return_value = mock_stmt
                importer = SchwabImporter(
                    period_from=period_from,
                    period_to=period_to,
                    account_settings_list=settings,
                    strict_consistency=True,
                )
                return importer.import_files(['dummy.json', 'dummy.pdf'])

    def test_unsettled_trade_creates_separate_account(self):
        """A trade on Dec 31 (settles Jan 1) should produce two accounts:
        one settled (PDF balance = $0) and one unsettled ($1000)."""
        period_from = date(2025, 1, 1)
        period_to = date(2025, 12, 31)
        depot = "AWARDS"
        cash_pos = CashPosition(depot=depot, currentCy="USD", cash_account_id="GOOG")

        opening = SecurityStock(referenceDate=period_from, mutation=False, quantity=Decimal("0"),
                                balanceCurrency="USD", quotationType="PIECE")
        sale = SecurityStock(referenceDate=period_to, mutation=True, quantity=Decimal("1000"),
                             balanceCurrency="USD", quotationType="PIECE", name="Sale proceeds",
                             requires_settlement=True)
        # PDF reports $0 because trade hasn't settled
        closing_pdf = SecurityStock(referenceDate=period_to + timedelta(days=1), mutation=False,
                                    quantity=Decimal("0"), balanceCurrency="USD", quotationType="PIECE")

        mock_tx = [(cash_pos, [sale], [], depot, (period_from, period_to))]
        mock_stmt = ([(cash_pos, opening), (cash_pos, closing_pdf)],
                     period_from, period_to + timedelta(days=1), depot)

        tax_stmt = self._make_importer_with_mocks(mock_tx, mock_stmt)
        accounts = tax_stmt.listOfBankAccounts.bankAccount

        self.assertEqual(len(accounts), 2, "Expected main + unsettled account")

        # Identify settled vs unsettled account by balance
        balances = {a.taxValue.balance for a in accounts if a.taxValue}
        self.assertIn(Decimal("0"), balances)     # settled (PDF) account
        self.assertIn(Decimal("1000"), balances)  # unsettled account

        # The unsettled account name should contain "(Unsettled)"
        names = [str(a.bankAccountName) for a in accounts]
        self.assertTrue(any("Unsettled" in n for n in names),
                        f"Expected one name to contain 'Unsettled', got: {names}")

    def test_fully_settled_trade_no_unsettled_account(self):
        """A trade on Dec 29 (settles Dec 30) should NOT produce an unsettled account."""
        period_from = date(2025, 1, 1)
        period_to = date(2025, 12, 31)
        depot = "AWARDS"
        cash_pos = CashPosition(depot=depot, currentCy="USD", cash_account_id="GOOG")

        opening = SecurityStock(referenceDate=period_from, mutation=False, quantity=Decimal("0"),
                                balanceCurrency="USD", quotationType="PIECE")
        # Dec 29 is a Monday; settlement = Dec 30 ≤ Dec 31 → fully settled
        sale = SecurityStock(referenceDate=date(2025, 12, 29), mutation=True, quantity=Decimal("500"),
                             balanceCurrency="USD", quotationType="PIECE", requires_settlement=True)
        # PDF correctly shows $500 (trade settled by year-end)
        closing_pdf = SecurityStock(referenceDate=period_to + timedelta(days=1), mutation=False,
                                    quantity=Decimal("500"), balanceCurrency="USD", quotationType="PIECE")

        mock_tx = [(cash_pos, [sale], [], depot, (period_from, period_to))]
        mock_stmt = ([(cash_pos, opening), (cash_pos, closing_pdf)],
                     period_from, period_to + timedelta(days=1), depot)

        tax_stmt = self._make_importer_with_mocks(mock_tx, mock_stmt)
        accounts = tax_stmt.listOfBankAccounts.bankAccount

        self.assertEqual(len(accounts), 1, "Expected only the main account (no unsettled)")
        self.assertFalse(any("Unsettled" in str(a.bankAccountName) for a in accounts))

    def test_unsettled_account_name_for_awards(self):
        """The unsettled account for an awards position is named 'Equity Awards X (Unsettled)'."""
        period_from = date(2025, 1, 1)
        period_to = date(2025, 12, 31)
        depot = "AWARDS"
        cash_pos = CashPosition(depot=depot, currentCy="USD", cash_account_id="MSFT")

        opening = SecurityStock(referenceDate=period_from, mutation=False, quantity=Decimal("0"),
                                balanceCurrency="USD", quotationType="PIECE")
        # Dec 31 trade (Wed) settles Jan 1 → unsettled
        sale = SecurityStock(referenceDate=date(2025, 12, 31), mutation=True, quantity=Decimal("200"),
                             balanceCurrency="USD", quotationType="PIECE", requires_settlement=True)
        closing_pdf = SecurityStock(referenceDate=period_to + timedelta(days=1), mutation=False,
                                    quantity=Decimal("0"), balanceCurrency="USD", quotationType="PIECE")

        mock_tx = [(cash_pos, [sale], [], depot, (period_from, period_to))]
        mock_stmt = ([(cash_pos, opening), (cash_pos, closing_pdf)],
                     period_from, period_to + timedelta(days=1), depot)

        tax_stmt = self._make_importer_with_mocks(mock_tx, mock_stmt)
        accounts = tax_stmt.listOfBankAccounts.bankAccount

        unsettled_names = [str(a.bankAccountName) for a in accounts if "Unsettled" in str(a.bankAccountName)]
        self.assertEqual(len(unsettled_names), 1)
        self.assertIn("Equity Awards MSFT", unsettled_names[0])
        self.assertIn("Unsettled", unsettled_names[0])

    def test_multiple_unsettled_trades_merged_into_one_account(self):
        """Multiple unsettled trades at period end → one unsettled account with summed balance."""
        period_from = date(2025, 1, 1)
        period_to = date(2025, 12, 31)
        depot = "AWARDS"
        cash_pos = CashPosition(depot=depot, currentCy="USD", cash_account_id="GOOG")

        opening = SecurityStock(referenceDate=period_from, mutation=False, quantity=Decimal("0"),
                                balanceCurrency="USD", quotationType="PIECE")
        # Two unsettled trades on Dec 31 (Wed → settles Jan 1)
        sale1 = SecurityStock(referenceDate=date(2025, 12, 31), mutation=True, quantity=Decimal("600"),
                              balanceCurrency="USD", quotationType="PIECE", requires_settlement=True)
        sale2 = SecurityStock(referenceDate=date(2025, 12, 31), mutation=True, quantity=Decimal("400"),
                              balanceCurrency="USD", quotationType="PIECE", requires_settlement=True)
        closing_pdf = SecurityStock(referenceDate=period_to + timedelta(days=1), mutation=False,
                                    quantity=Decimal("0"), balanceCurrency="USD", quotationType="PIECE")

        mock_tx = [(cash_pos, [sale1, sale2], [], depot, (period_from, period_to))]
        mock_stmt = ([(cash_pos, opening), (cash_pos, closing_pdf)],
                     period_from, period_to + timedelta(days=1), depot)

        tax_stmt = self._make_importer_with_mocks(mock_tx, mock_stmt)
        accounts = tax_stmt.listOfBankAccounts.bankAccount

        self.assertEqual(len(accounts), 2)
        unsettled_accounts = [a for a in accounts if a.taxValue and a.taxValue.balance == Decimal("1000")]
        self.assertEqual(len(unsettled_accounts), 1, "Both unsettled trades should sum to 1000 in one account")


if __name__ == '__main__':
    unittest.main()
