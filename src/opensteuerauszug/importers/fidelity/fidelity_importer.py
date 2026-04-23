#!/usr/bin/env python3

import os
import logging
from typing import Final, List, Any, Dict, Sequence
from datetime import datetime, date, timedelta
from decimal import Decimal
from collections import defaultdict

logger = logging.getLogger(__name__)

from opensteuerauszug.model.position import SecurityPosition
from opensteuerauszug.model.ech0196 import (
    BankAccountName, Institution, DepotNumber, TaxStatement,
    ListOfBankAccounts, BankAccount, BankAccountPayment, BankAccountTaxValue,
    ListOfSecurities, SecurityCategory, Security, SecurityStock, SecurityPayment,
    QuotationType, BankAccountNumber, Depot,
)
from opensteuerauszug.core.position_reconciler import PositionReconciler
from opensteuerauszug.config.models import FidelityAccountSettings
from opensteuerauszug.importers.common import (
    CashPositionData,
    SecurityNameRegistry,
    SecurityPositionData,
    aggregate_mutations,
    apply_withholding_tax_fields,
    build_client,
    build_security_payment,
    parse_swiss_canton,
    resolve_first_last_name,
    to_decimal,
)
from opensteuerauszug.render.translations import get_text, Language, DEFAULT_LANGUAGE

KNOWN_ACTIONS = [ # actions that we know how to deal with
    "buy", "Cash In Lieu", "Credit Interest", "Deposit", "dividend",
    "NRA Tax Adj", "buy", "sell", "Stock Plan Activity",
    "stock_split", "Tax Withholding", "transfer", "Wire Transfer", "DIRECT DEBIT"
]

ACTION_STRINGS = [ # matching string in transactions csv
    "BOUGHT", "IN LIEU", "INTEREST EARNED", "DIRECT DEPOSIT", "DIVIDEND RECEIVED",
    "ADJ NON-RESIDENT TAX", "REINVESTMENT",  "SOLD", "Stock Plan Activity",
    "SPLIT", "NON-RESIDENT TAX", "TRANSFER OF ASSETS", "Wire Transfer", "DIRECT DEBIT"
]

ACTIONS_DICT:Final[Dict[str,str]]=dict(zip(ACTION_STRINGS,KNOWN_ACTIONS))

# lines from statements that can / should be ignored when these values are in the symbols column
SYMBOLS_TO_IGNORE = ['Subtotal of Core Account','QPIQQ','QPIFQ','Core Account','Subtotal of Stocks']
#Actions that have no impact on the tax statement
ACTIONS_TO_IGNORE = ['Cash In Lieu']


def should_skip_entry(entry: Any, entry_label: str) -> bool:
    """Skip pseudo rows where accountId='-' or mapped-to-None SUMMARY rows."""
    # Some rows might have missing accountId or be marked as SUMMARY, 
    # which we treat as pseudo entries.
    symbol = entry.get('Symbol/CUSIP') if entry.get('Symbol/CUSIP')  else entry.get('Symbol')
    symbol=symbol.strip() if symbol else symbol
    account_id = entry.get('Account Number') if (
        entry.get('Account Number')) else entry.get('Account')

    if entry_label in ['Trade','Position']:
        description = entry.get('Description')
        if entry_label in ['Position']:
            ending_value = entry.get('Ending Value')
            if ending_value == 'unavailable':
                logger.debug(
                    "Skipping entry %s of type %s with no ending value.",
                    entry, entry_label
                )
                return True
        if symbol is None or symbol == '':
            if description is not None: # if there is no Description it's probably just an emptry line
                logger.info(
                    "Skipping entry %s of type %s with description:%s and no symbol",
                    entry,entry_label,description
                )
            else:
                logger.debug(
                    "Skipping entry %s of type %s with no description or symbol",
                    entry,entry_label
                )
            return True
    if (account_id is None or account_id == '') and entry_label in ['Transactions']:
        logger.debug(
            "Skipping entry %s of type %s with no Account Number",
            entry,entry_label
        )
        return True
    if symbol in SYMBOLS_TO_IGNORE or symbol == account_id:
        logger.debug(
            "Skipping entry %s of type %s", symbol,entry_label
        )
        return True
    else:
        return False

class FidelityImporter:
    """
    Imports Fidelity account data for a given tax period
    from csv files.
    """
    def _get_required_field(self, data_object: dict, field_name: str,
                              object_description: str) -> str | None | date | list | Any:
        """Helper to get a required field or raise ValueError if missing."""
        value = data_object.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip() and not
        object_description=='CashTransaction'):
            error_desc = object_description  # Use the passed in description
            if data_object.get('Symbol'):
                error_desc = (f"{object_description} (Symbol: "
                              f"{data_object.get('Symbol')})")
            elif data_object.get('Symbol/CUSIP'):
                error_desc = (f"{object_description} (Symbol: "
                              f"{data_object.get('Symbol/CUSIP')})")
            elif (data_object.get('Account Number') and
                  not ('Account:' in object_description)):  # Avoid double "Account:"
                error_desc = (f"{object_description} (Account: "
                              f"{data_object.get('Account Number')})")
            elif (data_object.get('Account') and
                  not ('Account:' in object_description)):  # Avoid double "Account:"
                error_desc = (f"{object_description} (Account: "
                              f"{data_object.get('Account')})")
            raise ValueError(
                f"Missing required field '{field_name}' in {error_desc}."
            )
        if field_name =='Run Date':
            try:
                if data_object.get('Action').find(' as of ')>0:
                    tmp_date = data_object.get('Action').split()
                    value = datetime.strptime(tmp_date[tmp_date.index('of')+1], "%b-%d-%Y").date()
                else:
                    value = datetime.strptime(value.strip(), "%m/%d/%Y").date()
            except (ValueError, UnboundLocalError) as e:
                logger.warning(
                    "Warning: Could not parse transaction date info : %s from %s", value, object_description)
                value = None
        if isinstance(value, list):
            if len(value)==1:
                if isinstance(value[0], str):
                    return value[0].strip() if isinstance(value[0], str) else value[0]
        return value.strip() if isinstance(value, str) else value

    def _to_decimal(self, value: object | None, field_name: str,
                    object_description: str) -> Decimal:
        """Converts a value to Decimal, raising ValueError on failure."""
        return to_decimal(value, field_name, object_description)

    def __init__(self,
                 period_from: date,
                 period_to: date,
                 account_settings_list: List[FidelityAccountSettings],
                 strict_consistency: bool = True,
                 render_language: Language = DEFAULT_LANGUAGE):
        """
        Initialize the importer with a tax period.

        Args:
            period_from (date): The start date of the tax period.
            period_to (date): The end date of the tax period.
            account_settings_list: List of Fidelity account settings.
            strict_consistency (bool): If True, raises an error on position reconciliation
                inconsistencies. If False, logs a warning.
        """
        self.period_from = period_from
        self.period_to = period_to
        self.account_settings_list = account_settings_list
        self.strict_consistency = strict_consistency
        self.render_language = render_language

        if not self.account_settings_list:
            # Currently no account info is used so we keep stump.
            logger.debug(
                "FidelityImporter initialized with an empty list of "
                "account settings."
            )
        else:
            logger.debug(
                "FidelityImporter initialized with settings %s", account_settings_list
            )

    def _aggregate_stocks(self, stocks: List[SecurityStock]) -> List[SecurityStock]:
        """Aggregate buy and sell entries on the same date with equal order id if present without reordering."""
        return aggregate_mutations(stocks)

    def _read_statement(self,file_contents: list[str]):
        import csv
        transaction_start_header = "Symbol/CUSIP,Description,Quantity,Price,Beginning Value,Ending Value,Cost Basis"
        summary_data = list(csv.DictReader(file_contents[:2], skipinitialspace=True))[0]
        transaction_start_index = next(
            index for index, line in enumerate(file_contents)
            if line.strip() == transaction_start_header
        )

        #transaction_start_index = file_contents.index(
        #    "Symbol/CUSIP,Description,Quantity,Price,Beginning Value,Ending Value,Cost Basis")
        position_data = list(csv.DictReader(file_contents[transaction_start_index:], skipinitialspace=True))
        skimmed_position_data = []
        for line in position_data:
            if not should_skip_entry(line, "Position reader"):
                skimmed_position_data.append(line)

        if len(position_data) and len(summary_data):
            logger.info(
                "Successfully parsed statement for  account: %s, with number: %s",
                summary_data['Account Type'], summary_data['Account']
            )
            return summary_data, skimmed_position_data
        else:
            return None, None

    def _read_transactions(self,file_contents: list[str]):
        import csv
        separator_index = next(
            (i for i, line in enumerate(file_contents) if not line.strip()),
            len(file_contents),
        )
        data = list(csv.DictReader(file_contents[:separator_index], skipinitialspace=True))
        if len(data) > 0:
            logger.info(
                "Successfully parsed transactions for account: %s, with number: %s",
                data[1]['Account'], data[1]['Account Number']
            )
        return data

    def _parse_inputs(
        self,
        filenames: Sequence[str],
        *,
        file_label: str,
        log_label: str,
        error_label: str,
    ) :
        from datetime import datetime
        statements: list[dict[str, Any]] = []
        transactions: list[dict[str, Any]] = []
        for filename in filenames:
            if not os.path.exists(filename):
                raise FileNotFoundError(f"{file_label} not found: {filename}")
            if not filename.lower().endswith(".csv"):
                logger.warning("Skipping non-csv %s: %s", log_label, filename)
                continue
            try:
                with ((open(filename, mode='r', encoding='us-ascii')) as csvfile):
                    logger.debug("Parsing %s: %s", log_label, filename)
                    if (filename.find('Statement') > -1):
                        statement = {}
                        logger.debug("Parsing %s: %s as a Statement", log_label, filename)
                        statement['Date']= ''
                        try:
                            statement['Date']  = datetime.strptime(filename.split('/')[-1].strip('.csv').strip(
                                'Statement'),
                            '%m%d%Y').date()
                        except ValueError as e:
                            logger.warning(
                                "Unable to extract statement date from filename: %s\n %s",
                                filename,e
                            )
                        file_contents=csvfile.readlines()
                        statement['Summary'], statement['Positions'] = self._read_statement(
                            file_contents=file_contents)
                        if statement['Positions'] is not None:
                            statements.append(statement)
                    elif (filename.find('Accounts_History') > -1):
                        logger.debug("Parsing %s: %s as Transaction History", log_label, filename)
                        transaction_data = self._read_transactions(file_contents=csvfile.readlines())
                        if transaction_data is not None:
                            transactions.extend(transaction_data)
                    else:
                        logger.warning(
                            "No Valid input files found in %s or response was empty.",
                            filename,
                        )
            except Exception as e:
                raise RuntimeError(
                    f"An unexpected error occurred while parsing {filename}: {e}"
                )
        return statements,transactions

    def _find_processed_security_position(
        self,
        processed_security_positions: Dict[SecurityPosition, SecurityPositionData],
        account_id: str,
        security_id: object,
    ) -> SecurityPosition | None:
        for position in processed_security_positions:
            if position.depot == account_id and position.symbol == str(security_id):
                return position
        return None

    def _build_cash_transaction_security_position(
        self,
        account_id: str,
        transaction: dict,
        description: str,
    ) -> SecurityPosition:
        symbol = self._get_required_field(transaction, 'Symbol', 'CashTransaction')
        return SecurityPosition(
            depot=account_id,
            valor=None,
            isin=None,
            symbol=str(symbol),
            description=(
                f"{description} ({symbol})" if symbol else description
            ),
        )

    _WITHHOLDING_ACTIONS = frozenset({"Tax Withholding", "NRA Tax Adj"})

    def _apply_withholding_tax_fields(
        self,
        payment: SecurityPayment,
        amount: Decimal,
        currency: str,
        tx_type: str,
    ) -> None:
        if tx_type not in self._WITHHOLDING_ACTIONS:
            return
        apply_withholding_tax_fields(payment, amount, currency)

    def _build_security_payment(
        self,
        payment_date: date,
        description: str,
        currency: str,
        amount: Decimal,
        tx_type: str,
    ) -> SecurityPayment:
        return build_security_payment(
            payment_date=payment_date,
            description=description,
            currency=currency,
            amount=amount,
            broker_label=tx_type,
            is_withholding=tx_type in self._WITHHOLDING_ACTIONS,
            is_securities_lending=tx_type == "Cash In Lieu",
        )

    def import_files(self, filenames: List[str]) -> TaxStatement:
        """
        Import data from Fidelity csv statements and transactions reports and return a TaxStatement.

        Args:
            filenames: List of file paths to import (csv).

        Returns:
            The imported tax statement.
        """
        all_statements, all_transactions = self._parse_inputs(
            filenames,
            file_label="Fidelity statement file",
            log_label="Fidelity statement log",
            error_label="Fidelity statement error",
        )
        currency = "USD" #assumption for Fidelity
        if not all_statements:
            # This might be an error or just a case of no relevant data.
            # "If data is missing do a hard error" - might need adjustment
            logger.warning(
                "No statements or were successfully parsed. "
                "Returning empty TaxStatement."
            )
            return TaxStatement(
                minorVersion=1, periodFrom=self.period_from,
                periodTo=self.period_to,
                taxPeriod=self.period_from.year, listOfSecurities=None,
                listOfBankAccounts=None
            )

        # Best-name-wins registry for security display names.
        security_name_registry = SecurityNameRegistry()

        # Key: SecurityPosition or tuple for cash. Value: dict with 'stocks', 'payments'
        processed_security_positions: defaultdict[SecurityPosition, SecurityPositionData] = \
            defaultdict(lambda: SecurityPositionData({'stocks': [], 'payments': []}))

        processed_cash_positions: defaultdict[tuple, CashPositionData] = \
            defaultdict(lambda: CashPositionData({'stocks': [], 'payments': []}))


        # Map to store assetCategory and subCategory for each security
        security_asset_category_map: Dict[SecurityPosition, SecurityCategory] = {}
        if (len(all_statements) > 0):
            logger.info(f"Processing statements")
        for stmt in all_statements:
            summary = self._get_required_field(
                stmt, 'Summary', 'Statement'
            )
            account_id = self._get_required_field(
                summary, 'Account', 'Statement Summary'
            )
            positions = self._get_required_field(
                stmt, 'Positions', 'Statement'
            )
            # account_id_processed = account_id # Keep track for summary

            # --- Process Open Positions (End of Period Snapshot) ---
            end_date = self._get_required_field(stmt,'Date', 'Statement')
            end_plus_one = end_date + timedelta(days=1)
            default_category=''
            for position in positions:
                logger.debug("position: %s for stmt in all_statements", position)
                if should_skip_entry(position, "Position"):
                    continue
                # Use period end + 1 as reference date for the balance
                # entry. This avoids creating a separate stock entry on
                # the period end itself which would later result in a
                # duplicate closing balance.
                symbol = self._get_required_field(
                    position, 'Symbol/CUSIP', 'Position'
                )
                if symbol.find('Stocks')==0:
                    default_category = 'SHARE'
                    continue
                if len(symbol) == 0: #can happen with a delisted stock which will have an unknown value
                    logger.warning(
                        f"Skipping position without symbol: {position}\n"
                        f"from statement dated: {end_date}"
                    )
                    continue
                if len(symbol) < 6: #otherwise the line is something else
                    description = self._get_required_field(
                        position, 'Description', 'Position'
                    )

                    quantity = self._to_decimal(
                        self._get_required_field(position, 'Quantity',
                                                 'Position'),
                        'position', f"Position {symbol}"
                    )

                    asset_category = (
                        'FUND'
                        if ('ETF' in description or 'INDEX' in description)
                        else default_category
                    )

                    sec_pos = SecurityPosition(
                        depot=account_id,
                        symbol=symbol,
                        description=f"{description} ({symbol})"
                    )

                    # Update name metadata (Priority: 10 for OpenPositions)
                    security_name_registry.update(sec_pos, f"{description} ({symbol})", 10)

                    if sec_pos not in security_asset_category_map:
                        logger.debug(f"Adding security position {sec_pos} asset category"
                                     f" {asset_category}")
                        security_asset_category_map[sec_pos] = asset_category

                    mark_price =  self._to_decimal(position.get('Price'), 'Price', f"Position {symbol}")

                    pos_value = self._to_decimal(position.get('Ending Value'), ' Ending Value', f"Position"
                                                                                                f" {symbol}")

                    balance_stock = SecurityStock(
                        # Balance as of the period end + 1
                        referenceDate=end_plus_one,
                        mutation=False,
                        quantity=quantity,
                        name=f"End of Period Balance {symbol}",
                        balanceCurrency=currency,
                        quotationType="PIECE",
                        unitPrice=mark_price,
                        balance=pos_value,
                    )
                    processed_security_positions[sec_pos]['stocks'].append(
                        balance_stock
                    )
                elif should_skip_entry(position, "Position") or symbol==account_id:
                        continue
                else:
                    raise NotImplementedError(f"Fidelity Importer:Importing position {position} not implemented "
                                              f"yet.")

        logger.info(f"Processing Transactions for account: {account_id}")
        for transaction in all_transactions:
            logger.debug("transaction: %s for transaction in all_transactions", transaction)
            account_id=''
            symbol=None
            account_id = self._get_required_field(
                transaction, 'Account Number', 'Transactions'
            )
            # account_id_processed = account_id # Keep track for summary
            action=None
            for key, value in ACTIONS_DICT.items():
                if transaction['Action'].find(key) >-1:
                    action = value
                    break
                logger.debug("key:%s, value:%s, action:%s, found:%s ", key, value, transaction['Action'], transaction[
                    'Action'].find(
                    key))
            if action is None:
                raise ValueError(f"Unknown {transaction['Action']} is not supported for {transaction['Description']}")
            if not action:
                raise ValueError(f"Missing action in transaction: {transaction}")
            trade_date = self._get_required_field(
                transaction, 'Run Date', 'Transaction'
            )
            #settle_date = transaction.get('Settlement Date') not usually present...

            description = self._get_required_field(
                transaction, 'Description', action
            )

            quantity = self._to_decimal(
                self._get_required_field(transaction, 'Quantity', action),
                'Quantity', f"Transaction {symbol if symbol is not None else action}"
            )
            # --- Process Trades ---
            if action in ACTIONS_TO_IGNORE:
                logger.debug("Skipping transaction of type %s which is not tax relevant", action)
                continue
            if action in ['buy', 'sell','transfer','stock_split']:
                if should_skip_entry(transaction, "Trade"):
                    continue
                if not transaction['Symbol'] or len(transaction['Symbol']) < 1:
                    logger.warning(
                        f"Skipping transaction without recognisable symbol: {transaction}\n"
                    )
                    continue

                symbol = self._get_required_field(
                    transaction, 'Symbol', action
                )

                trade_money = self._to_decimal(
                    self._get_required_field(transaction, 'Amount ($)', 'Trade'),
                    'Amount', f"Trade {symbol}"
                )
                if not action in ['transfer', 'stock_split']:
                    trade_price = self._to_decimal(
                        self._get_required_field(transaction, 'Price ($)', 'Trade'),
                    'Price', f"Trade {symbol}"
                    )
                else:
                    trade_price = (trade_money / quantity)

                commission = self._to_decimal(
                    transaction['Commission ($)'] if 'Commission' in transaction else 0,
                    'Commission', f"Trade {symbol}"
                )

                sec_pos = SecurityPosition(
                    depot=account_id,
                    symbol=symbol,
                    description=f"{description} ({symbol})"
                )

                asset_category = security_asset_category_map[sec_pos] if sec_pos in security_asset_category_map else \
                    'SHARE'
                # Added ETF, FUND
                if asset_category not in [
                    "SHARE", "FUND"
                ]:
                    asset_category='SHARE'
                    logger.warning(
                        f"Assuming asset category: {asset_category} "
                        f"for (Symbol: {symbol})"
                    )
                # Update name metadata (Priority: 8 for Trades)
                security_name_registry.update(sec_pos, f"{description} ({symbol})", 8)
                if quantity < 0 and action=="stock_split":
                    action="reverse_stock_split"

                stock_mutation = SecurityStock(
                    referenceDate=trade_date,
                    mutation=True,
                    quantity=quantity,
                    unitPrice=trade_price if trade_price != Decimal(0) else None,
                    name=get_text(action, self.render_language),
                    balanceCurrency=currency,
                    quotationType="PIECE",
                    value= trade_money if trade_money != Decimal(0) else None
                )
                processed_security_positions[sec_pos]['stocks'].append(
                    stock_mutation
                )

                # Cash movements resulting from trades are tracked via the cash transaction section. Only the stock mutation is stored here.

            # --- Process Cash Transactions ---
            else:
                if should_skip_entry(transaction, "CashTransaction"):
                    continue
                amount = self._to_decimal(
                    self._get_required_field(transaction, 'Amount ($)',
                                             'CashTransaction'),
                    'amount', f"CashTransaction {description[:30]}"
                )
                symbol = transaction['Symbol']
                if symbol:
                    assert "Credit Interest" not in action
                    sec_pos_key = self._find_processed_security_position(
                        processed_security_positions,
                        account_id,
                        symbol,
                    )
                    sec_pos = SecurityPosition(
                        depot=account_id,
                        symbol=symbol,
                        description=f"{description} ({symbol})",
                    )

                    # Update name metadata (Priority: 0 for CashTransactions - lowest)
                    # Use description or symbol if description is generic?
                    # Usually description in CashTx is like "Dividend ...". Not great for security name.
                    # But if it's the only source, it's better than nothing.
                    if sec_pos_key is not None:
                        security_name_registry.update(
                            sec_pos_key,
                            f"{description} ({symbol})",
                            0,
                        )

                    if sec_pos_key is None:
                        sec_pos_key = self._build_cash_transaction_security_position(
                            account_id,
                            transaction,
                            transaction['Action'],
                        )

                    sec_payment = self._build_security_payment(
                        payment_date=trade_date,
                        description=description,
                        currency=currency,
                        amount=amount,
                        tx_type=action,
                    )
                    processed_security_positions[sec_pos_key]['payments'].append(
                        sec_payment
                    )
                else:
                    if (action in ['DIRECT DEBIT','Deposit']):
                        logger.debug('skipping: %s', action)
                        continue
                    logger.debug('Adding:%s', action)
                    cash_pos_key = (account_id, currency, "MAIN_CASH")
                    bank_payment = BankAccountPayment(
                        paymentDate=trade_date,
                        name=transaction['Action'].replace("INTEREST EARNED", get_text("credit_interest",
                                                                                    self.render_language)),
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
            sorted_stocks = self._aggregate_stocks(data['stocks'])
            sorted_payments = sorted(
                data['payments'], key=lambda p: p.paymentDate
            )

            # Determine currency and quotation type from stocks or defaults
            primary_currency = "USD"
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
            # Get assetCategory and subCategory from the map, default to "STK"
            asset_cat = security_asset_category_map[sec_pos_obj] if sec_pos_obj in security_asset_category_map else \
                'SHARE'


            # Initial Consistency Check
            initial_reconciler = PositionReconciler(list(sorted_stocks), identifier=f"{sec_pos_obj.symbol}-initial_check")
            is_consistent_initial, _ = initial_reconciler.check_consistency(
                print_log=True,
                raise_on_error=self.strict_consistency,
                assume_zero_if_no_balances=True
            )
            if not is_consistent_initial and not self.strict_consistency:
                logger.warning(
                    f"{sec_pos_obj.symbol}] Initial consistency check on raw data failed. Review logs. Proceeding with synthesis.")

            # --- Ensure balance at period start and period end + 1 using PositionReconciler ---
            reconciler = PositionReconciler(list(sorted_stocks), identifier=f"{sec_pos_obj.symbol}-reconcile", )
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
                    f"Negative balance computed for security {sec_pos_obj.symbol} with {asset_cat}. In case you expect short positions, please report this to the developers for further investigation."
                    f" (start {opening_balance}, end {closing_balance})"
                )

            # Find settings for this account
            account_settings = next(
                (s for s in self.account_settings_list if s.account_number == sec_pos_obj.depot),
                None
            )

            start_exists = any(
                (not s.mutation and s.referenceDate == self.period_from)
                for s in sorted_stocks
            )
            if not start_exists and opening_balance != 0:
                sorted_stocks.append(
                    SecurityStock(
                        referenceDate=self.period_from,
                        mutation=False,
                        quotationType=primary_quotation_type,
                        quantity=opening_balance,
                        balanceCurrency=primary_currency,
                        name="Opening balance",
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
                        name="Closing balance",
                    )
                )

            sorted_stocks = sorted(
                sorted_stocks, key=lambda s: (s.referenceDate, s.mutation)
            )

            final_security_name = security_name_registry.resolve(sec_pos_obj)

            sec = Security(
                positionId=sec_pos_idx,
                currency=primary_currency,
                quotationType=primary_quotation_type,
                securityCategory=asset_cat,
                securityName=final_security_name,
                stock=sorted_stocks,
                payment=sorted_payments,
                symbol=sec_pos_obj.symbol if sec_pos_obj.symbol is not None else None,
                country = 'US' #stub
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
        
        for stmt in all_statements:
            summary = self._get_required_field(
                stmt, 'Summary', 'Statement'
            )
            account_id = self._get_required_field(
                summary, 'Account', 'Statement Summary'
            )
            end_date = self._get_required_field(stmt, 'Date', 'Statement')
            curr = "USD"
            key = (str(account_id), str(curr))

            # Extract closing balance
            closing_net_value = None
            closing_mkt_value = None
            if summary.get('Ending Net Value') is not None:
                closing_net_value = self._to_decimal(self._get_required_field(summary,
                    'Ending Net Value', 'Account Summary'),'Ending Net Value',
                    f"Statement Summary Net Value:{account_id}"
                )
            else:
                closing_net_value = Decimal(0)
            if summary.get('Ending mkt Value') is not None:
                closing_mkt_value = self._to_decimal(self._get_required_field(
                    summary,
                    'Ending mkt Value', 'Account Summary'),'Ending mkt Value',
                    f"Statement Summary mkt Value:{account_id}"
                )
            else:
                closing_mkt_value = Decimal(0)

            closing_balance_value = closing_net_value - closing_mkt_value

            if closing_balance_value is not None:
                if key not in all_currencies_with_balances.keys() or  end_date > all_currencies_with_balances[key][
                    'date']:
                    all_currencies_with_balances[key] = {
                        'account_id': account_id,
                        'currency': curr,
                        'closing_balance': closing_balance_value,
                        'payments': [],
                        'date': end_date
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
                    name="Closing balance",
                    balanceCurrency=curr,
                    balance=closing_balance_value
                )
            else:
                logger.warning(
                    f"No closing cash balance found in CashReport "
                    f"for account {acc_id}, currency {curr} for date "
                    f"{self.period_to}."
                )
                raise ValueError(
                    f"No closing cash balance found in CashReport "
                    f"for account {acc_id}, currency {curr} for date "
                    f"{self.period_to}."
                )

            bank_account_num_str = f"{acc_id}-{curr}"
            bank_account_name_str = f"{acc_id} {curr} position"

            # Look up dates for this specific account
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
        logger.info(
            "Partial TaxStatement created with Trades, OpenPositions, "
            "and basic CashTransactions mapping."
        )

        # Fill in institution
        # Name is sufficient. Avoid setting legal identifiers avoid implying this is
        # officially from the broker.
        tax_statement.institution = Institution(
            name="Fidelity Investments",
        )
        # --- Create Client object ---
        # TODO: Handle joint accounts
        account_id = None
        summary = all_statements[0].get('Summary') if all_statements else None
        if summary is not None:
            account_id = summary.get('Account')
        if not account_id:
            logger.warning(
                'Account ID not found in first statement: %s', summary
            )

        matching_settings = next(
            (
                s for s in self.account_settings_list
                if getattr(s, 'account_number', None) == account_id
            ),
            None,
        )

        first_name, last_name = resolve_first_last_name(
            full_name=getattr(matching_settings, 'full_name', None) if matching_settings is not None else None
        )

        canton_raw = (
            getattr(matching_settings, 'canton', None)
            if matching_settings is not None else None
        )

        canton = parse_swiss_canton(canton_raw)
        if canton:
            tax_statement.canton = canton
            logger.info("Set canton from account settings: %s", canton)
        elif canton_raw:
            logger.warning(
                "Invalid canton in account settings: %r", canton_raw
            )


        client_obj = build_client(
            client_number=account_id,
            first_name=first_name,
            last_name=last_name,
        )
        if client_obj is not None:
            tax_statement.client = [client_obj]
            logger.info("Client Object added to TaxStatement")
        # --- End Client object ---
        return tax_statement

    def import_dir(self, directory: str) -> TaxStatement:
        """
    Import all PDF and JSON files in the given directory and return a TaxStatement.

    Args:
        directory (str): Path to the directory containing files to import.

    Returns:
        TaxStatement: The imported tax statement.
    """
        files = []
        for fname in os.listdir(directory):
            if fname.lower().endswith('.csv'):
                files.append(os.path.join(directory, fname))
            #elif fname.lower().endswith('.pdf') for later implementation (maybe)
            #    files.append(os.path.join(directory, fname))
            else:
                logger.warning(f"Skipping file: {fname} This type of file is not supported")
        return self.import_files(files)

def main():
    import argparse
    from datetime import datetime
    from opensteuerauszug.config import ConfigManager
    from opensteuerauszug.config.paths import resolve_config_file

    logging.basicConfig(filename='fidelity_importer.log', level=logging.INFO)
    logger.info('Started')

    parser = argparse.ArgumentParser(description="Run FidelityImporter on a directory of files.")
    parser.add_argument("directory", type=str, help="Directory containing csv files")
    parser.add_argument("period_from", type=str, help="Start date of tax period (YYYY-MM-DD)")
    parser.add_argument("period_to", type=str, help="End date of tax period (YYYY-MM-DD)")
    parser.add_argument('--config_file', type=str,default='config.toml', help="config file path",required=False)
    parser.add_argument('-strict_consistency', action='store_true', help='Enable/disable strict consistency '
                                                     'checks in importers. Defaults to strict.',required=False)
    args = parser.parse_args()

    # Parse dates
    period_from = datetime.strptime(args.period_from, "%Y-%m-%d").date()
    period_to = datetime.strptime(args.period_to, "%Y-%m-%d").date()
    config_file=args.config_file
    effective_config_file = resolve_config_file(config_file)
    config_manager = ConfigManager(config_file_path=str(effective_config_file))
    concrete_accounts_list = config_manager.get_all_account_settings_for_broker(
        "fidelity"
    )
    all_fidelity_account_settings_models = []
    for acc_settings in concrete_accounts_list:
        if acc_settings.kind == "fidelity":
            all_fidelity_account_settings_models.append(acc_settings.settings)
    if len(all_fidelity_account_settings_models) < 1:
        logger.info('No Fidelity Account Setting Found')
    importer = FidelityImporter(period_from, period_to,all_fidelity_account_settings_models,strict_consistency=args.strict_consistency)
    tax_statement = importer.import_dir(args.directory)
    if logging.DEBUG >= logging.root.level:
        from devtools import debug
        debug(tax_statement)
    logger.info('Finished')

if __name__ == "__main__":
    main()

