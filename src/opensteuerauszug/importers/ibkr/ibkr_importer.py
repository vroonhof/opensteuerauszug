import os
from typing import List, Any
from datetime import date
from decimal import Decimal, InvalidOperation
from collections import defaultdict

from opensteuerauszug.model.position import SecurityPosition, CashPosition, Position # Added Position
from opensteuerauszug.model.ech0196 import (
    TaxStatement, ListOfSecurities, ListOfBankAccounts, # Added ListOfSecurities, ListOfBankAccounts
    Security, SecurityStock, SecurityPayment,
    BankAccount, BankAccountPayment, BankAccountTaxValue,
    CurrencyId, QuotationType, DepotNumber, BankAccountNumber # Added DepotNumber, BankAccountNumber
)
from opensteuerauszug.config.models import IbkrAccountSettings # This will be created later

# Attempt to import ibflex and handle if it's not installed
try:
    from ibflex import parser as ibflex_parser
    from ibflex.error import FlexParserError
    IBFLEX_AVAILABLE = True
except ImportError:
    IBFLEX_AVAILABLE = False
    # Define dummy classes if ibflex is not available to prevent NameErrors later
    # This allows the rest of the application to load even if ibflex is missing,
    # though the importer itself will not function.
    class ibflex_parser: # type: ignore
        @staticmethod
        def parse(filename):
            raise RuntimeError("ibflex library is not installed. Please install it to use the IBKR importer.")

    class FlexParserError(Exception): # type: ignore
        pass


class IbkrImporter:
    """
    Imports Interactive Brokers account data for a given tax period from Flex Query XML files.
    """
    def _get_required_field(self, data_object, field_name: str, object_description: str) -> Any:
        """Helper to get a required field or raise ValueError if missing."""
        value = getattr(data_object, field_name, None)
        if value is None:
            error_desc = object_description # Use the passed in description
            if hasattr(data_object, 'symbol'):
                error_desc = f"{object_description} (Symbol: {getattr(data_object, 'symbol', 'N/A')})"
            elif hasattr(data_object, 'accountId') and not ('Account:' in object_description): # Avoid double "Account:"
                error_desc = f"{object_description} (Account: {getattr(data_object, 'accountId', 'N/A')})"
            raise ValueError(f"Missing required field '{field_name}' in {error_desc}.")
        if isinstance(value, str) and not value.strip():
            error_desc = object_description # Use the passed in description
            if hasattr(data_object, 'symbol'):
                error_desc = f"{object_description} (Symbol: {getattr(data_object, 'symbol', 'N/A')})"
            elif hasattr(data_object, 'accountId') and not ('Account:' in object_description):
                 error_desc = f"{object_description} (Account: {getattr(data_object, 'accountId', 'N/A')})"
            raise ValueError(f"Empty required field '{field_name}' in {error_desc}.")
        return value

    def _to_decimal(self, value: Any, field_name: str, object_description: str) -> Decimal:
        """Converts a value to Decimal, raising ValueError on failure."""
        if value is None: # Should be caught by _get_required_field if it was required
            raise ValueError(f"Cannot convert None to Decimal for field '{field_name}' in {object_description}")
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise ValueError(f"Invalid value for Decimal conversion: '{value}' for field '{field_name}' in {object_description}")

    def __init__(self,
                 period_from: date,
                 period_to: date,
                 account_settings_list: List[IbkrAccountSettings]):
        """
        Initialize the importer with a tax period defined by a start and end date.

        Args:
            period_from (date): The start date of the tax period.
            period_to (date): The end date of the tax period.
            account_settings_list (List[IbkrAccountSettings]): List of IBKR account settings.
        """
        self.period_from = period_from
        self.period_to = period_to
        self.account_settings_list = account_settings_list

        if not IBFLEX_AVAILABLE:
            # This check could also be done in the CLI or application entry point
            # when selecting the importer, to provide a cleaner error to the user.
            print("CRITICAL: ibflex library is not installed. IbkrImporter will not function.")
            # Depending on desired behavior, could raise an error here too.

        if not self.account_settings_list:
            print("Warning: IbkrImporter initialized with an empty list of account settings.")
        # else:
            # print(f"IbkrImporter initialized. Primary account (if used): {self.account_settings_list[0].account_id}")


    def import_files(self, filenames: List[str]) -> TaxStatement:
        """
        Import data from a list of IBKR Flex Query XML filenames and return a TaxStatement.

        Args:
            filenames (List[str]): List of file paths to import (XML).

        Returns:
            TaxStatement: The imported tax statement.
        """
        if not IBFLEX_AVAILABLE:
            raise RuntimeError("ibflex library is not installed. Cannot import IBKR Flex statements.")

        all_flex_statements = []

        for filename in filenames:
            if not os.path.exists(filename):
                raise FileNotFoundError(f"IBKR Flex statement file not found: {filename}")
            if not filename.lower().endswith(".xml"):
                print(f"Warning: Skipping non-XML file: {filename}")
                continue

            try:
                print(f"Parsing IBKR Flex statement: {filename}")
                response = ibflex_parser.parse(filename)
                # response.FlexStatements is a list of FlexStatement objects
                # Each FlexStatement corresponds to an account within the report period
                if response and response.FlexStatements:
                    for stmt in response.FlexStatements:
                        # TODO: Potentially filter by accountId if multiple accounts are in one file
                        # and account_settings_list specifies which one to process.
                        # For now, we'll accumulate all statements found.
                        print(f"Successfully parsed statement for account: {stmt.accountId}, Period: {stmt.fromDate} to {stmt.toDate}")
                        all_flex_statements.append(stmt)
                else:
                    print(f"Warning: No FlexStatements found in {filename} or response was empty.")
            except FlexParserError as e:
                raise ValueError(f"Failed to parse IBKR Flex XML file {filename} with ibflex: {e}")
            except Exception as e:
                # Catch other potential errors during parsing, e.g., file corruption not caught by FlexParserError
                raise RuntimeError(f"An unexpected error occurred while parsing {filename}: {e}")

        if not all_flex_statements:
            # This might be an error or just a case of no relevant data.
            # For now, we'll return an empty/minimal statement.
            # The issue states "If data is missing do a hard error", so this might need adjustment
            print("Warning: No Flex statements were successfully parsed. Returning empty TaxStatement.")
            return TaxStatement(
                minorVersion=1, periodFrom=self.period_from, periodTo=self.period_to,
                taxPeriod=self.period_from.year, listOfSecurities=None, listOfBankAccounts=None
            )

        # Using defaultdict to store lists of stocks and payments per position
        # Key: SecurityPosition object (for securities) or a tuple for cash accounts
        # Value: dict with 'stocks': [], 'payments': []
        processed_security_positions = defaultdict(lambda: {'stocks': [], 'payments': []})
        processed_cash_positions = defaultdict(lambda: {'stocks': [], 'payments': []}) # 'stocks' for cash are BankAccountTaxValue-like entries if needed

        account_id_processed = "UNKNOWN_ACCOUNT" # Fallback if no statements

        for stmt in all_flex_statements:
            account_id = self._get_required_field(stmt, 'accountId', 'FlexStatement')
            account_id_processed = account_id # Keep track of the last processed account ID for summary
            print(f"Processing statement for account: {account_id}")

            # --- Process Trades ---
            if stmt.Trades:
                for trade in stmt.Trades:
                    trade_date = self._get_required_field(trade, 'tradeDate', 'Trade')
                    settle_date = self._get_required_field(trade, 'settleDateTarget', 'Trade')
                    symbol = self._get_required_field(trade, 'symbol', 'Trade')
                    description = self._get_required_field(trade, 'description', 'Trade')
                    asset_category = self._get_required_field(trade, 'assetCategory', 'Trade')

                    conid = str(self._get_required_field(trade, 'conid', 'Trade'))
                    isin = getattr(trade, 'isin', None) # Optional
                    valor = None # Flex does not typically provide Valor

                    quantity = self._to_decimal(self._get_required_field(trade, 'quantity', 'Trade'), 'quantity', f"Trade {symbol}")
                    trade_price = self._to_decimal(self._get_required_field(trade, 'tradePrice', 'Trade'), 'tradePrice', f"Trade {symbol}")
                    trade_money = self._to_decimal(self._get_required_field(trade, 'tradeMoney', 'Trade'), 'tradeMoney', f"Trade {symbol}")
                    currency = self._get_required_field(trade, 'currency', 'Trade')
                    buy_sell = self._get_required_field(trade, 'buySell', 'Trade') # 'BUY' or 'SELL'

                    ib_commission = self._to_decimal(getattr(trade, 'ibCommission', '0'), 'ibCommission', f"Trade {symbol}")

                    if asset_category not in ["STK", "OPT", "FUT", "BOND", "ETF", "FUND"]: # Added ETF, FUND
                        print(f"Warning: Skipping trade for unhandled asset category: {asset_category} (Symbol: {symbol})")
                        continue

                    sec_pos = SecurityPosition(
                        depot=account_id,
                        valor=valor,
                        isin=isin,
                        symbol=conid,
                        description=f"{description} ({symbol})"
                    )

                    stock_mutation = SecurityStock(
                        referenceDate=trade_date,
                        mutation=True,
                        quantity=quantity,
                        name=f"{buy_sell} {abs(quantity)} {symbol} @ {trade_price} {currency}",
                        balanceCurrency=currency,
                        quotationType="PIECE"
                    )
                    processed_security_positions[sec_pos]['stocks'].append(stock_mutation)

                    payment_amount = trade_money
                    if quantity > 0: # BUY
                        payment_amount = -abs(payment_amount)
                    else: # SELL
                        payment_amount = abs(payment_amount)

                    payment_amount += ib_commission # ib_commission is typically negative

                    trade_payment = SecurityPayment(
                        paymentDate=settle_date,
                        name=f"Trade: {buy_sell} {symbol}",
                        amountCurrency=currency,
                        amount=payment_amount
                    )
                    processed_security_positions[sec_pos]['payments'].append(trade_payment)

            # --- Process Open Positions (End of Period Snapshot) ---
            if stmt.OpenPositions:
                for open_pos in stmt.OpenPositions:
                    report_date = self._get_required_field(open_pos, 'reportDate', 'OpenPosition')
                    symbol = self._get_required_field(open_pos, 'symbol', 'OpenPosition')
                    description = self._get_required_field(open_pos, 'description', 'OpenPosition')
                    asset_category = self._get_required_field(open_pos, 'assetCategory', 'OpenPosition')

                    conid = str(self._get_required_field(open_pos, 'conid', 'OpenPosition'))
                    isin = getattr(open_pos, 'isin', None)
                    valor = None

                    quantity = self._to_decimal(self._get_required_field(open_pos, 'position', 'OpenPosition'), 'position', f"OpenPosition {symbol}")
                    currency = self._get_required_field(open_pos, 'currency', 'OpenPosition')

                    if asset_category not in ["STK", "OPT", "FUT", "BOND", "ETF", "FUND"]: # Added ETF, FUND
                        print(f"Warning: Skipping open position for unhandled asset category: {asset_category} (Symbol: {symbol})")
                        continue

                    sec_pos = SecurityPosition(
                        depot=account_id,
                        valor=valor,
                        isin=isin,
                        symbol=conid,
                        description=f"{description} ({symbol})"
                    )

                    balance_stock = SecurityStock(
                        referenceDate=report_date,
                        mutation=False,
                        quantity=quantity,
                        name=f"End of Period Balance {symbol}",
                        balanceCurrency=currency,
                        quotationType="PIECE"
                    )
                    processed_security_positions[sec_pos]['stocks'].append(balance_stock)

            # --- Process Cash Transactions ---
            if stmt.CashTransactions:
                for cash_tx in stmt.CashTransactions:
                    tx_date_time = self._get_required_field(cash_tx, 'dateTime', 'CashTransaction')
                    tx_date = tx_date_time.date() if hasattr(tx_date_time, 'date') else self._get_required_field(cash_tx, 'tradeDate', 'CashTransaction') # Ensure tx_date is a date object

                    description = self._get_required_field(cash_tx, 'description', 'CashTransaction')
                    amount = self._to_decimal(self._get_required_field(cash_tx, 'amount', 'CashTransaction'), 'amount', f"CashTransaction {description[:30]}")
                    currency = self._get_required_field(cash_tx, 'currency', 'CashTransaction')

                    cash_pos_key = (account_id, currency, "MAIN_CASH")

                    bank_payment = BankAccountPayment(
                        paymentDate=tx_date,
                        name=description,
                        amountCurrency=currency,
                        amount=amount
                    )
                    processed_cash_positions[cash_pos_key]['payments'].append(bank_payment)

        # --- Construct ListOfSecurities ---
        depot_securities_map = defaultdict(list) # account_id -> list of Security objects
        sec_pos_idx = 0
        for sec_pos_obj, data in processed_security_positions.items():
            sec_pos_idx +=1
            sorted_stocks = sorted(data['stocks'], key=lambda s: (s.referenceDate, s.mutation))
            sorted_payments = sorted(data['payments'], key=lambda p: p.paymentDate)

            # Determine currency and quotation type from available stock entries or defaults
            primary_currency = None
            primary_quotation_type = QuotationType.PIECE # Default
            if sorted_stocks:
                # Try to get from a balance entry first, then any entry
                balance_stocks = [s for s in sorted_stocks if not s.mutation and s.balanceCurrency]
                if balance_stocks:
                    primary_currency = balance_stocks[0].balanceCurrency
                    primary_quotation_type = balance_stocks[0].quotationType
                else: # Try any stock
                    primary_currency = sorted_stocks[0].balanceCurrency
                    primary_quotation_type = sorted_stocks[0].quotationType

            if not primary_currency: # Fallback if no stocks or no currency on stocks
                if sorted_payments:
                    primary_currency = sorted_payments[0].amountCurrency
                else:
                    raise ValueError(f"Cannot determine currency for security {sec_pos_obj.symbol} (Desc: {sec_pos_obj.description}). No stocks or payments with currency info.")

            # TODO: Map assetCategory to eCH-0196 SecurityCategory more accurately
            # Attempt to get assetCategory from stock or payment, default to "STK"
            asset_cat_source = None
            if sorted_stocks and hasattr(sorted_stocks[0], 'assetCategory'):
                 asset_cat_source = sorted_stocks[0]
            elif sorted_payments and hasattr(sorted_payments[0], 'assetCategory'): # Payments don't usually have assetCategory
                 asset_cat_source = sorted_payments[0]

            asset_cat = getattr(asset_cat_source, 'assetCategory', 'STK') if asset_cat_source else 'STK'


            sec_category = "SHARE" # Default
            if asset_cat == "BOND":
                sec_category = "BOND"
            elif asset_cat == "OPT":
                sec_category = "OPTION"
            # Add more mappings as needed (e.g. FUND, ETF might map to "FUND" or "SHARE" depending on tax rules)

            sec = Security(
                positionId=str(sec_pos_idx),
                currency=CurrencyId(primary_currency),
                quotationType=primary_quotation_type,
                securityCategory=sec_category,
                securityName=sec_pos_obj.description or sec_pos_obj.symbol,
                isin=sec_pos_obj.isin,
                valor=sec_pos_obj.valor,
                stock=sorted_stocks,
                payment=sorted_payments
            )
            depot_securities_map[sec_pos_obj.depot].append(sec)

        final_depots = []
        if depot_securities_map:
            for depot_id, securities_in_depot in depot_securities_map.items():
                if securities_in_depot:
                    final_depots.append(Depot(depotNumber=DepotNumber(depot_id), security=securities_in_depot))

        list_of_securities = ListOfSecurities(depot=final_depots) if final_depots else None

        # --- Construct ListOfBankAccounts ---
        final_bank_accounts: List[BankAccount] = []
        aggregated_bank_payments = defaultdict(lambda: {'payments': [], 'account_id': None, 'currency': None})

        for (stmt_account_id, currency_code, _), data in processed_cash_positions.items():
            key = (stmt_account_id, currency_code)
            aggregated_bank_payments[key]['payments'].extend(data['payments'])
            aggregated_bank_payments[key]['account_id'] = stmt_account_id
            aggregated_bank_payments[key]['currency'] = currency_code

        for key, data in aggregated_bank_payments.items():
            acc_id = data['account_id']
            curr = data['currency']
            payments = data['payments']

            sorted_payments = sorted(payments, key=lambda p: p.paymentDate)

            closing_balance_value = None
            for s_stmt in all_flex_statements:
                if s_stmt.accountId == acc_id and hasattr(s_stmt, 'CashReport') and s_stmt.CashReport:
                    for cash_report_currency_obj in s_stmt.CashReport:
                        if hasattr(cash_report_currency_obj, 'currency') and cash_report_currency_obj.currency == curr:
                            if hasattr(cash_report_currency_obj, 'endingCash'):
                                closing_balance_value = self._to_decimal(cash_report_currency_obj.endingCash, 'endingCash', f"CashReport {acc_id} {curr}")
                                break
                            elif hasattr(cash_report_currency_obj, 'balance') and hasattr(cash_report_currency_obj, 'reportDate') and cash_report_currency_obj.reportDate == self.period_to :
                                closing_balance_value = self._to_decimal(cash_report_currency_obj.balance, 'balance', f"CashReport {acc_id} {curr}")
                                break
                    if closing_balance_value is not None:
                        break

            bank_account_tax_value_obj = None
            if closing_balance_value is not None:
                 bank_account_tax_value_obj = BankAccountTaxValue(
                    referenceDate=self.period_to,
                    name="Closing Balance",
                    balanceCurrency=CurrencyId(curr),
                    balance=closing_balance_value
                )
            else:
                print(f"Warning: No closing cash balance found in CashReport for account {acc_id}, currency {curr} for date {self.period_to}. BankAccountTaxValue will be missing.")

            bank_account_num_str = f"{acc_id}-{curr}"

            ba = BankAccount(
                bankAccountNumber=BankAccountNumber(bank_account_num_str),
                bankAccountCountry="US",
                bankAccountCurrency=CurrencyId(curr),
                payment=sorted_payments,
                taxValue=[bank_account_tax_value_obj] if bank_account_tax_value_obj else []
            )
            final_bank_accounts.append(ba)

        list_of_bank_accounts = ListOfBankAccounts(bankAccount=final_bank_accounts) if final_bank_accounts else None

        tax_statement = TaxStatement(
            minorVersion=1,
            periodFrom=self.period_from,
            periodTo=self.period_to,
            taxPeriod=self.period_from.year,
            listOfSecurities=list_of_securities,
            listOfBankAccounts=list_of_bank_accounts
        )
        print("Partial TaxStatement created with Trades, OpenPositions, and basic CashTransactions mapping.")
        return tax_statement

if __name__ == '__main__':
    print("IbkrImporter module loaded.")
    if not IBFLEX_AVAILABLE:
        print("ibflex library not available. Run 'pip install ibflex' to use this importer.")
    else:
        print("ibflex library is available.")
    # Example usage:
    # from opensteuerauszug.config.models import IbkrAccountSettings # Create this class
    # settings = IbkrAccountSettings(account_id="U1234567")
    # importer = IbkrImporter(
    #     period_from=date(2023, 1, 1),
    #     period_to=date(2023, 12, 31),
    #     account_settings_list=[settings]
    # )
    #
    # # Create a dummy XML file for testing
    # DUMMY_XML_CONTENT = """
    # <FlexQueryResponse queryName="Test Query" type="AF">
    #   <FlexStatements count="1">
    #     <FlexStatement accountId="U1234567" fromDate="2023-01-01" toDate="2023-12-31" period="Year" whenGenerated="2024-01-15T10:00:00">
    #       <Trades>
    #         <Trade assetCategory="STK" symbol="AAPL" tradeDate="2023-05-10" quantity="10" tradePrice="150.00" currency="USD" />
    #       </Trades>
    #       <CashTransactions>
    #         <CashTransaction type="Deposits/Withdrawals" dateTime="2023-02-01T00:00:00" amount="1000" currency="USD" />
    #       </CashTransactions>
    #       <OpenPositions>
    #         <OpenPosition assetCategory="STK" symbol="MSFT" position="100" markPrice="300" currency="USD" />
    #       </OpenPositions>
    #     </FlexStatement>
    #   </FlexStatements>
    # </FlexQueryResponse>
    # """
    # DUMMY_FILE = "dummy_ibkr_flex.xml"
    # with open(DUMMY_FILE, "w") as f:
    #     f.write(DUMMY_XML_CONTENT)
    #
    # try:
    #     print(f"Attempting to import dummy file: {DUMMY_FILE}")
    #     statement = importer.import_files([DUMMY_FILE])
    #     from devtools import debug
    #     debug(statement)
    #     print("Dummy import successful.")
    # except Exception as e:
    #     print(f"Error during example usage: {e}")
    # finally:
    #     if os.path.exists(DUMMY_FILE):
    #         os.remove(DUMMY_FILE)
    print("Example usage in __main__ needs IbkrAccountSettings to be defined in config.models and 'pip install ibflex devtools'.")
