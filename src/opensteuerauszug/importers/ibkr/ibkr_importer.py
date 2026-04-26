import os
import logging
from typing import Final, List, Any, Dict, Optional, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from collections import defaultdict

logger = logging.getLogger(__name__)

from opensteuerauszug.model.position import SecurityPosition
from opensteuerauszug.model.ech0196 import (
    BankAccountPayment, Institution, ISINType, SecurityCategory,
    SecurityPayment, SecurityStock, TaxStatement, Client,
)
from opensteuerauszug.config.models import IbkrAccountSettings
from opensteuerauszug.importers.common import (
    CashAccountEntry,
    CashPositionData,
    PositionHints,
    SecurityNameRegistry,
    SecurityPositionData,
    aggregate_mutations,
    apply_withholding_tax_fields,
    augment_list_of_bank_accounts,
    augment_list_of_securities,
    build_client,
    build_security_payment,
    fold_cash_payments,
    parse_swiss_canton,
    resolve_first_last_name,
    to_decimal,
)
from opensteuerauszug.render.translations import get_text, Language, DEFAULT_LANGUAGE

IBKR_ASSET_CATEGORY_TO_ECH_SECURITY_CATEGORY: Final[Dict[str, SecurityCategory]] = {
    "STK": "SHARE",
    "BOND": "BOND",
    "OPT": "OPTION",
    "FOP": "OPTION",
    "FUT": "OTHER",
    "ETF": "FUND",
    "FUND": "FUND",
}
# Import ibflex components to avoid RuntimeWarning about module loading order
import ibflex
from ibflex.parser import FlexParserError
from ibflex.enums import TradeType


def is_summary_level(entry: object) -> bool:
    """Return True when an entry is marked with levelOfDetail SUMMARY."""
    level_of_detail = getattr(entry, "levelOfDetail", None)
    if level_of_detail is None:
        return False
    level_value = (
        level_of_detail.value
        if hasattr(level_of_detail, "value")
        else str(level_of_detail)
    )
    return str(level_value).upper() == "SUMMARY"


def should_skip_pseudo_account_entry(entry: object) -> bool:
    """Skip pseudo rows where accountId='-' or mapped-to-None SUMMARY rows."""
    # ibflex maps accountId="-" to None on some entry types, so
    # we only treat missing accountId rows as pseudo entries when they
    # are marked as SUMMARY.
    entry_account_id = getattr(entry, "accountId", None)
    return entry_account_id == "-" or (
        entry_account_id is None and is_summary_level(entry)
    )

class IbkrImporter:
    """
    Imports Interactive Brokers account data for a given tax period
    from Flex Query XML files.
    """
    def _get_required_field(self, data_object: object, field_name: str,
                              object_description: str) -> object:
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
    
    def _price_apply_multiplier(self, data_object: Any, price: Decimal,
                              object_description: str) -> Decimal:
        """Helper to apply multiplier to quantity."""
        if price:
            value = getattr(data_object, "assetCategory", None)
            if value in ["OPT", "FOP"]:
                multiplier = self._to_decimal(
                    self._get_required_field(data_object, "multiplier", object_description),
                    "multiplier",
                    object_description
                )
                return price * multiplier

        return price

    def _to_decimal(self, value: object | None, field_name: str,
                    object_description: str) -> Decimal:
        """Converts a value to Decimal, raising ValueError on failure."""
        return to_decimal(value, field_name, object_description)

    def _normalize_country_code(self, value: object | None) -> str | None:
        if value is None:
            return None
        country = str(value).strip().upper()
        if not country:
            return None
        return country[:2]

    def _maybe_update_security_country(
        self,
        security_country_map: Dict[SecurityPosition, str],
        sec_pos: SecurityPosition,
        country_code: str | None,
        source_label: str,
    ) -> None:
        if not country_code:
            return
        existing = security_country_map.get(sec_pos)
        if existing and existing != country_code:
            logger.warning(
                "Conflicting issuer country code for %s from %s: %s (existing: %s)",
                sec_pos.get_processing_identifier(),
                source_label,
                country_code,
                existing,
            )
            return
        if not existing:
            security_country_map[sec_pos] = country_code

    def __init__(self,
                 period_from: date,
                 period_to: date,
                 account_settings_list: List[IbkrAccountSettings],
                 render_language: Language = DEFAULT_LANGUAGE):
        """
        Initialize the importer with a tax period.

        Args:
            period_from (date): The start date of the tax period.
            period_to (date): The end date of the tax period.
            account_settings_list: List of IBKR account settings.
            render_language (Language): Language for translations.
        """
        self.period_from = period_from
        self.period_to = period_to
        self.account_settings_list = account_settings_list
        self.render_language = render_language

        if not self.account_settings_list:
            # Currently no account info is used so we keep stumm.
            logger.debug(
                "IbkrImporter initialized with an empty list of "
                "account settings."
            )
        # else:
            # print(
            #     f"IbkrImporter initialized. Primary account (if used): "
            #     f"{self.account_settings_list[0].account_id}"
            # )

    def _aggregate_stocks(self, stocks: List[SecurityStock]) -> List[SecurityStock]:
        """Aggregate buy and sell entries on the same date with equal order id if present without reordering."""
        return aggregate_mutations(stocks)

    def _parse_flex_statements(
        self,
        filenames: Sequence[str],
        *,
        file_label: str,
        log_label: str,
        error_label: str,
    ) -> list[ibflex.FlexStatement]:
        statements: list[ibflex.FlexStatement] = []

        for filename in filenames:
            if not os.path.exists(filename):
                raise FileNotFoundError(f"{file_label} not found: {filename}")
            if not filename.lower().endswith(".xml"):
                logger.warning("Skipping non-XML %s: %s", log_label, filename)
                continue

            try:
                logger.info("Parsing %s: %s", log_label, filename)
                response = ibflex.parser.parse(filename)
                if response and response.FlexStatements:
                    for stmt in response.FlexStatements:
                        if should_skip_pseudo_account_entry(stmt):
                            logger.info(
                                "Skipping FlexStatement with pseudo accountId in %s",
                                filename,
                            )
                            continue
                        logger.info(
                            "Successfully parsed statement for account: %s, Period: %s to %s",
                            stmt.accountId,
                            stmt.fromDate,
                            stmt.toDate,
                        )
                        statements.append(stmt)
                else:
                    logger.warning(
                        "No FlexStatements found in %s or response was empty.",
                        filename,
                    )
            except FlexParserError as e:
                raise ValueError(
                    f"Failed to parse {error_label} {filename} with ibflex: {e}"
                )
            except Exception as e:
                raise RuntimeError(
                    f"An unexpected error occurred while parsing {filename}: {e}"
                )

        return statements

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
        cash_tx: ibflex.CashTransaction,
        description: str,
    ) -> SecurityPosition:
        security_id = self._get_required_field(cash_tx, 'conid', 'CashTransaction')
        isin_attr = cash_tx.isin
        symbol_attr = cash_tx.symbol
        return SecurityPosition(
            depot=account_id,
            valor=None,
            isin=ISINType(isin_attr) if isin_attr else None,
            symbol=str(security_id),
            description=(
                f"{description} ({symbol_attr})" if symbol_attr else description
            ),
        )

    def _apply_withholding_tax_fields(
        self,
        payment: SecurityPayment,
        amount: Decimal,
        currency: str,
        tx_type: ibflex.CashAction,
    ) -> None:
        if tx_type != ibflex.CashAction.WHTAX:
            return
        apply_withholding_tax_fields(payment, amount, currency)

    def _build_security_payment(
        self,
        *,
        payment_date: date,
        description: str,
        currency: str,
        amount: Decimal,
        tx_type: ibflex.CashAction,
    ) -> SecurityPayment:
        return build_security_payment(
            payment_date=payment_date,
            description=description,
            currency=currency,
            amount=amount,
            broker_label=tx_type.value,
            is_withholding=tx_type == ibflex.CashAction.WHTAX,
            is_securities_lending=tx_type == ibflex.CashAction.PAYMENTINLIEU,
        )

    def _import_corrections_flex_files(
        self,
        corrections_filenames: Sequence[str],
        processed_security_positions: Dict[SecurityPosition, SecurityPositionData],
    ) -> None:
        corrections_flex_statements = self._parse_flex_statements(
            corrections_filenames,
            file_label="Corrections Flex file",
            log_label="corrections Flex statement",
            error_label="corrections Flex file",
        )

        corrections_count = 0
        for stmt in corrections_flex_statements:
            account_id = self._get_required_field(
                stmt,
                'accountId',
                'FlexStatement (corrections)',
            )
            if not stmt.CashTransactions:
                continue

            for cash_tx in stmt.CashTransactions:
                if should_skip_pseudo_account_entry(cash_tx):
                    continue

                settle_date = getattr(cash_tx, 'settleDate', None)
                if settle_date is None:
                    continue
                if isinstance(settle_date, str):
                    settle_date = datetime.strptime(settle_date, "%Y%m%d").date()
                if settle_date < self.period_from or settle_date > self.period_to:
                    continue

                security_id = cash_tx.conid
                if not security_id:
                    continue

                tx_type = cash_tx.type
                if tx_type is None:
                    continue

                if tx_type != ibflex.CashAction.WHTAX:
                    continue

                description = self._get_required_field(
                    cash_tx,
                    'description',
                    'CashTransaction (corrections)',
                )
                amount = self._to_decimal(
                    self._get_required_field(
                        cash_tx,
                        'amount',
                        'CashTransaction (corrections)',
                    ),
                    'amount',
                    f"CashTransaction (corrections) {description[:30]}",
                )
                currency = self._get_required_field(
                    cash_tx,
                    'currency',
                    'CashTransaction (corrections)',
                )

                sec_pos_key = self._find_processed_security_position(
                    processed_security_positions,
                    account_id,
                    security_id,
                )
                if sec_pos_key is None:
                    logger.warning(
                        "Corrections flex: skipping withholding correction for unknown security conid=%s (%s)",
                        security_id,
                        description,
                    )
                    continue

                processed_security_positions[sec_pos_key]['payments'].append(
                    self._build_security_payment(
                        payment_date=settle_date,
                        description=description,
                        currency=currency,
                        amount=amount,
                        tx_type=tx_type,
                    )
                )
                corrections_count += 1

        if corrections_count:
            logger.info(
                "Imported %d withholding-tax correction(s) from corrections flex file(s).",
                corrections_count,
            )


    def import_files(self, filenames: List[str], corrections_filenames: Optional[List[str]] = None) -> TaxStatement:
        """
        Import data from IBKR Flex Query XMLs and return a TaxStatement.

        Args:
            filenames: List of file paths to import (XML).
            corrections_filenames: Optional list of "corrections" flex query XML
                files covering the period after the tax year (e.g. Jan–Mar of
                the following year).  Only CashTransactions whose settleDate
                falls within [period_from, period_to] are imported from these
                files, allowing withholding-tax reversals to be netted against
                original deductions.

        Returns:
            The imported tax statement.
        """
        all_flex_statements = self._parse_flex_statements(
            filenames,
            file_label="IBKR Flex statement file",
            log_label="IBKR Flex statement",
            error_label="IBKR Flex XML file",
        )

        if not all_flex_statements:
            # This might be an error or just a case of no relevant data.
            # "If data is missing do a hard error" - might need adjustment
            logger.warning(
                "No Flex statements were successfully parsed. "
                "Returning empty TaxStatement."
            )
            return TaxStatement(
                minorVersion=1, periodFrom=self.period_from,
                periodTo=self.period_to,
                taxPeriod=self.period_from.year, listOfSecurities=None,
                listOfBankAccounts=None
            )

        # Key: SecurityPosition or tuple for cash. Value: dict with 'stocks', 'payments'
        processed_security_positions: defaultdict[SecurityPosition, SecurityPositionData] = \
            defaultdict(lambda: {'stocks': [], 'payments': []})

        # Best-name-wins registry for security display names.
        security_name_registry = SecurityNameRegistry()

        processed_cash_positions: defaultdict[tuple, CashPositionData] = \
            defaultdict(lambda: {'stocks': [], 'payments': []})
        security_country_map: Dict[SecurityPosition, str] = {}

        # Map to store assetCategory and subCategory for each security
        security_asset_category_map: Dict[SecurityPosition, tuple[str, Optional[str]]] = {}
        rights_issue_positions: set[SecurityPosition] = set()

        for stmt in all_flex_statements:
            account_id = self._get_required_field(
                stmt, 'accountId', 'FlexStatement'
            )
            # account_id_processed = account_id # Keep track for summary
            logger.info(f"Processing statement for account: {account_id}")

            def should_skip_entry(entry: Any, entry_label: str) -> bool:
                if should_skip_pseudo_account_entry(entry):
                    logger.info(
                        "Skipping %s entry with pseudo accountId in account %s",
                        entry_label,
                        account_id,
                    )
                    return True
                return False

            # --- Process Trades ---
            if stmt.Trades:
                for trade in stmt.Trades:
                    if not isinstance(trade, ibflex.Trade):
                        # Skipping summary objects.
                        # It seems tempting to use SymbolSummary but for FX these
                        # are actually for the full report period, so have no fixed date.
                        continue
                    if should_skip_entry(trade, "Trade"):
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
                    isin = trade.isin  # Optional field always present on dataclass
                    valor = None  # Flex does not typically provide Valor

                    quantity = self._to_decimal(
                        self._get_required_field(trade, 'quantity', 'Trade'),
                        'quantity', f"Trade {symbol}"
                    )
                    trade_price = self._to_decimal(
                        self._get_required_field(trade, 'tradePrice', 'Trade'),
                        'tradePrice', f"Trade {symbol}"
                    )
                    trade_price = self._price_apply_multiplier(trade, trade_price, f"Trade {symbol}")

                    trade_money = self._to_decimal(
                        self._get_required_field(trade, 'tradeMoney', 'Trade'),
                        'tradeMoney', f"Trade {symbol}"
                    )
                    currency = self._get_required_field(
                        trade, 'currency', 'Trade'
                    )
                    # 'BUY' or 'SELL'
                    buy_sell = self._get_required_field(trade, 'buySell', 'Trade')

                    transaction_type: TradeType = getattr(trade, 'transactionType', None)
                    expiry_date = getattr(trade, 'expiry', None)
                    close_price = getattr(trade, 'closePrice', None)

                    ib_commission = self._to_decimal(
                        trade.ibCommission if trade.ibCommission is not None else '0',
                        'ibCommission', f"Trade {symbol}"
                    )

                    if asset_category == "CASH":
                        # FX trades are neutral to the portfolio, so we skip them.
                        logger.debug("Skipped CASH trade {symbol}")
                        continue

                    if asset_category not in [
                        "STK", "OPT", "FUT", "BOND", "ETF", "FUND", "FOP"
                    ]:
                        logger.warning(
                            f"Skipping trade for unhandled asset "
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

                    # Update name metadata (Priority: 8 for Trades)
                    security_name_registry.update(sec_pos, f"{description} ({symbol})", 8)

                    # Store assetCategory and subCategory
                    sub_category = getattr(trade, 'subCategory', None)
                    if sec_pos not in security_asset_category_map:
                        security_asset_category_map[sec_pos] = (asset_category, sub_category)

                    trade_country = self._normalize_country_code(
                        getattr(trade, 'issuerCountryCode', None)
                    )
                    self._maybe_update_security_country(
                        security_country_map,
                        sec_pos,
                        trade_country,
                        "Trade",
                    )

                    unit_price = trade_price if trade_price != Decimal(0) else None
                    name = get_text(buy_sell.value.lower(), self.render_language)
                    # Trade price is 0 for expired, assigned or exercised options.
                    if (trade_price == Decimal(0) and asset_category in ["OPT", "FOP"]):
                        if transaction_type is None:
                            raise ValueError(f"Transaction type is missing for category {asset_category} with zero price")
                        if transaction_type == TradeType.BOOKTRADE:
                            if close_price is None:
                                raise ValueError(f"Close price is missing for category {asset_category} with zero price")
                            if close_price == Decimal(0) and (expiry_date is None or expiry_date is not None and expiry_date == trade_date):
                                # For expired options with zero close price, we can assume they expired worthless. However, we need corresponding OptionEAE entry to be sure. But taxwise it does not matter.
                                name = get_text('option_expiration', self.render_language)
                            elif close_price != Decimal(0):
                                name = get_text('option_assignment', self.render_language)   # can be assignemnt or exercise, but for that we would need to link the trade to the corresponding OptionEAE entry
                        unit_price = Decimal(0)

                    stock_mutation = SecurityStock(
                        referenceDate=trade_date,
                        mutation=True,
                        quantity=quantity,
                        unitPrice=unit_price,
                        name=name,
                        orderId=trade.ibOrderID,
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
                    if should_skip_entry(open_pos, "OpenPosition"):
                        continue
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
                    isin = open_pos.isin
                    valor = None

                    quantity = self._to_decimal(
                        self._get_required_field(open_pos, 'position',
                                                 'OpenPosition'),
                        'position', f"OpenPosition {symbol}"
                    )
                    currency = self._get_required_field(
                        open_pos, 'currency', 'OpenPosition'
                    )

                    if asset_category not in [
                        "STK", "OPT", "FUT", "BOND", "ETF", "FUND", "FOP"
                    ]:
                        logger.warning(
                            f"Skipping open position for unhandled "
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

                    # Update name metadata (Priority: 10 for OpenPositions)
                    security_name_registry.update(sec_pos, f"{description} ({symbol})", 10)

                    # Store assetCategory and subCategory
                    sub_category = getattr(open_pos, 'subCategory', None)
                    if sec_pos not in security_asset_category_map:
                        security_asset_category_map[sec_pos] = (asset_category, sub_category)

                    position_country = self._normalize_country_code(
                        getattr(open_pos, 'issuerCountryCode', None)
                    )
                    self._maybe_update_security_country(
                        security_country_map,
                        sec_pos,
                        position_country,
                        "OpenPosition",
                    )

                    mark_price = None
                    if getattr(open_pos, 'markPrice', None) is not None:
                        mark_price = self._to_decimal(open_pos.markPrice, 'markPrice', f"OpenPosition {symbol}")
                        mark_price = self._price_apply_multiplier(open_pos, mark_price, f"OpenPosition {symbol}")
                    
                    pos_value = None
                    if getattr(open_pos, 'positionValue', None) is not None:
                        pos_value = self._to_decimal(open_pos.positionValue, 'positionValue', f"OpenPosition {symbol}")

                    balance_stock = SecurityStock(
                        # Balance as of the period end + 1
                        referenceDate=end_plus_one,
                        mutation=False,
                        quantity=quantity,
                        balanceCurrency=currency,
                        quotationType="PIECE",
                        unitPrice=mark_price,
                        balance=pos_value,
                    )
                    processed_security_positions[sec_pos]['stocks'].append(
                        balance_stock
                    )

            # --- Process Transfers ---
            if stmt.Transfers:
                for transfer in stmt.Transfers:
                    if should_skip_entry(transfer, "Transfer"):
                        continue
                    asset_category = self._get_required_field(
                        transfer, 'assetCategory', 'Transfer'
                    )
                    asset_cat_val = (
                        asset_category.value if hasattr(asset_category, 'value') else str(asset_category)
                    )
                    if str(asset_cat_val).upper() == 'CASH':
                        continue

                    tx_date = transfer.date
                    if tx_date is None:
                        tx_dt = transfer.dateTime
                        if tx_dt is not None:
                            tx_date = tx_dt.date() if hasattr(tx_dt, 'date') else tx_dt
                    if tx_date is None:
                        raise ValueError('Transfer missing date/dateTime')

                    symbol = self._get_required_field(transfer, 'symbol', 'Transfer')
                    description = self._get_required_field(
                        transfer, 'description', 'Transfer'
                    )
                    conid = str(self._get_required_field(transfer, 'conid', 'Transfer'))
                    isin = transfer.isin

                    quantity = self._to_decimal(
                        self._get_required_field(transfer, 'quantity', 'Transfer'),
                        'quantity', f"Transfer {symbol}"
                    )

                    direction = transfer.direction
                    direction_val = direction.value.upper() if direction else None
                    is_cancel = ibflex.Code.CANCEL in (transfer.code or ())
                    if direction_val == 'OUT' and quantity > 0 and not is_cancel:
                        raise ValueError(
                            f"Transfer direction OUT but quantity {quantity} positive"
                            f" for {symbol}"
                        )
                    if direction_val == 'IN' and quantity < 0 and not is_cancel:
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
                    transfer_type_val = transfer_type.value
                    account = self._get_required_field(transfer, 'account', 'Transfer')

                    sec_pos = SecurityPosition(
                        depot=account_id,
                        valor=None,
                        isin=ISINType(isin) if isin else None,
                        symbol=conid,
                        description=f"{description} ({symbol})",
                    )

                    # Update name metadata (Priority: 5 for Transfers)
                    security_name_registry.update(sec_pos, f"{description} ({symbol})", 5)

                    stock_mutation = SecurityStock(
                        referenceDate=tx_date,
                        mutation=True,
                        quantity=quantity,
                        name=f"{transfer_type_val} {account}" + (" (Cancelled)" if is_cancel else ""),
                        balanceCurrency=currency,
                        quotationType="PIECE",
                    )

                    processed_security_positions[sec_pos]['stocks'].append(
                        stock_mutation
                    )

            # --- Process Corporate Actions ---
            if stmt.CorporateActions:
                for action in stmt.CorporateActions:
                    if should_skip_entry(action, "CorporateAction"):
                        continue
                    # CorporateActions have dates with time stamps, which can be at end of business etc
                    # to avoid this we assume that the reportDate is always the effective date when we see
                    # a difference in the amount of securities.
                    action_date = self._get_required_field(action, "reportDate", "CorporateAction")

                    if hasattr(action_date, "date"):
                        action_date = action_date.date()
                    elif isinstance(action_date, str):
                        date_part = action_date.split(";")[0].split("T")[0]
                        action_date = date.fromisoformat(date_part)

                    symbol = self._get_required_field(action, "symbol", "CorporateAction")
                    description = self._get_required_field(action, "description", "CorporateAction")
                    conid = str(self._get_required_field(action, "conid", "CorporateAction"))
                    isin = action.isin

                    quantity = self._to_decimal(
                        self._get_required_field(action, "quantity", "CorporateAction"),
                        "quantity",
                        f"CorporateAction {symbol}",
                    )
                    currency = self._get_required_field(action, "currency", "CorporateAction")

                    action_description = getattr(action, "actionDescription", None) or description

                    sec_pos = SecurityPosition(
                        depot=account_id,
                        valor=None,
                        isin=ISINType(isin) if isin else None,
                        symbol=conid,
                        description=f"{description} ({symbol})",
                    )

                    # Update name metadata for CorporateActions
                    # Priority logic:
                    # - Issuer available: 4
                    # - Description only (short): 1
                    # - Description only (long): 0 (use symbol fallback via helper logic if priority 0 beats existing)
                    # Actually, if description is long, we prefer symbol.
                    # Let's say:
                    # - Issuer: 4
                    # - Description <= 50 chars: 1
                    # - Description > 50 chars: -1 (Don't use if possible, prefer symbol if nothing else)

                    issuer = getattr(action, "issuer", None)
                    ca_name = f"{description} ({symbol})"
                    ca_priority = 1

                    if issuer:
                        ca_name = f"{issuer} ({symbol})"
                        ca_priority = 4
                    elif len(description) > 50:
                        # Long description and no issuer. Prefer symbol (short name).
                        ca_name = f"{symbol} ({symbol})"
                        ca_priority = 2
                    else:
                        ca_name = f"{description} ({symbol})"
                        ca_priority = 3

                    security_name_registry.update(sec_pos, ca_name, ca_priority)

                    sub_category = getattr(action, "subCategory", None)
                    if sub_category == "RIGHT":
                        rights_issue_positions.add(sec_pos)

                    stock_mutation = SecurityStock(
                        referenceDate=action_date,
                        mutation=True,
                        quantity=quantity,
                        name=action_description,
                        balanceCurrency=currency,
                        quotationType="PIECE",
                    )

                    processed_security_positions[sec_pos]["stocks"].append(
                        stock_mutation
                    )

            # --- Process Cash Transactions ---
            if stmt.CashTransactions:
                for cash_tx in stmt.CashTransactions:
                    if should_skip_entry(cash_tx, "CashTransaction"):
                        continue
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

                    security_id = cash_tx.conid
                    tx_type = cash_tx.type
                    if tx_type is None:
                        raise ValueError(f"CashTransaction type is missing for {description}")

                    # Skip fees even if they are associated with a security (e.g., ADR fees)
                    if tx_type in [ibflex.CashAction.FEES, ibflex.CashAction.ADVISORFEES]:
                        logger.warning(f"Fees paid for {description} are ignored for statement.")
                        continue

                    if security_id:
                        tx_type_str = tx_type.value
                        tx_type_str_lower = str(tx_type_str).lower()
                        assert 'interest' not in tx_type_str_lower

                        sec_pos_key = self._find_processed_security_position(
                            processed_security_positions,
                            account_id,
                            security_id,
                        )

                        sym_attr = cash_tx.symbol

                        if sec_pos_key is None:
                            sec_pos_key = self._build_cash_transaction_security_position(
                                account_id,
                                cash_tx,
                                description,
                            )

                        # Update name metadata (Priority: 0 for CashTransactions - lowest)
                        # Use description or symbol if description is generic?
                        # Usually description in CashTx is like "Dividend ...". Not great for security name.
                        # But if it's the only source, it's better than nothing.
                        security_name_registry.update(
                            sec_pos_key,
                            f"{description} ({sym_attr})" if sym_attr else description,
                            0
                        )

                        sec_payment = self._build_security_payment(
                            payment_date=tx_date,
                            description=description,
                            currency=currency,
                            amount=amount,
                            tx_type=tx_type,
                        )
                        processed_security_positions[sec_pos_key]['payments'].append(
                            sec_payment
                        )
                    else:
                        if tx_type in [ibflex.CashAction.DEPOSITWITHDRAW]:
                            # Not Tax Relant event
                            continue
                        elif tx_type in [ibflex.CashAction.BROKERINTPAID]:
                            # Interst paid due to negative balance: description starting with "<CURRENCY> DEBIT INT FOR"
                            if description.startswith(f"{currency} DEBIT INT FOR"):
                                # Tax relevant event. Fall through to create a bank payment.
                                pass
                            else:
                                # TODO: CREDIT INT is charged on positive balance and would belong to fees (not liabilities).
                                logger.warning(f"Broker credit interest payment {description} with amount {amount} is not handled, would belong to fees.")
                                continue
                        elif tx_type in [ibflex.CashAction.FEES]:
                            # TODO: Optionally create a costs sections.
                            logger.warning(f"Fees paid for {description} are ignored for statement.")
                            continue
                        elif tx_type in [ibflex.CashAction.ADVISORFEES]:
                            # TODO: Optionally create a costs sections.
                            logger.warning(f"Fees paid for {description} are ignored for statement.")
                            continue
                        elif tx_type in [ibflex.CashAction.BROKERINTRCVD]:
                            # Tax relevant event. Fall through to create a bank payment.
                            pass
                        elif tx_type in [ibflex.CashAction.WHTAX]:
                            # Withholding tax not linked to a security (e.g. yield enhancement).
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

        # --- Process Corrections Flex Files ---
        # Import withholding-tax corrections from a post-year-end flex export.
        # Only CashTransactions whose settleDate falls within the tax period
        # are included, so that reversals/adjustments are netted against the
        # original deductions automatically during reconciliation.
        if corrections_filenames:
            self._import_corrections_flex_files(
                corrections_filenames,
                processed_security_positions,
            )

        # --- Assemble the partial TaxStatement and augment it via the shared
        # post-processing stage. The client/institution/canton block below
        # continues to write onto the same object.
        tax_statement = TaxStatement(
            minorVersion=1,
            periodFrom=self.period_from,
            periodTo=self.period_to,
            taxPeriod=self.period_from.year,
        )

        ignore_rights_issues_by_account: Dict[str, bool] = {
            s.account_number: getattr(s, "ignore_rights_issues", False)
            for s in self.account_settings_list
            if getattr(s, "account_number", None)
        }

        def _hints_for(sec_pos: SecurityPosition) -> PositionHints:
            asset_cat, _sub_category = security_asset_category_map.get(
                sec_pos, ("STK", None)
            )
            sec_category = IBKR_ASSET_CATEGORY_TO_ECH_SECURITY_CATEGORY.get(asset_cat)
            if not sec_category:
                raise ValueError(f"Unknown asset category: {asset_cat}")
            is_rights = sec_pos in rights_issue_positions
            skip_if_zero = is_rights and ignore_rights_issues_by_account.get(
                sec_pos.depot, False
            )
            return PositionHints(
                security_category=sec_category,
                country=security_country_map.get(sec_pos, "US"),
                is_rights_issue=is_rights,
                skip_if_zero=skip_if_zero,
            )

        augment_list_of_securities(
            tax_statement,
            processed_security_positions,
            name_registry=security_name_registry,
            hints_for=_hints_for,
        )

        # --- Collect per-account dateOpened / dateClosed + CashReport seeds ---
        account_dates: Dict[str, Dict[str, date | None]] = {}
        for s_stmt in all_flex_statements:
            stmt_account_id = self._get_required_field(
                s_stmt, 'accountId', 'FlexStatement'
            )
            if s_stmt.AccountInformation:
                acc_info = s_stmt.AccountInformation
                account_dates[stmt_account_id] = {
                    'dateOpened': acc_info.dateOpened,
                    'dateClosed': acc_info.dateClosed,
                }

        seed_entries: List[CashAccountEntry] = []
        for s_stmt in all_flex_statements:
            account_id = s_stmt.accountId
            if not s_stmt.CashReport:
                continue
            for cash_report_currency_obj in s_stmt.CashReport:
                if should_skip_pseudo_account_entry(cash_report_currency_obj):
                    logger.info(
                        "Skipping CashReport entry with pseudo accountId in account %s",
                        account_id,
                    )
                    continue
                curr = cash_report_currency_obj.currency
                if curr == "BASE_SUMMARY":
                    continue

                closing_balance_value: Optional[Decimal] = None
                if cash_report_currency_obj.endingCash is not None:
                    closing_balance_value = self._to_decimal(
                        cash_report_currency_obj.endingCash,
                        'endingCash',
                        f"CashReport {account_id} {curr}",
                    )
                elif (
                    cash_report_currency_obj.balance is not None
                    and cash_report_currency_obj.reportDate == self.period_to
                ):
                    closing_balance_value = self._to_decimal(
                        cash_report_currency_obj.balance,
                        'balance',
                        f"CashReport {account_id} {curr}",
                    )

                if closing_balance_value is None:
                    continue
                dates_for_account = account_dates.get(account_id, {})
                seed_entries.append(
                    CashAccountEntry(
                        account_id=account_id,
                        currency=curr,
                        closing_balance=closing_balance_value,
                        name=f"{account_id} {curr}",
                        number=f"{account_id}-{curr}",
                        opening_date=dates_for_account.get('dateOpened'),
                        closing_date=dates_for_account.get('dateClosed'),
                    )
                )

        cash_entries = fold_cash_payments(seed_entries, processed_cash_positions)
        augment_list_of_bank_accounts(tax_statement, cash_entries)

        logger.info(
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
        # TODO: Handle joint accounts
        client_obj: Optional[Client] = None
        if all_flex_statements:
            first_statement = all_flex_statements[0]
            acc_info = getattr(first_statement, 'AccountInformation', None)
            if acc_info:
                canton = parse_swiss_canton(getattr(acc_info, 'stateResidentialAddress', None))
                if canton:
                    tax_statement.canton = canton
                    logger.info(f"Set canton from IBKR stateResidentialAddress: {canton}")

                client_first_name, client_last_name = resolve_first_last_name(
                    first_name=getattr(acc_info, 'firstName', None),
                    last_name=getattr(acc_info, 'lastName', None),
                    full_name=getattr(acc_info, 'name', None),
                    account_holder_name=getattr(acc_info, 'accountHolderName', None),
                )
                client_obj = build_client(
                    client_number=getattr(acc_info, 'accountId', None),
                    first_name=client_first_name,
                    last_name=client_last_name,
                )
        if client_obj:
            tax_statement.client = [client_obj]
        # --- End Client object ---

        return tax_statement


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    logger.info("IbkrImporter module loaded.")
    # Example usage:
    # from .config.models import IbkrAccountSettings
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
    logger.info(
        "Example usage in __main__ needs IbkrAccountSettings to be defined "
        "in config.models and 'pip install ibflex devtools'."
    )
