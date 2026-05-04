"""Degiro broker importer.

Converts Degiro's Account.csv + Portfolio.csv exports into a TaxStatement
following the same accumulator pattern used by the IBKR and Fidelity importers.

Key design choices
------------------
* ISIN is used as both ``symbol`` and ``isin`` on SecurityPosition (Degiro
  provides no tickers; ISINs satisfy the no-space requirement).
* ``value_date`` (settlement date from Account.csv) is used as
  ``referenceDate`` on mutation SecurityStock entries.
* Security category defaults to ``"FUND"`` when the product name contains
  ``"ETF"`` or ``"UCITS"``, ``"SHARE"`` otherwise.
* Country is derived from the first two characters of the ISIN (ISO 3166-1
  alpha-2 country code embedded in the ISIN standard).
* Partial fills sharing the same ``Order Id`` each produce their own
  SecurityStock; ``aggregate_mutations()`` merges them in post-processing.
* Securities present in Account.csv but absent from Portfolio.csv (e.g.
  delisted equities) get an explicit zero closing-balance stock so the
  reconciler can backward-synthesize the correct opening balance.
"""

import logging
import os
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from opensteuerauszug.config.models import DegiroAccountSettings
from opensteuerauszug.importers.common import (
    CashAccountEntry,
    PositionHints,
    SecurityNameRegistry,
    SecurityPositionData,
    apply_withholding_tax_fields,
    augment_list_of_bank_accounts,
    augment_list_of_securities,
    build_client,
    build_security_payment,
    parse_swiss_canton,
    resolve_first_last_name,
)
from opensteuerauszug.model.ech0196 import (
    ISINType,
    Institution,
    SecurityCategory,
    SecurityStock,
    TaxStatement,
)
from opensteuerauszug.model.position import SecurityPosition

from .account_csv_parser import (
    DegiroRow,
    DegiroRowKind,
    classify_row,
    load_account_csv,
)
from .portfolio_csv_parser import PortfolioEntry, load_portfolio_csv

logger = logging.getLogger(__name__)

# Regex for trade description lines, e.g.:
#   Buy 60 iShares S&P 500 Info Technolg Sctr UCITS ETF USD A@20.08 EUR (IE00B3WJKG14)
#   Sell 10 Vanguard S&P 500 UCITS ETF USD Dis@71.00 EUR (IE00B3XXRP09)
_TRADE_RE = re.compile(
    r"^(Buy|Sell)\s+(\d+(?:\.\d+)?)\s+(.+?)@([\d.]+)\s+([A-Z]{3})"
    r"(?:\s+\([A-Z0-9]{12}\))?$"
)

# Regex for delisting lines, e.g.:
#   DELISTING: Sell 10 Activision Blizzard Inc@0 USD (US00507V1098)
_DELISTING_RE = re.compile(
    r"^DELISTING:\s+Sell\s+(\d+(?:\.\d+)?)\s+.+@([\d.]+)\s+([A-Z]{3})"
)

# ISIN validation pattern (matches pydantic field constraint on SecurityPosition)
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def _valid_isin(isin: str) -> bool:
    return bool(_ISIN_RE.match(isin))


def _infer_category(product: str) -> SecurityCategory:
    if "ETF" in product or "UCITS" in product:
        return "FUND"
    return "SHARE"


def _country_from_isin(isin: str) -> str:
    return isin[:2].upper() if len(isin) >= 2 else "US"


class DegiroImporter:
    """Import Degiro Account.csv + Portfolio.csv for a given tax period."""

    def __init__(
        self,
        period_from: date,
        period_to: date,
        account_settings_list: List[DegiroAccountSettings],
    ) -> None:
        self.period_from = period_from
        self.period_to = period_to
        self.account_settings_list = account_settings_list

        self._depot_id: str = (
            account_settings_list[0].account_number
            if account_settings_list
            else "DEGIRO"
        )

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def import_dir(self, directory: str) -> TaxStatement:
        """Discover Account.csv + Portfolio.csv in *directory* and import."""
        account_csv = os.path.join(directory, "Account.csv")
        portfolio_csv = os.path.join(directory, "Portfolio.csv")
        if not os.path.exists(account_csv):
            raise FileNotFoundError(f"Account.csv not found in {directory}")
        if not os.path.exists(portfolio_csv):
            raise FileNotFoundError(f"Portfolio.csv not found in {directory}")
        return self.import_files(account_csv, portfolio_csv)

    def import_files(self, account_csv: str, portfolio_csv: str) -> TaxStatement:
        """Import from explicit file paths and return a TaxStatement."""
        account_rows = load_account_csv(account_csv)
        portfolio_entries = load_portfolio_csv(portfolio_csv)

        # Account.csv is reverse-chronological; reverse to chronological.
        account_rows_chrono = list(reversed(account_rows))

        # Accumulators
        name_registry = SecurityNameRegistry()
        processed_security_positions: Dict[SecurityPosition, SecurityPositionData] = (
            defaultdict(lambda: SecurityPositionData({"stocks": [], "payments": []}))
        )

        # Step 1 – Seed closing balances from Portfolio.csv
        cash_balance: Optional[Decimal] = None
        cash_currency: str = "CHF"

        end_plus_one = self.period_to + timedelta(days=1)

        # Aggregate duplicate ISINs before seeding (e.g. two lots of same fund)
        isin_to_quantity: Dict[str, Decimal] = {}
        isin_to_entry: Dict[str, PortfolioEntry] = {}
        for entry in portfolio_entries:
            if entry.is_cash:
                cash_balance = entry.local_amount
                cash_currency = entry.local_currency or "CHF"
                continue
            if not _valid_isin(entry.isin):
                logger.debug("Skipping portfolio entry with non-ISIN: %s", entry.isin)
                continue
            if entry.isin in isin_to_quantity:
                isin_to_quantity[entry.isin] += entry.amount
            else:
                isin_to_quantity[entry.isin] = entry.amount
                isin_to_entry[entry.isin] = entry

        for isin, total_qty in isin_to_quantity.items():
            entry = isin_to_entry[isin]
            sec_pos = self._make_sec_pos(isin, entry.product)
            name_registry.update(sec_pos, entry.product, 5)
            currency = entry.local_currency or "EUR"
            balance_stock = SecurityStock(
                referenceDate=end_plus_one,
                mutation=False,
                quantity=total_qty,
                balanceCurrency=currency,
                quotationType="PIECE",
                unitPrice=entry.closing_price,
            )
            processed_security_positions[sec_pos]["stocks"].append(balance_stock)

        # Step 2 – Build lookup tables before the main loop
        # div_tax_lookup: (value_date, isin) -> list of DIVIDEND_TAX rows
        div_tax_lookup: Dict[tuple, List[DegiroRow]] = defaultdict(list)
        for row in account_rows_chrono:
            if classify_row(row) == DegiroRowKind.DIVIDEND_TAX and row.isin:
                div_tax_lookup[(row.value_date, row.isin)].append(row)

        # order_id_groups: order_id -> list of rows
        order_id_groups: Dict[str, List[DegiroRow]] = defaultdict(list)
        for row in account_rows_chrono:
            if row.order_id:
                order_id_groups[row.order_id].append(row)

        # Step 3 – Main loop
        consumed_rows: set = set()

        for row in account_rows_chrono:
            if row.raw_row in consumed_rows:
                continue
            kind = classify_row(row)

            if kind == DegiroRowKind.BUY_SELL:
                self._process_buy_sell(
                    row,
                    processed_security_positions,
                    name_registry,
                    order_id_groups,
                    consumed_rows,
                )

            elif kind == DegiroRowKind.DIVIDEND:
                if not row.isin or not _valid_isin(row.isin):
                    logger.warning("DIVIDEND row %d has no valid ISIN", row.raw_row)
                    continue
                self._process_dividend(
                    row, processed_security_positions, name_registry, div_tax_lookup
                )

            elif kind == DegiroRowKind.DELISTING:
                if not row.isin or not _valid_isin(row.isin):
                    logger.warning("DELISTING row %d has no valid ISIN", row.raw_row)
                    continue
                self._process_delisting(
                    row, processed_security_positions, name_registry
                )

            elif kind == DegiroRowKind.CORPORATE_CASH:
                if not row.isin or not _valid_isin(row.isin):
                    logger.warning(
                        "CORPORATE_CASH row %d has no valid ISIN", row.raw_row
                    )
                    continue
                self._process_corporate_cash(
                    row, processed_security_positions, name_registry
                )

            elif kind == DegiroRowKind.UNKNOWN:
                raise NotImplementedError(
                    f"Unknown DEGIRO row kind for description {row.description!r} "
                    f"(row {row.raw_row}). The row may be tax-relevant; please report "
                    "this as a bug so support can be added."
                )
            else:
                logger.debug(
                    "Skipping %s row: %r (row %d)", kind.name, row.description, row.raw_row
                )

        # Step 4 – Add zero closing balance for positions with no balance checkpoint.
        # Necessary for securities that had transactions but were fully closed
        # (e.g. delisted) and therefore do not appear in Portfolio.csv.
        for sec_pos, data in processed_security_positions.items():
            stocks = data["stocks"]
            if not any(not s.mutation for s in stocks):
                mutation_stocks = [s for s in stocks if s.mutation]
                currency = (
                    mutation_stocks[-1].balanceCurrency if mutation_stocks else "USD"
                )
                stocks.append(
                    SecurityStock(
                        referenceDate=end_plus_one,
                        mutation=False,
                        quantity=Decimal("0"),
                        balanceCurrency=currency,
                        quotationType="PIECE",
                    )
                )

        # Step 5 – Build the statement scaffold
        statement = TaxStatement(
            minorVersion=1,
            periodFrom=self.period_from,
            periodTo=self.period_to,
            taxPeriod=self.period_from.year,
            listOfSecurities=None,
            listOfBankAccounts=None,
        )
        statement.institution = Institution(name="DEGIRO")

        # Step 6 – Client from settings
        settings = self.account_settings_list[0] if self.account_settings_list else None
        if settings:
            first_name, last_name = resolve_first_last_name(
                full_name=getattr(settings, "full_name", None)
            )
            canton_raw = getattr(settings, "canton", None)
            canton = parse_swiss_canton(canton_raw)
            if canton:
                statement.canton = canton
            client_obj = build_client(
                client_number=settings.account_number,
                first_name=first_name,
                last_name=last_name,
            )
            if client_obj is not None:
                statement.client = [client_obj]

        # Step 7 – Augment securities
        def _hints_for(sec_pos: SecurityPosition) -> PositionHints:
            isin = sec_pos.symbol or ""
            country = _country_from_isin(isin)
            desc = sec_pos.description or sec_pos.symbol or ""
            category: SecurityCategory = _infer_category(desc)
            return PositionHints(security_category=category, country=country)

        augment_list_of_securities(
            statement,
            processed_security_positions,
            name_registry=name_registry,
            hints_for=_hints_for,
            strict_consistency=False,
            assume_zero_if_no_balances=True,
        )

        # Step 8 – Augment bank accounts
        if cash_balance is not None:
            cash_entry = CashAccountEntry(
                account_id=self._depot_id,
                currency=cash_currency,
                closing_balance=cash_balance,
                payments=[],
                country="NL",
                name=f"{self._depot_id} {cash_currency}",
                number=f"{self._depot_id}-{cash_currency}",
            )
            augment_list_of_bank_accounts(statement, [cash_entry])

        return statement

    # ------------------------------------------------------------------
    # Row-type handlers
    # ------------------------------------------------------------------

    def _make_sec_pos(self, isin: str, product: str) -> SecurityPosition:
        return SecurityPosition(
            depot=self._depot_id,
            isin=ISINType(isin),
            symbol=isin,
            description=product or isin,
        )

    def _process_buy_sell(
        self,
        row: DegiroRow,
        positions: Dict[SecurityPosition, SecurityPositionData],
        name_registry: SecurityNameRegistry,
        order_id_groups: Dict[str, List[DegiroRow]],
        consumed_rows: set,
    ) -> None:
        m = _TRADE_RE.match(row.description)
        if not m:
            logger.warning(
                "BUY_SELL row %d: cannot parse description %r",
                row.raw_row,
                row.description,
            )
            return

        action, qty_str, _name, price_str, currency = m.groups()
        qty = Decimal(qty_str)
        price = Decimal(price_str)

        if action == "Sell":
            qty = -qty

        # Determine ISIN – prefer the row's ISIN column, fall back to regex name
        isin = row.isin if _valid_isin(row.isin) else None
        if isin is None:
            logger.warning(
                "BUY_SELL row %d: no valid ISIN available", row.raw_row
            )
            return

        product = row.product or _name
        sec_pos = self._make_sec_pos(isin, product)
        name_registry.update(sec_pos, product, 8)

        # Consume all non-BUY_SELL siblings in the same order
        if row.order_id:
            for sibling in order_id_groups.get(row.order_id, []):
                if sibling.raw_row == row.raw_row:
                    continue
                if classify_row(sibling) != DegiroRowKind.BUY_SELL:
                    consumed_rows.add(sibling.raw_row)

        stock = SecurityStock(
            referenceDate=row.value_date,
            mutation=True,
            quantity=qty,
            unitPrice=price,
            balanceCurrency=currency,
            quotationType="PIECE",
            orderId=row.order_id or None,
            name="Buy" if qty > 0 else "Sell",
        )
        positions[sec_pos]["stocks"].append(stock)

    def _process_dividend(
        self,
        row: DegiroRow,
        positions: Dict[SecurityPosition, SecurityPositionData],
        name_registry: SecurityNameRegistry,
        div_tax_lookup: Dict[tuple, List[DegiroRow]],
    ) -> None:
        product = row.product
        sec_pos = self._make_sec_pos(row.isin, product)
        name_registry.update(sec_pos, product, 8)

        payment = build_security_payment(
            payment_date=row.value_date,
            description=product or row.isin,
            currency=row.change_currency,
            amount=row.change_amount,
            broker_label="Dividend",
        )

        # Look up and apply matching withholding tax
        tax_rows = div_tax_lookup.get((row.value_date, row.isin), [])
        if tax_rows:
            tax_row = tax_rows.pop(0)
            apply_withholding_tax_fields(
                payment, tax_row.change_amount, tax_row.change_currency
            )

        positions[sec_pos]["payments"].append(payment)

    def _process_delisting(
        self,
        row: DegiroRow,
        positions: Dict[SecurityPosition, SecurityPositionData],
        name_registry: SecurityNameRegistry,
    ) -> None:
        m = _DELISTING_RE.match(row.description)
        if not m:
            logger.warning(
                "DELISTING row %d: cannot parse description %r",
                row.raw_row,
                row.description,
            )
            return

        qty_str, price_str, currency = m.groups()
        qty = Decimal(qty_str)
        price = Decimal(price_str)

        product = row.product
        sec_pos = self._make_sec_pos(row.isin, product)
        name_registry.update(sec_pos, product, 8)

        stock = SecurityStock(
            referenceDate=row.value_date,
            mutation=True,
            quantity=-qty,
            unitPrice=price if price else None,
            balanceCurrency=currency,
            quotationType="PIECE",
            name="Delisting",
        )
        positions[sec_pos]["stocks"].append(stock)

    def _process_corporate_cash(
        self,
        row: DegiroRow,
        positions: Dict[SecurityPosition, SecurityPositionData],
        name_registry: SecurityNameRegistry,
    ) -> None:
        product = row.product
        sec_pos = self._make_sec_pos(row.isin, product)
        name_registry.update(sec_pos, product, 8)

        payment = build_security_payment(
            payment_date=row.value_date,
            description=product or row.isin,
            currency=row.change_currency,
            amount=row.change_amount,
            broker_label="Corporate Action Cash Settlement",
        )
        positions[sec_pos]["payments"].append(payment)
