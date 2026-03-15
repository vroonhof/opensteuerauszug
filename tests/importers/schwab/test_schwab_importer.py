import unittest
from unittest.mock import MagicMock, patch
from datetime import date, datetime, timedelta
from decimal import Decimal

from opensteuerauszug.importers.schwab.schwab_importer import SchwabImporter, convert_security_positions_to_list_of_securities
from opensteuerauszug.importers.schwab.transaction_extractor import TransactionExtractor # Assuming path
from opensteuerauszug.model.ech0196 import (
    TaxStatement,
    SecurityPayment,
    SecurityStock,
    CurrencyId,      # This is an Annotated[str, ...]
    QuotationType,   # This is a Literal["PIECE", "PERCENT"]
    DepotNumber,     # This is class DepotNumber(str)
    Security,        # Added Security for asserting results
    ListOfSecurities # Added for type hint
    # Import other necessary eCH-0196 models if needed for constructing test data
)
from opensteuerauszug.model.position import SecurityPosition
# Assuming your models are Pydantic, otherwise adjust instantiation

from opensteuerauszug.importers.schwab.schwab_importer import _get_configured_account_info, create_tax_statement_from_positions
from opensteuerauszug.config.models import SchwabAccountSettings
from opensteuerauszug.model.ech0196 import ClientNumber # Import ClientNumber for assertions


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

from opensteuerauszug.importers.schwab.schwab_importer import convert_cash_positions_to_list_of_bank_accounts
from opensteuerauszug.model.position import CashPosition
from opensteuerauszug.model.ech0196 import BankAccountNumber, BankAccountName, ListOfBankAccounts, Depot # Depot needed for DepotNumber


class TestSchwabImporterAccountResolution(unittest.TestCase):
    def setUp(self):
        self.default_settings_args = {"broker_name": "schwab", "canton": "ZH", "full_name": "Test User"}
        self.mock_stock_item = SecurityStock(
            referenceDate=date(2023,1,1),
            mutation=False,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal(10)
        )
        self.mock_security_stock_item = SecurityStock(
            referenceDate=date(2023,1,1),
            mutation=False,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal(10),
            name="Mock Security Stock"
        )
        self.period_to_date = date(2023, 12, 31)

    # --- BankAccountNumber Tests ---
    def test_bank_account_number_unique_match(self):
        settings = [
            SchwabAccountSettings(account_number="CH123-789", account_name_alias="main", **self.default_settings_args)
        ]
        cash_pos = CashPosition(depot="789", currentCy="USD", cash_account_id="cash789", type="cash") # cash_account_id is mandatory
        cash_tuples = [(cash_pos, [self.mock_stock_item], [])]

        result_list: ListOfBankAccounts = convert_cash_positions_to_list_of_bank_accounts(cash_tuples, self.period_to_date, settings)

        self.assertIsNotNone(result_list.bankAccount)
        self.assertEqual(len(result_list.bankAccount), 1)
        self.assertEqual(result_list.bankAccount[0].bankAccountNumber, BankAccountNumber("CH123-789"))

    def test_bank_account_number_no_match(self):
        settings = [
            SchwabAccountSettings(account_number="CH123-000", account_name_alias="other", **self.default_settings_args)
        ]
        cash_pos = CashPosition(depot="789", currentCy="USD", cash_account_id="cash789", type="cash")
        cash_tuples = [(cash_pos, [self.mock_stock_item], [])]

        result_list: ListOfBankAccounts = convert_cash_positions_to_list_of_bank_accounts(cash_tuples, self.period_to_date, settings)

        self.assertIsNotNone(result_list.bankAccount)
        self.assertEqual(len(result_list.bankAccount), 1)
        self.assertIsNone(result_list.bankAccount[0].bankAccountNumber)  # No configured account number
        self.assertEqual(result_list.bankAccount[0].bankAccountName, BankAccountName("USD Account ...789"))

    def test_bank_account_number_awards(self):
        settings = [
             SchwabAccountSettings(account_number="CH123-IGNORE", account_name_alias="main_ignore", **self.default_settings_args)
        ] # Settings should be ignored for awards
        cash_pos = CashPosition(depot="AWARDS", cash_account_id="AWARD123", currentCy="USD", type="cash")
        cash_tuples = [(cash_pos, [self.mock_stock_item], [])]

        result_list: ListOfBankAccounts = convert_cash_positions_to_list_of_bank_accounts(cash_tuples, self.period_to_date, settings)

        self.assertIsNotNone(result_list.bankAccount)
        self.assertEqual(len(result_list.bankAccount), 1)
        self.assertIsNone(result_list.bankAccount[0].bankAccountNumber)  # No configured account number for awards
        self.assertEqual(result_list.bankAccount[0].bankAccountName, BankAccountName("Equity Awards AWARD123"))

    def test_bank_account_number_empty_settings(self):
        settings = []
        cash_pos = CashPosition(depot="789", currentCy="USD", cash_account_id="cash789", type="cash")
        cash_tuples = [(cash_pos, [self.mock_stock_item], [])]

        result_list: ListOfBankAccounts = convert_cash_positions_to_list_of_bank_accounts(cash_tuples, self.period_to_date, settings)

        self.assertIsNotNone(result_list.bankAccount)
        self.assertEqual(len(result_list.bankAccount), 1)
        self.assertIsNone(result_list.bankAccount[0].bankAccountNumber)  # No configured account number
        self.assertEqual(result_list.bankAccount[0].bankAccountName, BankAccountName("USD Account ...789"))

    # --- Depot.depotNumber Tests ---
    def test_security_depot_number_unique_match(self):
        settings = [
            SchwabAccountSettings(account_number="CH999-123", account_name_alias="sec_main", **self.default_settings_args)
        ]
        sec_pos = SecurityPosition(depot="123", symbol="TEST", description="Test Security", type="security")
        # Ensure stock has required fields: referenceDate, mutation, quotationType, quantity, balanceCurrency
        security_tuples = [(sec_pos, [self.mock_security_stock_item], [])]

        result_list: ListOfSecurities = convert_security_positions_to_list_of_securities(security_tuples, settings)

        self.assertIsNotNone(result_list.depot)
        self.assertEqual(len(result_list.depot), 1)
        # DepotNumber is a class that subclasses str, direct comparison might work or cast to str
        self.assertEqual(result_list.depot[0].depotNumber, DepotNumber("CH999-123"))


    def test_security_depot_number_no_match(self):
        settings = [
            SchwabAccountSettings(account_number="CH999-000", account_name_alias="sec_other", **self.default_settings_args)
        ]
        sec_pos = SecurityPosition(depot="123", symbol="TEST", description="Test Security", type="security")
        security_tuples = [(sec_pos, [self.mock_security_stock_item], [])]

        result_list: ListOfSecurities = convert_security_positions_to_list_of_securities(security_tuples, settings)

        self.assertIsNotNone(result_list.depot)
        self.assertEqual(len(result_list.depot), 1)
        self.assertEqual(result_list.depot[0].depotNumber, DepotNumber("...123"))

    def test_security_depot_number_awards(self):
        settings = [
            SchwabAccountSettings(account_number="CH999-IGNORE", account_name_alias="sec_ignore", **self.default_settings_args)
        ] # Settings should be ignored
        sec_pos = SecurityPosition(depot="AWARDS", symbol="AWARDSEC", description="Award Security", type="security")
        security_tuples = [(sec_pos, [self.mock_security_stock_item], [])]

        result_list: ListOfSecurities = convert_security_positions_to_list_of_securities(security_tuples, settings)

        self.assertIsNotNone(result_list.depot)
        self.assertEqual(len(result_list.depot), 1)
        self.assertEqual(result_list.depot[0].depotNumber, DepotNumber("AWARDS"))

    # --- TaxStatement.clientID Tests ---
    def test_tax_statement_client_id_first_non_awards(self):
        settings = [
            SchwabAccountSettings(account_number="AWARDS-NUM", account_name_alias="awards", **self.default_settings_args),
            SchwabAccountSettings(account_number="CH123-FIRST", account_name_alias="main", **self.default_settings_args),
            SchwabAccountSettings(account_number="CH456-SECOND", account_name_alias="secondary", **self.default_settings_args)
        ]
        statement: TaxStatement = create_tax_statement_from_positions(
            security_tuples=[],
            cash_tuples=[],
            period_from=date(2023,1,1),
            period_to=self.period_to_date,
            tax_period=2023,
            account_settings_list=settings
        )
        self.assertEqual(len(statement.client), 1)
        self.assertEqual(statement.client[0].clientNumber, ClientNumber("CH123-FIRST"))

    def test_tax_statement_client_id_only_awards(self):
        settings = [
            SchwabAccountSettings(account_number="AWARDS-NUM1", account_name_alias="awards", **self.default_settings_args),
            SchwabAccountSettings(account_number="AWARDS-NUM2", account_name_alias="AWARDS_alias", **self.default_settings_args)
            # Note: "AWARDS_alias" will also be treated as an awards alias due to .lower() check
        ]
        # Re-create one with explicit "awards" to be sure, as the previous comment might be slightly off
        # if the check is strictly 'alias.lower() == "awards"' vs 'alias.lower().contains("awards")'
        # The current implementation is setting.account_name_alias.lower() != "awards"
        # So "AWARDS_alias".lower() != "awards" is true. Let's make one explicitly "awards".
        settings_strict_awards = [
            SchwabAccountSettings(account_number="AWARDS-NUM1", account_name_alias="awards", **self.default_settings_args),
            SchwabAccountSettings(account_number="AWARDS-NUM2", account_name_alias="awards", **self.default_settings_args)
        ]
        statement: TaxStatement = create_tax_statement_from_positions(
            [], [], date(2023,1,1), self.period_to_date, 2023, settings_strict_awards
        )
        self.assertEqual(len(statement.client), 0)

    def test_tax_statement_client_id_empty_settings(self):
        settings = []
        statement: TaxStatement = create_tax_statement_from_positions(
            [], [], date(2023,1,1), self.period_to_date, 2023, settings
        )
        self.assertEqual(len(statement.client), 0)

    def test_tax_statement_client_id_no_awards_present(self):
        settings = [
            SchwabAccountSettings(account_number="CH123-MAIN", account_name_alias="main", **self.default_settings_args),
            SchwabAccountSettings(account_number="CH456-ALT", account_name_alias="alternative", **self.default_settings_args)
        ]
        statement: TaxStatement = create_tax_statement_from_positions(
            [], [], date(2023,1,1), self.period_to_date, 2023, settings
        )
        self.assertEqual(len(statement.client), 1)
        self.assertEqual(statement.client[0].clientNumber, ClientNumber("CH123-MAIN"))


class TestSchwabImporterProcessing(unittest.TestCase):

    def test_convert_security_positions_populates_symbol(self):
        """
        Tests that `convert_security_positions_to_list_of_securities`
        correctly populates the `symbol` and `securityName` fields in the
        resulting Security objects.
        """
        depot1_str = "DEPOT1"
        # Case 1: Symbol and Description present
        pos1 = SecurityPosition(depot=depot1_str, symbol="MOCKSYM1", description="DESC1", type="security")
        stock1 = SecurityStock(referenceDate=date(2023,1,1), mutation=False, balanceCurrency="USD", quotationType="PIECE", quantity=Decimal(10))

        # Case 2: Symbol present, Description is None
        pos2 = SecurityPosition(depot=depot1_str, symbol="MOCKSYM2", description=None, type="security")
        stock2 = SecurityStock(referenceDate=date(2023,1,1), mutation=False, balanceCurrency="EUR", quotationType="PERCENT", quantity=Decimal(100))

        security_tuples = [
            (pos1, [stock1], []),
            (pos2, [stock2], []),
        ]
        # Provide an empty list for account_settings_list for this existing test
        settings_for_test = []
        list_of_securities: ListOfSecurities = convert_security_positions_to_list_of_securities(security_tuples, settings_for_test)

        self.assertIsNotNone(list_of_securities)
        self.assertEqual(len(list_of_securities.depot), 1)
        # The depot name will now be "...DEPOT1" due to no matching settings.
        # This test was about symbol and securityName, not depot name resolution.
        # To keep the original assertion for depot name, we'd need to add a setting.
        # For now, let's adjust the expectation or accept the new default.
        # Given the test name, it's better to make it pass with minimal changes if depot name isn't its focus.
        # However, to be robust, let's provide a setting that resolves it as it was.
        settings_for_test_resolved = [
             SchwabAccountSettings(account_number="DEPOT1", account_name_alias="test_depot1", broker_name="schwab", canton="ZH", full_name="Test User")
        ]
        list_of_securities_resolved: ListOfSecurities = convert_security_positions_to_list_of_securities(security_tuples, settings_for_test_resolved)

        # Using the resolved list for assertions below
        self.assertIsNotNone(list_of_securities_resolved)
        self.assertEqual(len(list_of_securities_resolved.depot), 1)
        depot = list_of_securities_resolved.depot[0]

        self.assertEqual(depot.depotNumber, depot1_str) # This should now pass
        self.assertEqual(len(depot.security), 2)

        # Assertions for pos1
        sec1 = depot.security[0]
        self.assertEqual(sec1.symbol, "MOCKSYM1")
        self.assertEqual(sec1.securityName, "DESC1 (MOCKSYM1)")
        self.assertEqual(sec1.currency, "USD") # Check a few other fields for sanity
        self.assertEqual(sec1.quotationType, "PIECE")

        # Assertions for pos2
        sec2 = depot.security[1]
        self.assertEqual(sec2.symbol, "MOCKSYM2")
        self.assertEqual(sec2.securityName, "MOCKSYM2") # No description, so just symbol
        self.assertEqual(sec2.currency, "EUR")
        self.assertEqual(sec2.quotationType, "PERCENT")

    def test_convert_security_positions_assigns_unique_position_ids(self):
        """Ensure generated Security objects have unique positionId values."""
        depot_str = "DEPOT1"
        # Use the same symbol for both positions to ensure uniqueness does not
        # depend on the symbol value.
        pos1 = SecurityPosition(depot=depot_str, symbol="DUPL", description="DESC1", type="security")
        stock1 = SecurityStock(referenceDate=date(2023, 1, 1), mutation=False,
                               balanceCurrency="USD", quotationType="PIECE", quantity=Decimal(1))

        pos2 = SecurityPosition(depot=depot_str, symbol="DUPL", description="DESC2", type="security")
        stock2 = SecurityStock(referenceDate=date(2023, 1, 2), mutation=False,
                               balanceCurrency="USD", quotationType="PIECE", quantity=Decimal(2))

        security_tuples = [
            (pos1, [stock1], []),
            (pos2, [stock2], [])
        ]

        result = convert_security_positions_to_list_of_securities(security_tuples, [])
        self.assertIsNotNone(result.depot)
        self.assertEqual(len(result.depot), 1)
        depot = result.depot[0]
        ids = [s.positionId for s in depot.security]
        self.assertEqual(len(ids), len(set(ids)), "positionId values must be unique")

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

    def test_unsettled_cash_adjustment_perfect_match(self):
        """Test that a $0.00 PDF cash balance is correctly adjusted when a recent trade exactly explains the discrepancy."""
        test_depot_str = "AWARDS"
        period_from_date = date(2025, 1, 1)
        period_to_date = date(2025, 12, 31)

        cash_pos = CashPosition(depot=test_depot_str, currentCy="USD", cash_account_id="GOOG")

        # Sale on Dec 31 generates $1000 cash
        cash_sale_tx = SecurityStock(
            referenceDate=date(2025, 12, 31),
            mutation=True,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("1000.00"),
            name="Sale Proceeds"
        )

        # PDF on Jan 1 reports $0 (trade hadn't settled)
        opening_balance = SecurityStock(
            referenceDate=date(2025, 1, 1),
            mutation=False,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("0.00"),
            name="Opening Balance"
        )
        pdf_balance = SecurityStock(
            referenceDate=date(2026, 1, 1),
            mutation=False,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("0.00"),
            name=None
        )

        mock_transaction_data = [
            (cash_pos, [cash_sale_tx], [], test_depot_str, (period_from_date, period_to_date))
        ]
        statement_result = ([(cash_pos, opening_balance), (cash_pos, pdf_balance)], period_from_date, period_to_date + timedelta(days=1), test_depot_str)

        with patch('opensteuerauszug.importers.schwab.schwab_importer.TransactionExtractor') as MockTransactionExtractor:
            mock_extractor_instance = MockTransactionExtractor.return_value
            mock_extractor_instance.extract_transactions.return_value = mock_transaction_data

            with patch('opensteuerauszug.importers.schwab.schwab_importer.StatementExtractor') as MockStatementExtractor:
                mock_statement_instance = MockStatementExtractor.return_value
                mock_statement_instance.extract_positions.return_value = statement_result

                importer_settings = [
                    SchwabAccountSettings(account_number="AWARDS", account_name_alias="awards_alias", broker_name="schwab", canton="ZH", full_name="Test User")
                ]
                
                importer = SchwabImporter(period_from=period_from_date, period_to=period_to_date, account_settings_list=importer_settings, strict_consistency=True)
                tax_statement = importer.import_files(['dummy.json', 'dummy.pdf'])

        self.assertIsNotNone(tax_statement)
        bank_accounts = tax_statement.listOfBankAccounts.bankAccount
        self.assertEqual(len(bank_accounts), 1)
        self.assertEqual(bank_accounts[0].taxValue.balance, Decimal("1000.00"))


    def test_unsettled_cash_adjustment_across_year_end(self):
        """Test that a trade on Dec 30 with $0 PDF balance is correctly adjusted."""
        test_depot_str = "AWARDS"
        period_from_date = date(2025, 1, 1)
        period_to_date = date(2025, 12, 31)

        cash_pos = CashPosition(depot=test_depot_str, currentCy="USD", cash_account_id="GOOG")

        cash_sale_tx = SecurityStock(
            referenceDate=date(2025, 12, 30),
            mutation=True,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("1000.00"),
            name="Sale Proceeds",
        )
        
        # PDF on Jan 1 reports $0 (trade settled after Jan 1 due to holiday)
        opening_balance = SecurityStock(
            referenceDate=date(2025, 1, 1),
            mutation=False,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("0.00"),
            name="Opening Balance"
        )
        pdf_balance = SecurityStock(
            referenceDate=date(2026, 1, 1),
            mutation=False,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("0.00"),
            name=None
        )

        mock_transaction_data = [
            (cash_pos, [cash_sale_tx], [], test_depot_str, (period_from_date, period_to_date))
        ]
        statement_result = ([(cash_pos, opening_balance), (cash_pos, pdf_balance)], period_from_date, period_to_date + timedelta(days=1), test_depot_str)

        with patch('opensteuerauszug.importers.schwab.schwab_importer.TransactionExtractor') as MockTransactionExtractor:
            mock_extractor_instance = MockTransactionExtractor.return_value
            mock_extractor_instance.extract_transactions.return_value = mock_transaction_data

            with patch('opensteuerauszug.importers.schwab.schwab_importer.StatementExtractor') as MockStatementExtractor:
                mock_statement_instance = MockStatementExtractor.return_value
                mock_statement_instance.extract_positions.return_value = statement_result

                importer_settings = [
                    SchwabAccountSettings(account_number="AWARDS", account_name_alias="awards_alias", broker_name="schwab", canton="ZH", full_name="Test User")
                ]
                
                importer = SchwabImporter(period_from=period_from_date, period_to=period_to_date, account_settings_list=importer_settings, strict_consistency=True)
                tax_statement = importer.import_files(['dummy.json', 'dummy.pdf'])

        self.assertIsNotNone(tax_statement)
        bank_accounts = tax_statement.listOfBankAccounts.bankAccount
        self.assertEqual(len(bank_accounts), 1)
        self.assertEqual(bank_accounts[0].taxValue.balance, Decimal("1000.00"))

    def test_unsettled_cash_adjustment_settled_before_year_end(self):
        """Test that a trade settled before year-end has no discrepancy (PDF includes it)."""
        test_depot_str = "AWARDS"
        period_from_date = date(2025, 1, 1)
        period_to_date = date(2025, 12, 31)

        cash_pos = CashPosition(depot=test_depot_str, currentCy="USD", cash_account_id="GOOG")

        cash_sale_tx = SecurityStock(
            referenceDate=date(2025, 12, 28),
            mutation=True,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("1000.00"),
            name="Sale Proceeds",
        )
        
        # PDF balance already includes the $1000 because it settled before Dec 31
        opening_balance = SecurityStock(
            referenceDate=date(2025, 1, 1),
            mutation=False,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("0.00"),
            name="Opening Balance"
        )
        pdf_balance = SecurityStock(
            referenceDate=date(2026, 1, 1),
            mutation=False,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("1000.00"),
            name=None
        )

        mock_transaction_data = [
            (cash_pos, [cash_sale_tx], [], test_depot_str, (period_from_date, period_to_date))
        ]
        statement_result = ([(cash_pos, opening_balance), (cash_pos, pdf_balance)], period_from_date, period_to_date + timedelta(days=1), test_depot_str)

        with patch('opensteuerauszug.importers.schwab.schwab_importer.TransactionExtractor') as MockTransactionExtractor:
            mock_extractor_instance = MockTransactionExtractor.return_value
            mock_extractor_instance.extract_transactions.return_value = mock_transaction_data

            with patch('opensteuerauszug.importers.schwab.schwab_importer.StatementExtractor') as MockStatementExtractor:
                mock_statement_instance = MockStatementExtractor.return_value
                mock_statement_instance.extract_positions.return_value = statement_result

                importer_settings = [
                    SchwabAccountSettings(account_number="AWARDS", account_name_alias="awards_alias", broker_name="schwab", canton="ZH", full_name="Test User")
                ]
                
                importer = SchwabImporter(period_from=period_from_date, period_to=period_to_date, account_settings_list=importer_settings, strict_consistency=True)
                tax_statement = importer.import_files(['dummy.json', 'dummy.pdf'])

        self.assertIsNotNone(tax_statement)
        bank_accounts = tax_statement.listOfBankAccounts.bankAccount
        self.assertEqual(len(bank_accounts), 1)
        # No adjustment needed — settled trade is already in PDF
        self.assertEqual(bank_accounts[0].taxValue.balance, Decimal("1000.00"))


    def test_unsettled_cash_adjustment_genuine_mismatch_fails(self):
        """Test that when the discrepancy can't be explained by recent trades, reconciliation fails."""
        test_depot_str = "AWARDS"
        period_from_date = date(2025, 1, 1)
        period_to_date = date(2025, 12, 31)

        cash_pos = CashPosition(depot=test_depot_str, currentCy="USD", cash_account_id="GOOG")

        # Sale generated $1000
        cash_sale_tx = SecurityStock(
            referenceDate=date(2025, 12, 31),
            mutation=True,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("1000.00"),
            name="Sale"
        )

        opening_balance = SecurityStock(
            referenceDate=date(2025, 1, 1),
            mutation=False,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("0.00"),
            name="Opening Balance"
        )

        # PDF reports $50 — discrepancy is -950, but the only recent trade is $1000.
        # $1000 ≠ 950, so this can't be explained by unsettled trades.
        pdf_balance = SecurityStock(
            referenceDate=date(2026, 1, 1),
            mutation=False,
            balanceCurrency="USD",
            quotationType="PIECE",
            quantity=Decimal("50.00"),
            name=None
        )

        mock_transaction_data = [(cash_pos, [cash_sale_tx], [], test_depot_str, (period_from_date, period_to_date))]
        statement_result = ([(cash_pos, opening_balance), (cash_pos, pdf_balance)], period_from_date, period_to_date + timedelta(days=1), test_depot_str)

        with patch('opensteuerauszug.importers.schwab.schwab_importer.TransactionExtractor') as MockTransactionExtractor:
            mock_extractor_instance = MockTransactionExtractor.return_value
            mock_extractor_instance.extract_transactions.return_value = mock_transaction_data

            with patch('opensteuerauszug.importers.schwab.schwab_importer.StatementExtractor') as MockStatementExtractor:
                mock_statement_instance = MockStatementExtractor.return_value
                mock_statement_instance.extract_positions.return_value = statement_result

                importer_settings = [SchwabAccountSettings(account_number="AWARDS", account_name_alias="awards_alias", broker_name="schwab", canton="ZH", full_name="Test User")]
                
                importer = SchwabImporter(period_from=period_from_date, period_to=period_to_date, account_settings_list=importer_settings, strict_consistency=True)
                
                with self.assertRaises(ValueError) as context:
                    importer.import_files(['dummy.json', 'dummy.pdf'])
                
                self.assertIn("Position reconciliation failed", str(context.exception))


class TestSchwabImporterBankAccountNames(unittest.TestCase):
    """Test that bank account names are always set for all bank accounts."""

    def setUp(self):
        self.default_settings_args = {"broker_name": "schwab", "canton": "ZH", "full_name": "Test User"}
        self.period_to_date = date(2023, 12, 31)

    def test_bank_account_names_always_set_with_configured_accounts(self):
        """Test that bank account names are set when accounts are configured."""
        settings = [
            SchwabAccountSettings(account_number="CH123-456789", account_name_alias="main", **self.default_settings_args)
        ]
        
        # Create cash positions
        cash_pos1 = CashPosition(depot="456789", currentCy="USD", cash_account_id="cash456789", type="cash")
        cash_pos2 = CashPosition(depot="456789", currentCy="EUR", cash_account_id="cash456789_eur", type="cash")
        
        # Create stock items for each position
        stock1 = SecurityStock(
            referenceDate=date(2024, 1, 1),  # day after period
            mutation=False,
            quotationType="PIECE", 
            quantity=Decimal(1000),
            balanceCurrency='USD'
        )
        stock2 = SecurityStock(
            referenceDate=date(2024, 1, 1),  # day after period
            mutation=False,
            quotationType="PIECE",
            quantity=Decimal(500),
            balanceCurrency='EUR'
        )
        
        cash_tuples = [
            (cash_pos1, [stock1], []),
            (cash_pos2, [stock2], [])
        ]

        result = convert_cash_positions_to_list_of_bank_accounts(cash_tuples, self.period_to_date, settings)

        # Verify that all bank accounts have names set
        assert len(result.bankAccount) == 2
        for bank_account in result.bankAccount:
            assert bank_account.bankAccountName is not None
            assert bank_account.bankAccountName != ""
            
        # For configured accounts, the name should be the full account number
        usd_account = next(ba for ba in result.bankAccount if ba.bankAccountCurrency == "USD")
        eur_account = next(ba for ba in result.bankAccount if ba.bankAccountCurrency == "EUR")
        
        assert usd_account.bankAccountName == "CH123-456789"
        assert eur_account.bankAccountName == "CH123-456789"
        
        # Bank account numbers should be set for configured accounts
        assert usd_account.bankAccountNumber == "CH123-456789"
        assert eur_account.bankAccountNumber == "CH123-456789"

    def test_bank_account_names_always_set_without_configured_accounts(self):
        """Test that bank account names are set even when no accounts are configured."""
        settings = []  # No configured accounts
        
        cash_pos = CashPosition(depot="999888", currentCy="USD", cash_account_id="cash999888", type="cash")
        stock = SecurityStock(
            referenceDate=date(2024, 1, 1),
            mutation=False,
            quotationType="PIECE",
            quantity=Decimal(750),
            balanceCurrency='USD'
        )
        
        cash_tuples = [(cash_pos, [stock], [])]

        result = convert_cash_positions_to_list_of_bank_accounts(cash_tuples, self.period_to_date, settings)

        # Verify bank account has name set
        assert len(result.bankAccount) == 1
        bank_account = result.bankAccount[0]
        
        assert bank_account.bankAccountName is not None
        assert bank_account.bankAccountName != ""
        
        # For unconfigured accounts, the name should follow the pattern "USD Account ...999888"
        assert bank_account.bankAccountName == "USD Account ...999888"
        
        # Bank account number should be None for unconfigured accounts
        assert bank_account.bankAccountNumber is None

    def test_bank_account_names_always_set_for_awards(self):
        """Test that bank account names are set for awards accounts."""
        settings = [
            SchwabAccountSettings(account_number="CH999-IGNORE", account_name_alias="main", **self.default_settings_args)
        ]  # Settings should be ignored for awards
        
        cash_pos = CashPosition(depot="AWARDS", cash_account_id="AWARD789", currentCy="USD", type="cash")
        stock = SecurityStock(
            referenceDate=date(2024, 1, 1),
            mutation=False,
            quotationType="PIECE",
            quantity=Decimal(100),
            balanceCurrency='USD'
        )
        
        cash_tuples = [(cash_pos, [stock], [])]

        result = convert_cash_positions_to_list_of_bank_accounts(cash_tuples, self.period_to_date, settings)

        # Verify bank account has name set
        assert len(result.bankAccount) == 1
        bank_account = result.bankAccount[0]
        
        assert bank_account.bankAccountName is not None
        assert bank_account.bankAccountName != ""
        
        # For awards accounts, the name should follow the pattern "Equity Awards <award_id>"
        assert bank_account.bankAccountName == "Equity Awards AWARD789"
        
        # Bank account number should be None for awards (no configured account number)
        assert bank_account.bankAccountNumber is None

    def test_unsettled_cash_adjustment_multi_mismatch(self):
        """Test that multiple sweep lags in different periods are both resolved."""
        test_depot_str = "AWARDS"
        period_from_date = date(2025, 1, 1)
        period_to_date = date(2025, 12, 31)
        cash_pos = CashPosition(depot=test_depot_str, currentCy="USD", cash_account_id="GOOG", type="cash")

        # Sale 1 near mid-year boundary (Sep 30)
        sale1 = SecurityStock(referenceDate=date(2025, 9, 30), mutation=True, quantity=Decimal("1000.00"), balanceCurrency="USD", quotationType="PIECE")
        # Sale 2 near year-end (Dec 31)
        sale2 = SecurityStock(referenceDate=date(2025, 12, 31), mutation=True, quantity=Decimal("2000.00"), balanceCurrency="USD", quotationType="PIECE")

        # Oct 1st balance reports 0 (Sale 1 unsettled)
        opening = SecurityStock(referenceDate=date(2025, 1, 1), mutation=False, quantity=Decimal("0"), balanceCurrency="USD", quotationType="PIECE")
        oct_bal = SecurityStock(referenceDate=date(2025, 10, 1), mutation=False, quantity=Decimal("0"), balanceCurrency="USD", quotationType="PIECE")
        # Jan 1st balance reports 1000 (Sale 2 unsettled, Sale 1 settled)
        jan_bal = SecurityStock(referenceDate=date(2026, 1, 1), mutation=False, quantity=Decimal("1000.00"), balanceCurrency="USD", quotationType="PIECE")

        mock_tx = [(cash_pos, [sale1, sale2], [], test_depot_str, (period_from_date, period_to_date))]
        mock_stmt = ([(cash_pos, opening), (cash_pos, oct_bal), (cash_pos, jan_bal)], period_from_date, date(2026, 1, 1), test_depot_str)

        with patch("opensteuerauszug.importers.schwab.schwab_importer.TransactionExtractor") as MockTX, patch(
            "opensteuerauszug.importers.schwab.schwab_importer.StatementExtractor"
        ) as MockStmt:
            MockTX.return_value.extract_transactions.return_value = mock_tx
            MockStmt.return_value.extract_positions.return_value = mock_stmt
            importer = SchwabImporter(
                period_from=period_from_date, period_to=period_to_date, account_settings_list=[], strict_consistency=True
            )
            # Use import_dir directly or ensure we pass a file list that triggers it
            tax_statement = importer.import_files(["dummy.json", "dummy.pdf"])

        self.assertIsNotNone(tax_statement)
        # Final balance should be 1000 + 2000 = 3000
        # If the adjustment worked, both mismatches were resolved.
        bank_accounts = tax_statement.listOfBankAccounts.bankAccount
        self.assertEqual(len(bank_accounts), 1)
        self.assertEqual(bank_accounts[0].taxValue.balance, Decimal("3000.00"))

    def test_unsettled_cash_adjustment_extended_window(self):
        """Test that a 7-day lag is resolved by the 10-day window."""
        test_depot_str = "AWARDS"
        period_from_date = date(2025, 1, 1)
        period_to_date = date(2025, 12, 31)
        cash_pos = CashPosition(depot=test_depot_str, currentCy="USD", cash_account_id="GOOG", type="cash")

        # Sale on Sep 27 (4 days before oct 1)
        sale = SecurityStock(referenceDate=date(2025, 9, 27), mutation=True, quantity=Decimal("500.00"), balanceCurrency="USD", quotationType="PIECE")
        opening = SecurityStock(referenceDate=date(2025, 1, 1), mutation=False, quantity=Decimal("0"), balanceCurrency="USD", quotationType="PIECE")
        oct_bal = SecurityStock(referenceDate=date(2025, 10, 1), mutation=False, quantity=Decimal("0"), balanceCurrency="USD", quotationType="PIECE")
        closing = SecurityStock(referenceDate=date(2026, 1, 1), mutation=False, quantity=Decimal("500.00"), balanceCurrency="USD", quotationType="PIECE")

        mock_tx = [(cash_pos, [sale], [], test_depot_str, (period_from_date, period_to_date))]
        mock_stmt = ([(cash_pos, opening), (cash_pos, oct_bal), (cash_pos, closing)], period_from_date, date(2026, 1, 1), test_depot_str)

        with patch("opensteuerauszug.importers.schwab.schwab_importer.TransactionExtractor") as MockTX, patch(
            "opensteuerauszug.importers.schwab.schwab_importer.StatementExtractor"
        ) as MockStmt:
            MockTX.return_value.extract_transactions.return_value = mock_tx
            MockStmt.return_value.extract_positions.return_value = mock_stmt
            importer = SchwabImporter(
                period_from=period_from_date, period_to=period_to_date, account_settings_list=[], strict_consistency=True
            )
            # We use dummy names that match the mock setup
            tax_statement = importer.import_files(["dummy.json", "dummy.pdf"])

        self.assertIsNotNone(tax_statement)
        self.assertEqual(tax_statement.listOfBankAccounts.bankAccount[0].taxValue.balance, Decimal("500.00"))


if __name__ == "__main__":
    unittest.main()
