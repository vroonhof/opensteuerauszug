import os
from typing import Final, List, Any, Dict, Literal
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from collections import defaultdict

from opensteuerauszug.model.position import SecurityPosition
from opensteuerauszug.model.ech0196 import (
    BankAccountName, ClientNumber, Institution, OrganisationName, SecurityCategory, TaxStatement, ListOfSecurities, ListOfBankAccounts,
    Security, SecurityStock, SecurityPayment,
    BankAccount, BankAccountPayment, BankAccountTaxValue,
    CurrencyId, QuotationType, DepotNumber, BankAccountNumber, Depot, ISINType, Client
)
from opensteuerauszug.core.position_reconciler import PositionReconciler
from opensteuerauszug.config.models import IbkrAccountSettings

# Import ibflex components to avoid RuntimeWarning about module loading order
try:
    import ibflex
    from ibflex.parser import FlexParserError
    IBFLEX_AVAILABLE = True
except ImportError:
    IBFLEX_AVAILABLE = False
    
    # Create type-safe placeholders for when ibflex is not available
    class Trade:  # type: ignore
        pass
    
    class MockParser:  # type: ignore
        @staticmethod
        def parse(filename: str):
            raise ImportError("ibflex library is not installed")

class IbkrImporter:
    """
    Imports Interactive Brokers account data for a given tax period
    from Flex Query XML files.
    """
    def _get_required_field(self, data_object: Any, field_name: str,
                              object_description: str) -> Any:
        """Helper to get a required field or raise ValueError if missing."""
        value = getattr(data_object, field_name, None)
        if value is None:
            error_desc = object_description  # Use the passed in description
            if hasattr(data_object, 'symbol'):
                error_desc = (f"{object_description} (Symbol: "
                              f"{getattr(data_object, 'symbol', 'N/A')})")
            elif (hasattr(data_object, 'accountId') and
                  not ('Account:' in object_description)):  # Avoid double "Account:"
                error_desc = (f"{object_description} (Account: "
                              f"{getattr(data_object, 'accountId', 'N/A')})")
            raise ValueError(
                f"Missing required field '{field_name}' in {error_desc}."
            )
        if isinstance(value, str) and not value.strip():
            error_desc = object_description  # Use the passed in description
            if hasattr(data_object, 'symbol'):
                error_desc = (f"{object_description} (Symbol: "
                              f"{getattr(data_object, 'symbol', 'N/A')})")
            elif (hasattr(data_object, 'accountId') and
                  not ('Account:' in object_description)):
                error_desc = (f"{object_description} (Account: "
                              f"{getattr(data_object, 'accountId', 'N/A')})")
            raise ValueError(
                f"Empty required field '{field_name}' in {error_desc}."
            )
        return value

    def _to_decimal(self, value: Any, field_name: str,
                    object_description: str) -> Decimal:
        """Converts a value to Decimal, raising ValueError on failure."""
        if value is None:  # Should be caught by _get_required_field if required
            raise ValueError(
                f"Cannot convert None to Decimal for field '{field_name}' "
                f"in {object_description}"
            )
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise ValueError(
                f"Invalid value for Decimal conversion: '{value}' for field "
                f"'{field_name}' in {object_description}"
            )

    def __init__(self,
                 period_from: date,
                 period_to: date,
                 account_settings_list: List[IbkrAccountSettings]):
        """
        Initialize the importer with a tax period.

        Args:
            period_from (date): The start date of the tax period.
            period_to (date): The end date of the tax period.
            account_settings_list: List of IBKR account settings.
        """
        self.period_from = period_from
        self.period_to = period_to
        self.account_settings_list = account_settings_list

        if not IBFLEX_AVAILABLE:
            # This check could also be done in the CLI or app entry point
            # to provide a cleaner error to the user.
            print(
                "CRITICAL: ibflex library is not installed. "
                "IbkrImporter will not function."
            )
            # Depending on desired behavior, could raise an error here too.

        if not self.account_settings_list:
            print(
                "Warning: IbkrImporter initialized with an empty list of "
                "account settings."
            )
        # else:
            # print(
            #     f"IbkrImporter initialized. Primary account (if used): "
            #     f"{self.account_settings_list[0].account_id}"
            # )

    def _aggregate_stocks_by_date(self, stocks: List[SecurityStock]) -> List[SecurityStock]:
        """Aggregate buy and sell entries on the same date without reordering."""

        aggregated: List[SecurityStock] = []
        pending: SecurityStock | None = None

        for stock in stocks:
            if stock.mutation:
                if (
                    pending
                    and pending.referenceDate == stock.referenceDate
                    and pending.balanceCurrency == stock.balanceCurrency
                    and pending.quotationType == stock.quotationType
                    # test for same sign of quantity
                    and (pending.quantity * stock.quantity) > 0
                ):
                    pending.quantity += stock.quantity
                    if pending.quantity > 0:
                        pending.name = "Buy"
                    else:
                        pending.name = "Sell"
                else:
                    if pending:
                        aggregated.append(pending)
                    pending = SecurityStock(
                        referenceDate=stock.referenceDate,
                        mutation=True,
                        quantity=stock.quantity,
                        name=stock.name,
                        balanceCurrency=stock.balanceCurrency,
                        quotationType=stock.quotationType,
                    )
            else:
                if pending:
                    aggregated.append(pending)
                    pending = None
                aggregated.append(stock)

        if pending:
            aggregated.append(pending)

        return aggregated


    def import_files(self, filenames: List[str]) -> TaxStatement:
        """
        Import data from IBKR Flex Query XMLs and return a TaxStatement.

        Args:
            filenames: List of file paths to import (XML).

        Returns:
            The imported tax statement.
        """
        if not IBFLEX_AVAILABLE:
            raise RuntimeError(
                "ibflex library is not installed. "
                "Cannot import IBKR Flex statements."
            )

        all_flex_statements = []

        for filename in filenames:
            if not os.path.exists(filename):
                raise FileNotFoundError(
                    f"IBKR Flex statement file not found: {filename}"
                )
            if not filename.lower().endswith(".xml"):
                print(f"Warning: Skipping non-XML file: {filename}")
                continue

            try:
                print(f"Parsing IBKR Flex statement: {filename}")
                response = ibflex.parser.parse(filename)
                # response.FlexStatements is a list of FlexStatement objects
                # Each FlexStatement corresponds to an account
                if response and response.FlexStatements:
                    for stmt in response.FlexStatements:
                        # TODO: Potentially filter by accountId if multiple
                        # accounts are in one file and account_settings_list
                        # specifies which one to process.
                        # For now, accumulate all statements found.
                        print(
                            f"Successfully parsed statement for account: "
                            f"{stmt.accountId}, Period: {stmt.fromDate} "
                            f"to {stmt.toDate}"
                        )
                        all_flex_statements.append(stmt)
                else:
                    print(
                        f"Warning: No FlexStatements found in {filename} "
                        "or response was empty."
                    )
            except FlexParserError as e:
                raise ValueError(
                    f"Failed to parse IBKR Flex XML file {filename} "
                    f"with ibflex: {e}"
                )
            except Exception as e:
                # Catch other potential errors during parsing
                raise RuntimeError(
                    f"An unexpected error occurred while parsing "
                    f"{filename}: {e}"
                )

        if not all_flex_statements:
            # This might be an error or just a case of no relevant data.
            # "If data is missing do a hard error" - might need adjustment
            print(
                "Warning: No Flex statements were successfully parsed. "
                "Returning empty TaxStatement."
            )
            return TaxStatement(
                minorVersion=1, periodFrom=self.period_from,
                periodTo=self.period_to,
                taxPeriod=self.period_from.year, listOfSecurities=None,
                listOfBankAccounts=None
            )

        # Key: SecurityPosition or tuple for cash. Value: dict with 'stocks', 'payments'
        processed_security_positions: defaultdict[SecurityPosition, Dict[str, list]] = \
            defaultdict(lambda: {'stocks': [], 'payments': []})
        processed_cash_positions: defaultdict[tuple, Dict[str, list]] = \
            defaultdict(lambda: {'stocks': [], 'payments': []})

        for stmt in all_flex_statements:
            account_id = self._get_required_field(
                stmt, 'accountId', 'FlexStatement'
            )
            # account_id_processed = account_id # Keep track for summary
            print(f"Processing statement for account: {account_id}")

            # --- Process Trades ---
            if stmt.Trades:
                for trade in stmt.Trades:
                    if IBFLEX_AVAILABLE and not isinstance(trade, ibflex.Trade):
                        # Skipping summary objects.
                        # It seems tempting to use SymbolSummary but for FX these
                        # are actually for the full report period, so have no fixed date.
                        continue
                    trade_date = self._get_required_field(
                        trade, 'tradeDate', 'Trade'
                    )
                    settle_date = self._get_required_field(
                        trade, 'settleDateTarget', 'Trade'
                    )
                    symbol = self._get_required_field(trade, 'symbol', 'Trade')
                    description = self._get_required_field(
                        trade, 'description', 'Trade'
                    )
                    asset_category = self._get_required_field(
                        trade, 'assetCategory', 'Trade'
                    )

                    conid = str(self._get_required_field(trade, 'conid', 'Trade'))
                    isin = getattr(trade, 'isin', None)  # Optional
                    valor = None  # Flex does not typically provide Valor

                    quantity = self._to_decimal(
                        self._get_required_field(trade, 'quantity', 'Trade'),
                        'quantity', f"Trade {symbol}"
                    )
                    trade_price = self._to_decimal(
                        self._get_required_field(trade, 'tradePrice', 'Trade'),
                        'tradePrice', f"Trade {symbol}"
                    )
                    trade_money = self._to_decimal(
                        self._get_required_field(trade, 'tradeMoney', 'Trade'),
                        'tradeMoney', f"Trade {symbol}"
                    )
                    currency = self._get_required_field(
                        trade, 'currency', 'Trade'
                    )
                    # 'BUY' or 'SELL'
                    buy_sell = self._get_required_field(trade, 'buySell', 'Trade')

                    ib_commission = self._to_decimal(
                        getattr(trade, 'ibCommission', '0'),
                        'ibCommission', f"Trade {symbol}"
                    )

                    # Added ETF, FUND
                    if asset_category not in [
                        "STK", "OPT", "FUT", "BOND", "ETF", "FUND"
                    ]:
                        print(
                            f"Warning: Skipping trade for unhandled asset "
                            f"category: {asset_category} (Symbol: {symbol})"
                        )
                        continue

                    sec_pos = SecurityPosition(
                        depot=account_id,
                        valor=valor,
                        isin=ISINType(isin) if isin else None,
                        symbol=conid,
                        description=f"{description} ({symbol})"
                    )

                    stock_mutation = SecurityStock(
                        referenceDate=trade_date,
                        mutation=True,
                        quantity=quantity,
                        name=f"{buy_sell} {abs(quantity)} {symbol} "
                             f"@ {trade_price} {currency}",
                        balanceCurrency=currency,
                        quotationType="PIECE"
                    )
                    processed_security_positions[sec_pos]['stocks'].append(
                        stock_mutation
                    )

                    # Cash movements resulting from trades are tracked via the cash transaction section. Only the stock mutation is stored here.

            # --- Process Open Positions (End of Period Snapshot) ---
            if stmt.OpenPositions:
                end_plus_one = self.period_to + timedelta(days=1)
                for open_pos in stmt.OpenPositions:
                    # Ignore the reportDate from the Flex statement and
                    # use period end + 1 as reference date for the balance
                    # entry. This avoids creating a separate stock entry on
                    # the period end itself which would later result in a
                    # duplicate closing balance.
                    _ = self._get_required_field(
                        open_pos, 'reportDate', 'OpenPosition'
                    )  # validation only
                    symbol = self._get_required_field(
                        open_pos, 'symbol', 'OpenPosition'
                    )
                    description = self._get_required_field(
                        open_pos, 'description', 'OpenPosition'
                    )
                    asset_category = self._get_required_field(
                        open_pos, 'assetCategory', 'OpenPosition'
                    )

                    conid = str(self._get_required_field(
                        open_pos, 'conid', 'OpenPosition'
                    ))
                    isin = getattr(open_pos, 'isin', None)
                    valor = None

                    quantity = self._to_decimal(
                        self._get_required_field(open_pos, 'position',
                                                 'OpenPosition'),
                        'position', f"OpenPosition {symbol}"
                    )
                    currency = self._get_required_field(
                        open_pos, 'currency', 'OpenPosition'
                    )

                    # Added ETF, FUND
                    if asset_category not in [
                        "STK", "OPT", "FUT", "BOND", "ETF", "FUND"
                    ]:
                        print(
                            f"Warning: Skipping open position for unhandled "
                            f"asset category: {asset_category} "
                            f"(Symbol: {symbol})"
                        )
                        continue

                    sec_pos = SecurityPosition(
                        depot=account_id,
                        valor=valor,
                        isin=ISINType(isin) if isin else None,
                        symbol=conid,
                        description=f"{description} ({symbol})"
                    )

                    balance_stock = SecurityStock(
                        # Balance as of the period end + 1
                        referenceDate=end_plus_one,
                        mutation=False,
                        quantity=quantity,
                        name=f"End of Period Balance {symbol}",
                        balanceCurrency=currency,
                        quotationType="PIECE"
                    )
                    processed_security_positions[sec_pos]['stocks'].append(
                        balance_stock
                    )

            # --- Process Transfers ---
            if stmt.Transfers:
                for transfer in stmt.Transfers:
                    asset_category = getattr(transfer, 'assetCategory', None)
                    asset_cat_val = getattr(asset_category, 'value', str(asset_category))
                    if str(asset_cat_val).upper() == 'CASH':
                        continue

                    tx_date = getattr(transfer, 'date', None)
                    if tx_date is None:
                        tx_dt = getattr(transfer, 'dateTime', None)
                        if tx_dt is not None:
                            tx_date = tx_dt.date() if hasattr(tx_dt, 'date') else tx_dt
                    if tx_date is None:
                        raise ValueError('Transfer missing date/dateTime')

                    symbol = self._get_required_field(transfer, 'symbol', 'Transfer')
                    description = self._get_required_field(
                        transfer, 'description', 'Transfer'
                    )
                    conid = str(self._get_required_field(transfer, 'conid', 'Transfer'))
                    isin = getattr(transfer, 'isin', None)

                    quantity = self._to_decimal(
                        self._get_required_field(transfer, 'quantity', 'Transfer'),
                        'quantity', f"Transfer {symbol}"
                    )

                    direction = getattr(transfer, 'direction', None)
                    direction_val = (
                        getattr(direction, 'value', str(direction)).upper()
                        if direction
                        else None
                    )
                    if direction_val == 'OUT' and quantity > 0:
                        raise ValueError(
                            f"Transfer direction OUT but quantity {quantity} positive"
                            f" for {symbol}"
                        )
                    if direction_val == 'IN' and quantity < 0:
                        raise ValueError(
                            f"Transfer direction IN but quantity {quantity} negative"
                            f" for {symbol}"
                        )

                    currency = self._get_required_field(
                        transfer, 'currency', 'Transfer'
                    )

                    transfer_type = self._get_required_field(
                        transfer, 'type', 'Transfer'
                    )
                    transfer_type_val = getattr(transfer_type, 'value', str(transfer_type))
                    account = self._get_required_field(transfer, 'account', 'Transfer')

                    sec_pos = SecurityPosition(
                        depot=account_id,
                        valor=None,
                        isin=ISINType(isin) if isin else None,
                        symbol=conid,
                        description=f"{description} ({symbol})",
                    )

                    stock_mutation = SecurityStock(
                        referenceDate=tx_date,
                        mutation=True,
                        quantity=quantity,
                        name=f"{transfer_type_val} {account}",
                        balanceCurrency=currency,
                        quotationType="PIECE",
                    )

                    processed_security_positions[sec_pos]['stocks'].append(
                        stock_mutation
                    )

            # --- Process Cash Transactions ---
            if stmt.CashTransactions:
                for cash_tx in stmt.CashTransactions:
                    tx_date_time = self._get_required_field(
                        cash_tx, 'dateTime', 'CashTransaction'
                    )
                    # Ensure tx_date is a date object
                    tx_date = (tx_date_time.date()
                               if hasattr(tx_date_time, 'date')
                               else self._get_required_field(
                                   cash_tx, 'tradeDate', 'CashTransaction'
                               ))

                    description = self._get_required_field(
                        cash_tx, 'description', 'CashTransaction'
                    )
                    amount = self._to_decimal(
                        self._get_required_field(cash_tx, 'amount',
                                                 'CashTransaction'),
                        'amount', f"CashTransaction {description[:30]}"
                    )
                    currency = self._get_required_field(
                        cash_tx, 'currency', 'CashTransaction'
                    )

                    security_id = getattr(cash_tx, 'conid', None)
                    tx_type = cash_tx.type
                    if tx_type is None:
                        raise ValueError(f"CashTransaction type is missing for {description}")

                    if security_id:
                        tx_type_str = getattr(tx_type, 'value', str(tx_type))
                        assert 'interest' not in str(tx_type_str).lower()

                        sec_pos_key = None
                        for pos in processed_security_positions.keys():
                            if pos.depot == account_id and pos.symbol == str(security_id):
                                sec_pos_key = pos
                                break

                        if sec_pos_key is None:
                            isin_attr = getattr(cash_tx, 'isin', None)
                            sym_attr = getattr(cash_tx, 'symbol', None)
                            sec_pos_key = SecurityPosition(
                                depot=account_id,
                                valor=None,
                                isin=ISINType(isin_attr) if isin_attr else None,
                                symbol=str(security_id),
                                description=(
                                    f"{description} ({sym_attr})" if sym_attr else description
                                ),
                            )

                        sec_payment = SecurityPayment(
                            paymentDate=tx_date,
                            name=description,
                            amountCurrency=currency,
                            amount=amount,
                            quotationType='PIECE',
                            quantity=Decimal('0')
                        )
                        processed_security_positions[sec_pos_key]['payments'].append(
                            sec_payment
                        )
                    else:
                        if tx_type in [ibflex.CashAction.DEPOSITWITHDRAW]:
                            # Not Tax Relant event
                            continue
                        elif tx_type in [ibflex.CashAction.BROKERINTPAID]:
                            # TODO: Optionally create a liabilities section.
                            print(f"Warning: Broker interest paid for {description} is not handled for liabilities.")
                            continue
                        elif tx_type in [ibflex.CashAction.FEES]:
                            # TODO: Optionally create a costs sectioons.
                            print(f"Warning: Fees paid for {description} are ignored for statement.")
                            continue
                        elif tx_type in [ibflex.CashAction.BROKERINTRCVD]:
                            # Tax relevant event. Fall through to create a bank payment.
                            pass
                        else:
                            raise ValueError(f"CashTransaction type {tx_type} is not supported for {description}")
                        cash_pos_key = (account_id, currency, "MAIN_CASH")

                        bank_payment = BankAccountPayment(
                            paymentDate=tx_date,
                            name=description,
                            amountCurrency=currency,
                            amount=amount
                        )
                        processed_cash_positions[cash_pos_key]['payments'].append(
                            bank_payment
                        )

        # --- Construct ListOfSecurities ---
        # account_id -> list of Security objects
        depot_securities_map: defaultdict[str, List[Security]] = defaultdict(list)
        sec_pos_idx = 0
        for sec_pos_obj, data in processed_security_positions.items():
            sec_pos_idx += 1
            sorted_stocks = self._aggregate_stocks_by_date(data['stocks'])
            sorted_payments = sorted(
                data['payments'], key=lambda p: p.paymentDate
            )

            # Determine currency and quotation type from stocks or defaults
            primary_currency = None
            primary_quotation_type: QuotationType = "PIECE" # Default
            if sorted_stocks:
                # Try balance entry first, then any entry
                balance_stocks = [
                    s for s in sorted_stocks if not s.mutation and s.balanceCurrency
                ]
                if balance_stocks:
                    primary_currency = balance_stocks[0].balanceCurrency
                    primary_quotation_type = balance_stocks[0].quotationType
                else:  # Try any stock
                    primary_currency = sorted_stocks[0].balanceCurrency
                    primary_quotation_type = sorted_stocks[0].quotationType

            if not primary_currency:  # Fallback if no stocks or no currency
                if sorted_payments:
                    primary_currency = sorted_payments[0].amountCurrency
                else:
                    raise ValueError(
                        f"Cannot determine currency for security "
                        f"{sec_pos_obj.symbol} (Desc: {sec_pos_obj.description}). "
                        f"No stocks or payments with currency info."
                    )

            # TODO: Map assetCategory to eCH-0196 SecurityCategory
            # Attempt to get assetCategory, default to "STK"
            asset_cat_source = None
            if sorted_stocks and hasattr(sorted_stocks[0], 'assetCategory'):
                asset_cat_source = sorted_stocks[0]
            # Payments don't usually have assetCategory
            elif sorted_payments and hasattr(sorted_payments[0], 'assetCategory'):
                asset_cat_source = sorted_payments[0]

            asset_cat = (getattr(asset_cat_source, 'assetCategory', 'STK')
                         if asset_cat_source else 'STK')

            sec_category_str: SecurityCategory = "SHARE"
            if (asset_cat == "BOND"):
                sec_category_str = "BOND"
            elif (asset_cat == "OPT"):
                sec_category_str = "OPTION"
            elif (asset_cat == "FUT"):
                sec_category_str = "OTHER"
            elif (asset_cat == "ETF"):
                sec_category_str = "FUND"
            elif (asset_cat == "FUND"):
                sec_category_str = "FUND"
            elif (asset_cat == "STK"):
                sec_category_str = "SHARE"
            else:
                raise ValueError(f"Unknown asset category: {asset_cat}")

            # --- Ensure balance at period start and period end + 1 using PositionReconciler ---
            reconciler = PositionReconciler(list(sorted_stocks), identifier=f"{sec_pos_obj.symbol}-reconcile")
            end_plus_one = self.period_to + timedelta(days=1)
            end_pos = reconciler.synthesize_position_at_date(end_plus_one)
            closing_balance = end_pos.quantity if end_pos else Decimal("0")

            trades_quantity_total = sum(
                s.quantity for s in sorted_stocks if s.mutation
            )

            start_pos = reconciler.synthesize_position_at_date(self.period_from)
            if start_pos:
                opening_balance = start_pos.quantity
            else:
                tentative_opening = closing_balance - trades_quantity_total
                opening_balance = tentative_opening if tentative_opening >= 0 else Decimal("0")

            if opening_balance < 0 or closing_balance < 0:
                raise ValueError(
                    f"Negative balance computed for security {sec_pos_obj.symbol}"
                    f" (start {opening_balance}, end {closing_balance})"
                )

            start_exists = any(
                (not s.mutation and s.referenceDate == self.period_from)
                for s in sorted_stocks
            )
            if not start_exists:
                sorted_stocks.append(
                    SecurityStock(
                        referenceDate=self.period_from,
                        mutation=False,
                        quotationType=primary_quotation_type,
                        quantity=opening_balance,
                        balanceCurrency=primary_currency,
                        name="Opening balance"
                    )
                )

            end_exists = any(
                (not s.mutation and s.referenceDate == end_plus_one)
                for s in sorted_stocks
            )
            if not end_exists:
                sorted_stocks.append(
                    SecurityStock(
                        referenceDate=end_plus_one,
                        mutation=False,
                        quotationType=primary_quotation_type,
                        quantity=closing_balance,
                        balanceCurrency=primary_currency,
                        name="Closing balance"
                    )
                )

            sorted_stocks = sorted(
                sorted_stocks, key=lambda s: (s.referenceDate, s.mutation)
            )

            sec = Security(
                positionId=sec_pos_idx,
                currency=primary_currency,
                quotationType=primary_quotation_type,
                securityCategory=sec_category_str, # TODO: Map to Literal
                securityName=sec_pos_obj.description or sec_pos_obj.symbol,
                isin=ISINType(sec_pos_obj.isin) if sec_pos_obj.isin is not None else None,
                valorNumber=sec_pos_obj.valor,
                country="US", # Placeholder, determine actual country
                stock=sorted_stocks,
                payment=sorted_payments
            )
            depot_securities_map[sec_pos_obj.depot].append(sec)

        final_depots = []
        if depot_securities_map:
            for depot_id, securities_in_depot in depot_securities_map.items():
                if securities_in_depot:
                    final_depots.append(
                        Depot(depotNumber=DepotNumber(depot_id),
                              security=securities_in_depot)
                    )

        list_of_securities = (ListOfSecurities(depot=final_depots)
                              if final_depots else None)

        # --- Construct ListOfBankAccounts ---
        final_bank_accounts: List[BankAccount] = []
        
        # First, collect all currencies from CashReport that have closing balances
        all_currencies_with_balances: Dict[tuple, Dict[str, Any]] = {}
        
        for s_stmt in all_flex_statements:
            account_id = s_stmt.accountId
            if hasattr(s_stmt, 'CashReport') and s_stmt.CashReport:
                for cash_report_currency_obj in s_stmt.CashReport:
                    if hasattr(cash_report_currency_obj, 'currency'):
                        curr = cash_report_currency_obj.currency
                        
                        # Skip BASE_SUMMARY entries (IBKR internal aggregation, not a real currency)
                        if curr == "BASE_SUMMARY":
                            continue
                            
                        key = (account_id, curr)
                        
                        # Extract closing balance
                        closing_balance_value = None
                        if hasattr(cash_report_currency_obj, 'endingCash'):
                            closing_balance_value = self._to_decimal(
                                cash_report_currency_obj.endingCash,
                                'endingCash',
                                f"CashReport {account_id} {curr}"
                            )
                        elif (hasattr(cash_report_currency_obj, 'balance') and
                              hasattr(cash_report_currency_obj, 'reportDate') and
                              cash_report_currency_obj.reportDate == self.period_to):
                            closing_balance_value = self._to_decimal(
                                cash_report_currency_obj.balance,
                                'balance',
                                f"CashReport {account_id} {curr}"
                            )
                        
                        if closing_balance_value is not None:
                            all_currencies_with_balances[key] = {
                                'account_id': account_id,
                                'currency': curr,
                                'closing_balance': closing_balance_value,
                                'payments': []
                            }

        # Now add payments from cash transactions to the relevant currencies
        for (stmt_account_id, currency_code, _), data in processed_cash_positions.items():
            key = (stmt_account_id, currency_code)
            if key in all_currencies_with_balances:
                all_currencies_with_balances[key]['payments'].extend(data['payments'])
            else:
                # This currency has transactions but no closing balance in CashReport
                # Still create an entry for it
                all_currencies_with_balances[key] = {
                    'account_id': stmt_account_id,
                    'currency': currency_code,
                    'closing_balance': None,
                    'payments': data['payments']
                }

        # Create bank accounts for all currencies
        for key, data_dict in all_currencies_with_balances.items():
            acc_id = data_dict['account_id']
            curr = data_dict['currency']
            payments = data_dict['payments']
            closing_balance_value = data_dict['closing_balance']

            # Ensure payments is a list before sorting
            sorted_payments = sorted(payments or [], key=lambda p: p.paymentDate)

            bank_account_tax_value_obj = None
            if closing_balance_value is not None:
                bank_account_tax_value_obj = BankAccountTaxValue(
                    referenceDate=self.period_to,
                    name="Closing Balance",
                    balanceCurrency=curr,
                    balance=closing_balance_value
                )
            else:
                raise ValueError(
                    f"Warning: No closing cash balance found in CashReport "
                    f"for account {acc_id}, currency {curr} for date "
                    f"{self.period_to}."
                )

            bank_account_num_str = f"{acc_id}-{curr}"
            bank_account_name_str = f"{acc_id} {curr} position"

            ba = BankAccount(
                bankAccountName=BankAccountName(bank_account_name_str),
                bankAccountNumber=BankAccountNumber(bank_account_num_str),
                bankAccountCountry="US",
                bankAccountCurrency=curr,
                payment=sorted_payments,
                taxValue=bank_account_tax_value_obj # Adjusted to single obj
            )
            final_bank_accounts.append(ba)

        list_of_bank_accounts = (ListOfBankAccounts(bankAccount=final_bank_accounts)
                                 if final_bank_accounts else None)

        tax_statement = TaxStatement(
            minorVersion=1,
            periodFrom=self.period_from,
            periodTo=self.period_to,
            taxPeriod=self.period_from.year,
            listOfSecurities=list_of_securities,
            listOfBankAccounts=list_of_bank_accounts
        )
        print(
            "Partial TaxStatement created with Trades, OpenPositions, "
            "and basic CashTransactions mapping."
        )

        # Fill in institution
        # Name is sufficient. Avoid setting legal identifiers avoid implying this is
        # officially from the broker.
        tax_statement.institution = Institution(
            name="Interactive Brokers"
        )

        # --- Create Client object ---
        # TOOD: Handle joint accounts
        client_obj = None
        if all_flex_statements:
            first_statement = all_flex_statements[0]
            if hasattr(first_statement, 'AccountInformation') and first_statement.AccountInformation:
                acc_info = first_statement.AccountInformation
                account_id = getattr(acc_info, 'accountId', None)
                name = getattr(acc_info, 'name', None)
                first_name = getattr(acc_info, 'firstName', None)
                last_name = getattr(acc_info, 'lastName', None)
                account_holder_name = getattr(acc_info, 'accountHolderName', None)
                # address1 = getattr(acc_info, 'address1', None)
                # address2 = getattr(acc_info, 'address2', None)
                # city = getattr(acc_info, 'city', None)
                # state = getattr(acc_info, 'state', None)
                # country = getattr(acc_info, 'country', None)
                # postalCode = getattr(acc_info, 'postalCode', None)

                client_first_name = None
                client_last_name = None

                # Helper function to check if a string value is valid (not None, not empty, not just whitespace)
                def is_valid_string(value):
                    return value is not None and isinstance(value, str) and value.strip()

                if is_valid_string(first_name) and is_valid_string(last_name):
                    client_first_name = str(first_name).strip()
                    client_last_name = str(last_name).strip()
                elif is_valid_string(name):
                    client_last_name = str(name).strip()
                elif is_valid_string(account_holder_name):
                    client_last_name = str(account_holder_name).strip()

                if account_id and client_last_name: # lastName is mandatory for Client
                    client_obj = Client(
                        clientNumber=ClientNumber(account_id),
                        firstName=client_first_name,
                        lastName=client_last_name,
                        # Other fields like tin, salutation are not yet mapped
                    )
        if client_obj:
            tax_statement.client = [client_obj]
        # --- End Client object ---

        return tax_statement


if __name__ == '__main__':
    print("IbkrImporter module loaded.")
    if not IBFLEX_AVAILABLE:
        print(
            "ibflex library not available. Run 'pip install ibflex' "
            "to use this importer."
        )
    else:
        print("ibflex library is available.")
    # Example usage:
    # from opensteuerauszug.config.models import IbkrAccountSettings # Create
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
    #     <FlexStatement accountId="U1234567" fromDate="2023-01-01"
    #                    toDate="2023-12-31" period="Year"
    #                    whenGenerated="2024-01-15T10:00:00">
    #       <Trades>
    #         <Trade assetCategory="STK" symbol="AAPL" tradeDate="2023-05-10"
    #                quantity="10" tradePrice="150.00" currency="USD" />
    #       </Trades>
    #       <CashTransactions>
    #         <CashTransaction type="Deposits/Withdrawals"
    #                          dateTime="2023-02-01T00:00:00"
    #                          amount="1000" currency="USD" />
    #       </CashTransactions>
    #       <OpenPositions>
    #         <OpenPosition assetCategory="STK" symbol="MSFT" position="100"
    #                       markPrice="300" currency="USD" />
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
    print(
        "Example usage in __main__ needs IbkrAccountSettings to be defined "
        "in config.models and 'pip install ibflex devtools'."
    )
