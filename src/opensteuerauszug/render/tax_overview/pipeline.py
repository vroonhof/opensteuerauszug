"""Build TaxOverviewData from a broker statement file.

Bridges the existing import + calculate pipeline (which produces an
enriched eCH-0196 ``TaxStatement``) to the CHF-normalised
``TaxOverviewData`` that the sheet / HTML / PDF writers consume.

Scope: the translator reuses the main pipeline for broker parsing,
Kursliste enrichment, and CHF conversion. It then walks the resulting
``TaxStatement`` to populate positions, income events, orders, fees,
FX trail, waterfall, SG Verzeichnis, and DA-1 claims. Realized gains
via FIFO are intentionally left empty for now — opening-lot cost basis
is not available from a single-year flex export, and a partial FIFO
run would mislead more than it helps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ...calculate.base import CalculationMode
from ...calculate.cleanup import CleanupCalculator
from ...calculate.kursliste_tax_value_calculator import KurslisteTaxValueCalculator
from ...calculate.total import TotalCalculator
from ...config import ConfigManager
from ...config.models import GeneralSettings, IbkrAccountSettings, SchwabAccountSettings
from ...config.paths import (
    resolve_config_file,
    resolve_kursliste_dir,
    resolve_security_identifiers_file,
)
from ...core.identifier_loader import SecurityIdentifierMapLoader
from ...core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from ...core.kursliste_manager import KurslisteManager
from ...core.security import determine_security_type
from ...model.ech0196 import (
    BankAccount,
    BankAccountPayment,
    Security,
    SecurityPayment,
    SecurityStock,
    TaxStatement,
)
from .data import (
    DA1Claim,
    FeeEvent,
    FXRateUsed,
    IncomeEvent,
    PositionSummary,
    TaxOverviewData,
    VerzeichnisLine,
)
from .orders import Fill, Order, reconstruct_orders
from .performance import SectorLookup, build_performance_section
from .waterfall import Waterfall, WaterfallLine

logger = logging.getLogger(__name__)


ZERO = Decimal("0")
CHF = "CHF"

# SecurityCategory values that represent interest-bearing instruments.
_INTEREST_CATEGORIES = {"BOND", "MONEY_MARKET"}

# Commission / fee keywords that appear in SecurityPayment.name for IBKR.
_COMMISSION_KEYWORDS = ("COMMISS", "TRADING FEE", "EXCH FEE")
_FEE_KEYWORDS = ("BORROW FEE", "ACCESS FEE", "MARKET DATA", "SNAPSHOT", "EXPOSURE FEE")


@dataclass(frozen=True)
class PipelineResult:
    """The assembled overview data plus the source statement (for advanced uses)."""

    data: TaxOverviewData
    statement: TaxStatement


def build_tax_overview_data(
    input_path: Path,
    broker: str,
    tax_year: int,
    *,
    preparer_mode: bool = False,
    kursliste_dir: Optional[Path] = None,
    config_file: Optional[Path] = None,
    identifiers_csv: Optional[Path] = None,
    prior_year_input_path: Optional[Path] = None,
    canton: Optional[str] = None,
    online_sectors: bool = False,
) -> PipelineResult:
    """Run the broker pipeline and translate the result to TaxOverviewData.

    When ``prior_year_input_path`` is given, the prior year's closing values
    (Kursliste-driven taxValue per ISIN) override the current year's opening
    fallbacks. This avoids the "earliest 2024 mutation price" trap where one
    discounted Jan trade silently anchors the entire year-start valuation.
    """
    prior_year_closing: Dict[str, Decimal] = {}
    prior_year_closing_total: Optional[Decimal] = None
    if prior_year_input_path is not None:
        prior_year_closing, prior_year_closing_total = _build_prior_year_closing(
            input_path=prior_year_input_path,
            broker=broker,
            tax_year=tax_year - 1,
            kursliste_dir=kursliste_dir,
            config_file=config_file,
            identifiers_csv=identifiers_csv,
            canton=canton,
        )

    statement = _run_pipeline(
        input_path=input_path,
        broker=broker,
        tax_year=tax_year,
        kursliste_dir=kursliste_dir,
        config_file=config_file,
        identifiers_csv=identifiers_csv,
        canton=canton,
    )
    broker_fallback = (
        _extract_ibkr_flex_fallback(input_path) if broker == "ibkr" else BrokerFallback.empty()
    )
    data = _translate_statement(
        statement,
        broker=broker,
        tax_year=tax_year,
        preparer_mode=preparer_mode,
        fallback=broker_fallback,
        prior_year_closing_by_isin=prior_year_closing,
        prior_year_closing_total=prior_year_closing_total,
        online_sectors=online_sectors,
    )
    return PipelineResult(data=data, statement=statement)


def _build_prior_year_closing(
    *,
    input_path: Path,
    broker: str,
    tax_year: int,
    kursliste_dir: Optional[Path],
    config_file: Optional[Path],
    identifiers_csv: Optional[Path],
    canton: Optional[str] = None,
) -> Tuple[Dict[str, Decimal], Decimal]:
    """Run the prior-year pipeline and return (per-ISIN closing CHF, total CHF).

    Reuses the full import + cleanup + Kursliste calculator chain so the
    closing values come from the official year-end Kursliste prices — far
    more reliable than the current year's "earliest mutation" fallback.
    """
    try:
        statement = _run_pipeline(
            input_path=input_path,
            broker=broker,
            tax_year=tax_year,
            kursliste_dir=kursliste_dir,
            config_file=config_file,
            identifiers_csv=identifiers_csv,
            canton=canton,
        )
    except Exception as exc:
        logger.warning(
            "tax-overview: prior-year pipeline failed (%s); falling back to "
            "current-year opening computation",
            exc,
        )
        return {}, ZERO

    period_end = date(tax_year, 12, 31)
    fallback = (
        _extract_ibkr_flex_fallback(input_path) if broker == "ibkr" else BrokerFallback.empty()
    )
    positions = _collect_positions(statement, period_end=period_end, fallback=fallback)
    by_isin: Dict[str, Decimal] = {}
    for pos in positions:
        if pos.isin and pos.market_value_chf:
            by_isin[pos.isin] = pos.market_value_chf
    return by_isin, _sum_security_closing(positions)


@dataclass(frozen=True)
class BrokerFallback:
    """Raw-Flex fallback values the TaxStatement doesn't carry.

    Used to fill gaps the Kursliste can't cover: year-end prices for
    untracked ISINs, starting/ending cash, and cash deposits/withdrawals
    the eCH-0196 bank-payment model drops.
    """

    # ISIN → (positionValue in local currency, currency)
    open_position_value: Dict[str, Tuple[Decimal, str]]
    # ISIN → Flex subCategory asset-class label (ETF, COMMON, REIT, BOND, ...)
    # Used as a sector fallback when yfinance returns nothing.
    asset_class_by_isin: Dict[str, str]
    # currency → CHF rate at 31.12
    year_end_fx: Dict[str, Decimal]
    # CHF total of opening cash across all currencies, parsed from the Flex
    # CashReportCurrency.startingCash. Often zero in default flex queries —
    # signal "unknown" via ``bank_opening_known`` rather than guessing.
    bank_opening_cash_chf: Decimal
    bank_opening_known: bool
    # CHF total of Deposits/Withdrawals CashTransactions during the period (net, signed)
    cash_deposits_chf: Decimal
    # CHF total of deposit-side cash-flows only (always >= 0)
    cash_deposits_gross_chf: Decimal
    # CHF total of withdrawal-side cash-flows (always >= 0, stored unsigned for display)
    cash_withdrawals_chf: Decimal
    # CHF total of debit-side Broker Interest Paid (margin interest) — treated as fees
    debit_interest_chf: Decimal

    @classmethod
    def empty(cls) -> "BrokerFallback":
        return cls(
            open_position_value={},
            asset_class_by_isin={},
            year_end_fx={},
            cash_deposits_chf=ZERO,
            cash_deposits_gross_chf=ZERO,
            cash_withdrawals_chf=ZERO,
            debit_interest_chf=ZERO,
            bank_opening_cash_chf=ZERO,
            bank_opening_known=False,
        )


def _extract_ibkr_flex_fallback(flex_xml_path: Path) -> BrokerFallback:
    """Parse the raw Flex XML for values the eCH-0196 model drops."""
    try:
        from lxml import etree  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover - lxml ships with ibflex's deps
        return BrokerFallback.empty()

    if not flex_xml_path.exists():
        return BrokerFallback.empty()

    try:
        tree = etree.parse(str(flex_xml_path))
    except Exception as exc:  # pragma: no cover
        logger.warning("tax-overview: could not re-parse Flex XML for fallbacks (%s)", exc)
        return BrokerFallback.empty()

    open_positions: Dict[str, Tuple[Decimal, str]] = {}
    asset_class: Dict[str, str] = {}
    for op in tree.iter("OpenPosition"):
        isin = op.get("isin") or ""
        if not isin:
            continue
        try:
            value = Decimal(op.get("positionValue") or "0")
        except Exception:
            continue
        currency = op.get("currency") or ""
        existing = open_positions.get(isin)
        open_positions[isin] = (existing[0] + value, currency) if existing else (value, currency)
        sub = (op.get("subCategory") or "").strip().upper()
        if sub and isin not in asset_class:
            asset_class[isin] = sub

    year_end_fx: Dict[str, Decimal] = {}
    period_to_hint = _period_to_hint(tree)
    for cr in tree.iter("ConversionRate"):
        if cr.get("reportDate") != period_to_hint or cr.get("toCurrency") != "CHF":
            continue
        frm = cr.get("fromCurrency") or ""
        if not frm:
            continue
        try:
            rate = Decimal(cr.get("rate") or "0")
        except Exception:
            continue
        if rate > 0:
            year_end_fx[frm] = rate
    year_end_fx.setdefault("CHF", Decimal("1"))

    deposits = ZERO
    deposits_gross = ZERO
    withdrawals = ZERO
    debit_interest = ZERO
    for ct in tree.iter("CashTransaction"):
        ct_type = (ct.get("type") or "").strip()
        currency = ct.get("currency") or ""
        try:
            amount = Decimal(ct.get("amount") or "0")
        except Exception:
            continue
        rate = year_end_fx.get(currency, Decimal("1") if currency == "CHF" else ZERO)
        if rate == 0:
            continue
        amount_chf = (amount * rate).quantize(Decimal("0.01"))
        if ct_type == "Deposits/Withdrawals":
            deposits += amount_chf
            if amount_chf >= 0:
                deposits_gross += amount_chf
            else:
                withdrawals += -amount_chf  # store as positive
        elif ct_type == "Broker Interest Paid" and amount < 0:
            debit_interest += -amount_chf  # store as positive outflow

    bank_opening_chf = ZERO
    bank_opening_known = False
    for crc in tree.iter("CashReportCurrency"):
        currency = crc.get("currency") or ""
        if not currency or currency == "BASE_SUMMARY":
            continue
        try:
            starting = Decimal(crc.get("startingCash") or "0")
        except Exception:
            continue
        if starting == 0:
            continue
        rate = year_end_fx.get(currency, Decimal("1") if currency == "CHF" else ZERO)
        if rate == 0:
            continue
        bank_opening_chf += (starting * rate).quantize(Decimal("0.01"))
        bank_opening_known = True

    return BrokerFallback(
        open_position_value=open_positions,
        asset_class_by_isin=asset_class,
        year_end_fx=year_end_fx,
        cash_deposits_chf=deposits,
        cash_deposits_gross_chf=deposits_gross,
        cash_withdrawals_chf=withdrawals,
        debit_interest_chf=debit_interest,
        bank_opening_cash_chf=bank_opening_chf,
        bank_opening_known=bank_opening_known,
    )


def _period_to_hint(tree) -> str:  # type: ignore[no-untyped-def]
    """Return the year-end YYYYMMDD string observed in <FlexStatement toDate=.../>."""
    for fs in tree.iter("FlexStatement"):
        to_date = fs.get("toDate")
        if to_date:
            return to_date
    return ""


# ---------------------------------------------------------------------------
# Pipeline: run the existing import + calculate steps
# ---------------------------------------------------------------------------


def _run_pipeline(
    *,
    input_path: Path,
    broker: str,
    tax_year: int,
    kursliste_dir: Optional[Path],
    config_file: Optional[Path],
    identifiers_csv: Optional[Path],
    canton: Optional[str] = None,
) -> TaxStatement:
    period_from = date(tax_year, 1, 1)
    period_to = date(tax_year, 12, 31)

    # Config (general settings feed the CleanupCalculator). Config is optional —
    # we only pull canton / institution for display. Missing config is fine.
    general_settings: Optional[GeneralSettings] = None
    ibkr_accounts: List[IbkrAccountSettings] = []
    schwab_accounts: List[SchwabAccountSettings] = []
    effective_config = resolve_config_file(config_file)
    if effective_config.exists():
        try:
            cm = ConfigManager(config_file_path=str(effective_config))
            if cm.general_settings:
                general_settings = GeneralSettings(**dict(cm.general_settings))
            accounts = cm.get_all_account_settings_for_broker(broker)
            for acc in accounts or []:
                if acc.kind == "ibkr" and isinstance(acc.settings, IbkrAccountSettings):
                    ibkr_accounts.append(acc.settings)
                elif acc.kind == "schwab" and isinstance(acc.settings, SchwabAccountSettings):
                    schwab_accounts.append(acc.settings)
        except Exception as exc:  # pragma: no cover - config errors surface to CLI
            logger.warning("tax-overview: config load failed (%s) — continuing with defaults", exc)

    # Canton resolution mirrors the main CLI: an explicit --canton overrides
    # the config's general.canton; otherwise the importer-derived canton
    # (e.g. IBKR stateResidentialAddress) applies. If none is available,
    # CleanupCalculator raises with instructions — no silent default.
    if canton:
        if general_settings is None:
            general_settings = GeneralSettings(canton=canton, full_name="")
        else:
            general_settings = general_settings.model_copy(update={"canton": canton})

    # Run importer.
    if broker == "ibkr":
        # Enable tolerance for unknown XML attributes so new IBKR fields don't break parsing.
        import ibflex

        ibflex.enable_unknown_attribute_tolerance()
        from ...importers.ibkr.ibkr_importer import IbkrImporter

        importer = IbkrImporter(
            period_from=period_from,
            period_to=period_to,
            account_settings_list=ibkr_accounts,
        )
        statement = importer.import_files([str(input_path)])
    elif broker == "schwab":
        from ...importers.schwab.schwab_importer import SchwabImporter

        if not input_path.is_dir():
            raise ValueError(f"Schwab importer expects a directory, got file: {input_path}")
        importer = SchwabImporter(
            period_from=period_from,
            period_to=period_to,
            account_settings_list=schwab_accounts,
            strict_consistency=True,
        )
        statement = importer.import_dir(str(input_path))
    else:
        raise ValueError(f"unsupported broker: {broker!r}")

    # Cleanup (identifier map, period filtering).
    identifier_map = {}
    if identifiers_csv is None:
        identifiers_csv = resolve_security_identifiers_file(None)
    if identifiers_csv and Path(identifiers_csv).exists():
        try:
            identifier_map = SecurityIdentifierMapLoader(str(identifiers_csv)).load_map()
        except Exception as exc:
            logger.warning("tax-overview: identifier map load failed (%s)", exc)

    cleanup = CleanupCalculator(
        period_from=period_from,
        period_to=period_to,
        identifier_map=identifier_map,
        enable_filtering=True,
        importer_name=broker,
        config_settings=general_settings,
    )
    statement = cleanup.calculate(statement)

    # Kursliste-driven tax value + FX. Requires Kursliste data for the year.
    effective_kursliste = resolve_kursliste_dir(kursliste_dir)
    if effective_kursliste.exists():
        try:
            km = KurslisteManager()
            km.load_directory(effective_kursliste)
            km.ensure_year_available(tax_year, effective_kursliste)
            rate_provider = KurslisteExchangeRateProvider(km)
            kursliste_calc = KurslisteTaxValueCalculator(
                mode=CalculationMode.OVERWRITE,
                exchange_rate_provider=rate_provider,
            )
            statement = kursliste_calc.calculate(statement)
        except Exception as exc:
            logger.warning(
                "tax-overview: Kursliste enrichment skipped (%s). "
                "Positions may show broker balances instead of Steuerwert.",
                exc,
            )
    else:
        logger.warning(
            "tax-overview: Kursliste directory %s missing — positions will fall "
            "back to broker balances (no official Steuerwert applied).",
            effective_kursliste,
        )

    total = TotalCalculator(mode=CalculationMode.OVERWRITE)
    statement = total.calculate(statement)
    return statement


# ---------------------------------------------------------------------------
# Translation: TaxStatement -> TaxOverviewData
# ---------------------------------------------------------------------------


def _translate_statement(
    statement: TaxStatement,
    *,
    broker: str,
    tax_year: int,
    preparer_mode: bool,
    fallback: Optional[BrokerFallback] = None,
    prior_year_closing_by_isin: Optional[Dict[str, Decimal]] = None,
    prior_year_closing_total: Optional[Decimal] = None,
    online_sectors: bool = False,
) -> TaxOverviewData:
    period_end = date(tax_year, 12, 31)
    fallback = fallback or BrokerFallback.empty()

    positions = _collect_positions(statement, period_end=period_end, fallback=fallback)
    dividends, interest, sec_fees, da1_claims = _collect_security_events(statement)
    bank_interest, bank_fees = _collect_bank_events(statement, period_end=period_end)
    fees = sec_fees + bank_fees
    interest_events = interest + bank_interest
    orders = _collect_orders(statement)
    fx_rates = _collect_fx_rates(statement)

    # Bank cash opening: prefer the Flex-reported startingCash. The previous
    # ``closing_cash − tracked_payments`` heuristic silently inflated opening
    # cash to ≈ closing cash because tracked payments only cover dividends /
    # interest / fees, not deposits, withdrawals, or trade settlements.
    bank_opening_chf = fallback.bank_opening_cash_chf if fallback.bank_opening_known else ZERO
    if prior_year_closing_total is not None and prior_year_closing_total > 0:
        # Authoritative: 2023 Schluss = 2024 Eröffnung. Pulled from the
        # prior-year pipeline run with its Kursliste — guaranteed to use
        # the official year-end prices instead of the "earliest mutation"
        # fallback which can be far off when the first 2024 trade was
        # discounted (e.g. fractional sale, stop-loss, options).
        opening_securities_chf = prior_year_closing_total
    else:
        opening_securities_chf = _sum_security_opening(
            statement,
            period_start=date(tax_year, 1, 1),
            fx_fallback=fallback.year_end_fx,
        )
    closing_securities_chf = _sum_security_closing(positions)
    bank_closing_chf = _sum_bank_closing(statement, period_end=period_end)
    # Übersicht waterfall keeps the total-wealth view; Performance uses
    # securities-only so the return doesn't depend on unknown opening cash.
    opening_chf = opening_securities_chf + bank_opening_chf
    closing_chf = closing_securities_chf + bank_closing_chf

    verzeichnis = _build_verzeichnis(positions, dividends, interest_events, da1_claims)

    # Margin (debit) interest can arrive twice: as "DEBIT INT" FeeEvents from
    # the imported bank payments AND via the Flex fallback's debit_interest_chf
    # (which sums the same BROKERINTPAID cash transactions). When the fallback
    # saw them, keep it as the single source for the totals and drop the
    # FeeEvent duplicates; the Gebühren sheet still lists every line item.
    if fallback.debit_interest_chf > 0:
        total_fee_events = [f for f in fees if f.kind != "interest_debit"]
    else:
        total_fee_events = fees

    waterfall = _build_waterfall(
        opening_chf=opening_chf,
        closing_chf=closing_chf,
        dividends=dividends,
        interest=interest_events,
        fees=total_fee_events,
        deposits_chf=fallback.cash_deposits_chf,
        debit_interest_chf=fallback.debit_interest_chf,
    )

    dividends_chf = sum((d.gross_chf for d in dividends), ZERO)
    interest_chf = sum((i.gross_chf for i in interest_events), ZERO)
    fees_chf = sum((f.amount_chf for f in total_fee_events), ZERO) + fallback.debit_interest_chf

    # Online sector lookup (yfinance) is strictly opt-in: a tax tool must not
    # make network calls unless the user asked for them. Offline, sectors
    # resolve from the local cache or fall back to "Unbekannt".
    sector_lookup = SectorLookup(
        cache_path=Path("data/cache/sector_lookup.json"),
        online=online_sectors,
    )
    opening_by_isin = _opening_chf_by_isin(
        statement,
        period_start=date(tax_year, 1, 1),
        fx_fallback=fallback.year_end_fx,
    )
    # Prior-year overrides win per-ISIN; the current-year fallback only fills
    # ISINs the prior year doesn't carry (e.g. mid-year additions to scope).
    if prior_year_closing_by_isin:
        for isin, value in prior_year_closing_by_isin.items():
            opening_by_isin[isin] = value
    performance = build_performance_section(
        statement,
        tax_year=tax_year,
        opening_securities_chf=opening_securities_chf,
        closing_securities_chf=closing_securities_chf,
        closing_cash_chf=bank_closing_chf,
        cash_known=fallback.bank_opening_known,
        net_deposits_chf=fallback.cash_deposits_chf,
        deposits_gross_chf=fallback.cash_deposits_gross_chf,
        withdrawals_chf=fallback.cash_withdrawals_chf,
        dividends_chf=dividends_chf,
        interest_chf=interest_chf,
        fees_chf=fees_chf,
        positions=positions,
        opening_by_isin=opening_by_isin,
        sector_lookup=sector_lookup,
        asset_class_by_isin=fallback.asset_class_by_isin,
    )

    return TaxOverviewData(
        tax_year=tax_year,
        broker=broker,
        preparer_mode=preparer_mode,
        opening_value_chf=opening_chf,
        closing_value_chf=closing_chf,
        waterfall=waterfall,
        positions=positions,
        orders=orders,
        lot_closes=[],  # FIFO requires opening-lot basis we don't have here
        dividends=dividends,
        interest=interest_events,
        fees=fees,
        fx_rates=fx_rates,
        verzeichnis_lines=verzeichnis,
        da1_claims=da1_claims,
        ks36_criteria=[],
        ks36_evidence=[],
        performance=performance,
    )


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


def _collect_positions(
    statement: TaxStatement,
    *,
    period_end: date,
    fallback: BrokerFallback,
) -> List[PositionSummary]:
    positions: List[PositionSummary] = []
    los = statement.listOfSecurities
    if not los:
        return positions

    for depot in los.depot:
        for security in depot.security:
            pos = _position_for(security, period_end=period_end, fallback=fallback)
            if pos is not None:
                positions.append(pos)

    positions.sort(key=lambda p: (p.isin or "", p.symbol))
    return positions


def _position_for(
    security: Security,
    *,
    period_end: date,
    fallback: BrokerFallback,
) -> Optional[PositionSummary]:
    tv = security.taxValue
    closing_stock = _find_closing_stock(security.stock, period_end=period_end)

    # Prefer the security.taxValue Kursliste figures; fall back to the closing
    # stock entry when the calculator left taxValue empty (e.g. no Kursliste).
    quantity = (
        _first_non_none(
            tv.quantity if tv else None,
            closing_stock.quantity if closing_stock else None,
        )
        or ZERO
    )
    if quantity == 0:
        return None

    price_local = (
        _first_non_none(
            tv.unitPrice if tv else None,
            closing_stock.unitPrice if closing_stock else None,
        )
        or ZERO
    )

    market_value_chf: Decimal = (
        _first_non_none(
            tv.value if tv else None,
            closing_stock.value if closing_stock else None,
        )
        or ZERO
    )

    # Kursliste gap: fall back to the broker's year-end positionValue.
    if market_value_chf == 0 and security.isin and security.isin in fallback.open_position_value:
        local_value, currency = fallback.open_position_value[security.isin]
        currency_key = currency or security.currency or ""
        rate = fallback.year_end_fx.get(currency_key)
        if rate is None and currency_key in ("", "CHF"):
            rate = Decimal("1")
        if rate is None:
            # No year-end FX for a foreign currency: refusing to pretend the
            # local value is CHF matches _security_opening_chf's behaviour.
            logger.warning(
                "tax-overview: no year-end FX rate for %s — cannot value %s from broker positionValue",
                currency_key,
                security.isin,
            )
        else:
            market_value_chf = (local_value * rate).quantize(Decimal("0.01"))
            if price_local == 0 and quantity:
                price_local = (local_value / quantity).quantize(Decimal("0.0001"))

    # Per-share CHF: balance / quantity if available, else price_local * rate.
    if market_value_chf and quantity:
        price_chf = market_value_chf / quantity
    else:
        rate = _first_non_none(
            tv.exchangeRate if tv else None,
            closing_stock.exchangeRate if closing_stock else None,
        ) or Decimal("1")
        price_chf = price_local * rate

    return PositionSummary(
        isin=security.isin,
        symbol=(security.symbol or _symbol_from_name(security.securityName)),
        description=security.securityName,
        quantity_closing=quantity,
        currency=security.currency,
        price_closing_local=price_local,
        price_closing_chf=price_chf,
        market_value_chf=market_value_chf,
        security_type=determine_security_type(security),
    )


def _find_closing_stock(
    stocks: Sequence[SecurityStock], *, period_end: date
) -> Optional[SecurityStock]:
    """Return the year-end closing balance stock entry, if one exists.

    The importer writes a ``mutation=False`` entry for the closing balance.
    Its referenceDate is the day AFTER the period end (start-of-next-day
    convention), so we pick the latest non-mutation entry at or just past
    period_end.
    """
    # Only balances at or past period_end qualify: without this, a security
    # sold mid-year (whose closing balance the cleanup step moved into
    # taxValue) would fall back to its opening balance and resurface as a
    # phantom year-end position.
    candidates = [s for s in stocks if not s.mutation and s.referenceDate >= period_end]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.referenceDate)


def _find_opening_stock(
    stocks: Sequence[SecurityStock], *, period_start: date
) -> Optional[SecurityStock]:
    """Return the opening balance stock entry (mutation=False at period start).

    The IBKR importer writes a ``mutation=False`` entry with
    ``referenceDate == period_start`` for securities that had a non-zero
    position at the start of the tax year. Closing balances live at
    ``period_start + 365 days`` (i.e. start-of-next-day after period_to), so
    strict date matching is required — otherwise we'd return the closing
    entry as the opening.
    """
    for s in stocks:
        if not s.mutation and s.referenceDate == period_start:
            return s
    return None


def _earliest_mutation_price(stocks: Sequence[SecurityStock]) -> Optional[Decimal]:
    """First observed non-None unitPrice across mutation entries."""
    priced = [s for s in stocks if s.mutation and s.unitPrice is not None]
    if not priced:
        return None
    return min(priced, key=lambda s: s.referenceDate).unitPrice


def _earliest_mutation_rate(stocks: Sequence[SecurityStock]) -> Optional[Decimal]:
    priced = [s for s in stocks if s.mutation and s.exchangeRate is not None]
    if not priced:
        return None
    return min(priced, key=lambda s: s.referenceDate).exchangeRate


# ---------------------------------------------------------------------------
# Security events: dividends, interest, commissions, DA-1 claims
# ---------------------------------------------------------------------------


def _collect_security_events(
    statement: TaxStatement,
) -> Tuple[List[IncomeEvent], List[IncomeEvent], List[FeeEvent], List[DA1Claim]]:
    dividends: List[IncomeEvent] = []
    interest: List[IncomeEvent] = []
    fees: List[FeeEvent] = []
    da1: List[DA1Claim] = []

    los = statement.listOfSecurities
    if not los:
        return dividends, interest, fees, da1

    for depot in los.depot:
        for security in depot.security:
            symbol = security.symbol or _symbol_from_name(security.securityName)
            for payment in security.payment:
                kind = _classify_security_payment(payment, security)
                if kind == "fee":
                    fees.append(_fee_from_security_payment(payment, security))
                    continue
                event = _income_from_security_payment(payment, security, symbol=symbol)
                if event is None:
                    continue
                if _is_interest_security(security):
                    interest.append(event)
                else:
                    dividends.append(event)
                claim = _da1_from_security_payment(payment, security, event)
                if claim is not None:
                    da1.append(claim)

    dividends.sort(key=lambda e: (e.payment_date, e.symbol))
    interest.sort(key=lambda e: (e.payment_date, e.symbol))
    fees.sort(key=lambda f: (f.fee_date, f.kind))
    da1.sort(key=lambda c: (c.source_country, c.symbol))
    return dividends, interest, fees, da1


def _classify_security_payment(payment: SecurityPayment, security: Security) -> str:
    """Return 'fee' for commissions/fees, 'income' for dividends/interest."""
    name = (payment.name or "").upper()
    if any(kw in name for kw in _COMMISSION_KEYWORDS):
        return "fee"
    if any(kw in name for kw in _FEE_KEYWORDS):
        return "fee"
    return "income"


def _income_from_security_payment(
    payment: SecurityPayment, security: Security, *, symbol: str
) -> Optional[IncomeEvent]:
    # Gross in CHF is the sum of Kursliste-attributed gross revenue buckets.
    gross_chf = _sum_optional(
        payment.grossRevenueA,
        payment.grossRevenueACanton,
        payment.grossRevenueB,
        payment.grossRevenueBCanton,
    )
    wht_chf = _sum_optional(
        payment.withHoldingTaxClaim,
        payment.nonRecoverableTax,
        payment.additionalWithHoldingTaxUSA,
    )

    gross_local = payment.amount or ZERO
    rate = payment.exchangeRate or Decimal("1")
    # Some payments have amount in local + no CHF breakdown (e.g. when Kursliste
    # missed the ISIN). Fall back to amount * rate for a display-only figure.
    if gross_chf == 0 and gross_local != 0:
        gross_chf = (gross_local * rate).quantize(Decimal("0.01"))

    if gross_chf == 0 and gross_local == 0:
        return None

    wht_local = (wht_chf / rate) if rate and rate != 0 else ZERO
    net_local = gross_local - wht_local
    net_chf = gross_chf - wht_chf

    category = "interest" if _is_interest_security(security) else "dividend"
    return IncomeEvent(
        payment_date=payment.paymentDate,
        isin=security.isin,
        symbol=symbol,
        description=security.securityName,
        category=category,
        gross_local=gross_local,
        currency=payment.amountCurrency,
        withholding_tax_local=wht_local,
        net_local=net_local,
        gross_chf=gross_chf,
        withholding_tax_chf=wht_chf,
        net_chf=net_chf,
    )


def _fee_from_security_payment(payment: SecurityPayment, security: Security) -> FeeEvent:
    amount_local = payment.amount or ZERO
    # Brokers book commissions as negative numbers; show absolute value in the sheet.
    amount_local = abs(amount_local)
    rate = payment.exchangeRate or Decimal("1")
    amount_chf = (amount_local * rate).quantize(Decimal("0.01"))
    name_upper = (payment.name or "").upper()
    kind = "commission" if any(kw in name_upper for kw in _COMMISSION_KEYWORDS) else "other"
    return FeeEvent(
        fee_date=payment.paymentDate,
        kind=kind,
        description=payment.name or security.securityName,
        amount_local=amount_local,
        currency=payment.amountCurrency,
        amount_chf=amount_chf,
    )


def _da1_from_security_payment(
    payment: SecurityPayment, security: Security, event: IncomeEvent
) -> Optional[DA1Claim]:
    # Only foreign securities with a non-zero non-recoverable / additional US WHT
    # qualify for a DA-1 row. The Kursliste calculator writes the CHF figure
    # into nonRecoverableTaxAmount (not nonRecoverableTax), so consider both —
    # mirroring core.security._has_da1_payments — preferring the explicit
    # nonRecoverableTax when set to avoid ever counting the same tax twice.
    recoverable = _sum_optional(
        payment.nonRecoverableTax or payment.nonRecoverableTaxAmount,
        payment.additionalWithHoldingTaxUSA,
    )
    if recoverable == 0:
        return None
    country = (security.country or "").upper() or "??"
    if country == "CH":
        return None

    gross_chf = event.gross_chf
    wht_chf = recoverable
    withholding_rate = wht_chf / gross_chf if gross_chf else ZERO
    return DA1Claim(
        isin=security.isin,
        symbol=event.symbol,
        description=security.securityName,
        source_country=country,
        gross_chf=gross_chf,
        withholding_tax_chf=wht_chf,
        withholding_rate=withholding_rate,
        treaty_rate_ceiling=None,  # not resolved — left blank
        recoverable_chf=wht_chf,
    )


def _is_interest_security(security: Security) -> bool:
    return security.securityCategory in _INTEREST_CATEGORIES


# ---------------------------------------------------------------------------
# Bank account events: cash interest / fees
# ---------------------------------------------------------------------------


def _collect_bank_events(
    statement: TaxStatement, *, period_end: date
) -> Tuple[List[IncomeEvent], List[FeeEvent]]:
    interest: List[IncomeEvent] = []
    fees: List[FeeEvent] = []
    loba = statement.listOfBankAccounts
    if not loba:
        return interest, fees

    for ba in loba.bankAccount:
        for payment in ba.payment:
            amount = payment.amount or ZERO
            gross_chf = _sum_optional(payment.grossRevenueA, payment.grossRevenueB)
            if gross_chf == 0 and amount:
                rate = payment.exchangeRate or Decimal("1")
                gross_chf = (amount * rate).quantize(Decimal("0.01"))

            name_upper = (payment.name or "").upper()
            is_fee = (
                (amount < 0)
                or ("DEBIT INT" in name_upper)
                or any(kw in name_upper for kw in _FEE_KEYWORDS)
            )
            if is_fee or payment.bankingExpenses:
                fees.append(
                    FeeEvent(
                        fee_date=payment.paymentDate,
                        kind="interest_debit" if "DEBIT" in name_upper else "other",
                        description=payment.name or f"{ba.bankAccountName} fee",
                        amount_local=abs(amount),
                        currency=payment.amountCurrency,
                        amount_chf=abs(gross_chf),
                    )
                )
                continue

            # Credit interest on a cash account → interest income.
            if amount > 0:
                rate = payment.exchangeRate or Decimal("1")
                wht_chf = _sum_optional(
                    payment.withHoldingTaxClaim,
                    payment.nonRecoverableTax,
                )
                wht_local = (wht_chf / rate) if rate and rate != 0 else ZERO
                interest.append(
                    IncomeEvent(
                        payment_date=payment.paymentDate,
                        isin=None,
                        symbol=ba.bankAccountCurrency or "",
                        description=payment.name or f"{ba.bankAccountName} interest",
                        category="interest",
                        gross_local=amount,
                        currency=payment.amountCurrency,
                        withholding_tax_local=wht_local,
                        net_local=amount - wht_local,
                        gross_chf=gross_chf,
                        withholding_tax_chf=wht_chf,
                        net_chf=gross_chf - wht_chf,
                    )
                )

    interest.sort(key=lambda e: (e.payment_date, e.symbol))
    fees.sort(key=lambda f: (f.fee_date, f.kind))
    return interest, fees


# ---------------------------------------------------------------------------
# Orders: reconstruct from SecurityStock mutation entries
# ---------------------------------------------------------------------------


def _collect_orders(statement: TaxStatement) -> List[Order]:
    fills: List[Fill] = []
    los = statement.listOfSecurities
    if not los:
        return []

    for depot in los.depot:
        for security in depot.security:
            symbol = security.symbol or _symbol_from_name(security.securityName)
            for idx, stock in enumerate(security.stock):
                if not stock.mutation:
                    continue
                qty = stock.quantity or ZERO
                if qty == 0:
                    continue
                side = "BUY" if qty > 0 else "SELL"
                price = stock.unitPrice or ZERO
                money = abs(qty) * price
                fill_id = (
                    stock.orderId
                    or f"{security.positionId}:{idx}:{stock.referenceDate.isoformat()}"
                )
                fills.append(
                    Fill(
                        fill_id=fill_id,
                        symbol=symbol,
                        side=side,
                        quantity=abs(qty),
                        price=price,
                        money=money if side == "BUY" else -money,
                        commission=ZERO,  # commissions live separately in SecurityPayment
                        currency=security.currency,
                        trade_time=datetime.combine(stock.referenceDate, time.min),
                        asset_category=security.securityCategory or "",
                        isin=security.isin,
                        conid=None,
                        ib_order_id=stock.orderId,
                        order_reference=None,
                    )
                )

    return reconstruct_orders(fills)


# ---------------------------------------------------------------------------
# FX rates: unique (currency, date, rate) tuples observed during the run
# ---------------------------------------------------------------------------


def _collect_fx_rates(statement: TaxStatement) -> List[FXRateUsed]:
    seen: Dict[Tuple[str, date], Decimal] = {}

    def _add(currency: Optional[str], ref_date: Optional[date], rate: Optional[Decimal]) -> None:
        if not currency or currency == CHF or not ref_date or not rate:
            return
        seen.setdefault((currency, ref_date), rate)

    los = statement.listOfSecurities
    if los:
        for depot in los.depot:
            for security in depot.security:
                if security.taxValue:
                    _add(
                        security.currency,
                        security.taxValue.referenceDate,
                        security.taxValue.exchangeRate,
                    )
                for stock in security.stock:
                    _add(security.currency, stock.referenceDate, stock.exchangeRate)
                for payment in security.payment:
                    _add(payment.amountCurrency, payment.paymentDate, payment.exchangeRate)

    loba = statement.listOfBankAccounts
    if loba:
        for ba in loba.bankAccount:
            if ba.taxValue:
                _add(
                    ba.taxValue.balanceCurrency, ba.taxValue.referenceDate, ba.taxValue.exchangeRate
                )
            for payment in ba.payment:
                _add(payment.amountCurrency, payment.paymentDate, payment.exchangeRate)

    return sorted(
        (
            FXRateUsed(currency=ccy, reference_date=d, rate=rate, source="kursliste")
            for (ccy, d), rate in seen.items()
        ),
        key=lambda r: (r.reference_date, r.currency),
    )


# ---------------------------------------------------------------------------
# Aggregates for the waterfall
# ---------------------------------------------------------------------------


def _security_opening_chf(
    security: Security,
    *,
    period_start: date,
    fx_fallback: Optional[Dict[str, Decimal]] = None,
) -> Decimal:
    """Return the opening-day CHF value for one security (same rules as the
    aggregate).

    Returns :data:`ZERO` when no opening balance exists. Split from the
    aggregate helper so per-ISIN callers (performance tab) get the same
    3-tier fallback without re-implementing it.

    ``fx_fallback`` (currency → CHF rate, typically year-end) is consulted as
    a last resort when the SecurityStock entries don't carry an exchangeRate.
    Without it, the Tier-3 path silently treats the local-currency price as
    CHF, which inflates non-CHF positions by 1/fx (e.g. ~10x for HKD lines).
    """
    opening = _find_opening_stock(security.stock, period_start=period_start)
    if opening is None:
        return ZERO
    if opening.value is not None:
        return opening.value
    if opening.balance is not None and opening.exchangeRate is not None:
        return opening.balance * opening.exchangeRate
    quantity = opening.quantity or ZERO
    if not quantity:
        return ZERO
    price = _earliest_mutation_price(security.stock)
    if price is None and security.taxValue:
        price = security.taxValue.unitPrice
    if price is None:
        return ZERO
    rate = _earliest_mutation_rate(security.stock)
    if rate is None and security.taxValue:
        rate = security.taxValue.exchangeRate
    if rate is None:
        currency = (security.currency or "").upper()
        if currency == "CHF":
            rate = Decimal("1")
        elif fx_fallback and currency in fx_fallback and fx_fallback[currency] > 0:
            rate = fx_fallback[currency]
        else:
            # Unknown currency / FX → don't pretend the value is CHF.
            return ZERO
    return (quantity * price * rate).quantize(Decimal("0.01"))


def _opening_chf_by_isin(
    statement: TaxStatement,
    *,
    period_start: date,
    fx_fallback: Optional[Dict[str, Decimal]] = None,
) -> Dict[str, Decimal]:
    """Per-ISIN opening CHF values, for the performance tab.

    Uses the same 3-tier fallback as the portfolio-wide opening sum so
    per-position P&L reconciles with the summary Dietz numerator.
    """
    out: Dict[str, Decimal] = {}
    los = statement.listOfSecurities
    if not los:
        return out
    for depot in los.depot:
        for security in depot.security:
            if not security.isin:
                continue
            out[security.isin] = _security_opening_chf(
                security,
                period_start=period_start,
                fx_fallback=fx_fallback,
            )
    return out


def _sum_security_opening(
    statement: TaxStatement,
    *,
    period_start: date,
    fx_fallback: Optional[Dict[str, Decimal]] = None,
) -> Decimal:
    """Sum opening-day portfolio value in CHF (see :func:`_security_opening_chf`)."""
    total = ZERO
    los = statement.listOfSecurities
    if not los:
        return total
    for depot in los.depot:
        for security in depot.security:
            total += _security_opening_chf(
                security,
                period_start=period_start,
                fx_fallback=fx_fallback,
            )
    return total


def _sum_security_closing(positions: Iterable[PositionSummary]) -> Decimal:
    return sum((p.market_value_chf for p in positions), ZERO)


def _bank_closing_chf(ba: BankAccount) -> Decimal:
    if ba.taxValue and ba.taxValue.value is not None:
        return ba.taxValue.value
    if ba.taxValue and ba.taxValue.balance is not None and ba.taxValue.exchangeRate is not None:
        return ba.taxValue.balance * ba.taxValue.exchangeRate
    return ZERO


def _sum_bank_closing(statement: TaxStatement, *, period_end: date) -> Decimal:
    total = ZERO
    loba = statement.listOfBankAccounts
    if not loba:
        return total
    for ba in loba.bankAccount:
        total += _bank_closing_chf(ba)
    return total


# ---------------------------------------------------------------------------
# SG Verzeichnis lines (consolidate per ISIN)
# ---------------------------------------------------------------------------


def _build_verzeichnis(
    positions: Sequence[PositionSummary],
    dividends: Sequence[IncomeEvent],
    interest: Sequence[IncomeEvent],
    da1: Sequence[DA1Claim],
) -> List[VerzeichnisLine]:
    income_by_isin: Dict[str, Decimal] = {}
    vstk_by_isin: Dict[str, Decimal] = {}  # Verrechnungssteuer (CH WHT claim)
    foreign_by_isin: Dict[str, Decimal] = {}

    for event in list(dividends) + list(interest):
        key = event.isin or event.symbol
        income_by_isin[key] = income_by_isin.get(key, ZERO) + event.gross_chf

    for claim in da1:
        key = claim.isin or claim.symbol
        foreign_by_isin[key] = foreign_by_isin.get(key, ZERO) + claim.withholding_tax_chf

    # Swiss WHT only arises when no DA-1 foreign WHT was emitted for that payment;
    # approximate: sum (withholding_tax_chf - foreign_by_isin).
    # Precise bookkeeping lives upstream — this is an overview helper.
    for event in dividends:
        key = event.isin or event.symbol
        foreign = foreign_by_isin.get(key, ZERO)
        ch_portion = max(event.withholding_tax_chf - foreign, ZERO)
        if ch_portion > 0:
            vstk_by_isin[key] = vstk_by_isin.get(key, ZERO) + ch_portion

    lines: List[VerzeichnisLine] = []
    for position in positions:
        key = position.isin or position.symbol
        # Form 2 column A = "Werte mit Verrechnungssteuerabzug". Use the same
        # canonical classification as the official eCH-0196 rendering
        # (core.security.determine_security_type) so the mapping sheet never
        # contradicts the statement it mirrors. The Verrechnungssteuer
        # presence check stays as a backstop for edge cases.
        form_field = "A" if (position.security_type == "A" or vstk_by_isin.get(key)) else "B"
        lines.append(
            VerzeichnisLine(
                form_field=form_field,
                investment_type=_verzeichnis_type(position),
                isin=position.isin,
                description=position.description,
                quantity=position.quantity_closing,
                market_value_chf=position.market_value_chf,
                income_gross_chf=income_by_isin.get(key, ZERO),
                verrechnungssteuer_chf=vstk_by_isin.get(key, ZERO),
                auslaendische_quellensteuer_chf=foreign_by_isin.get(key, ZERO),
            )
        )
    return lines


def _verzeichnis_type(position: PositionSummary) -> str:
    # Without the SecurityCategory on PositionSummary we use a simple heuristic
    # on description. Callers who want precise typing should populate it upstream.
    desc = (position.description or "").upper()
    if "BOND" in desc or "%" in desc:
        return "Obligation"
    if "FUND" in desc or "ETF" in desc or "UCITS" in desc:
        return "Fonds"
    return "Aktie"


# ---------------------------------------------------------------------------
# Waterfall
# ---------------------------------------------------------------------------


def _build_waterfall(
    *,
    opening_chf: Decimal,
    closing_chf: Decimal,
    dividends: Sequence[IncomeEvent],
    interest: Sequence[IncomeEvent],
    fees: Sequence[FeeEvent],
    deposits_chf: Decimal = ZERO,
    debit_interest_chf: Decimal = ZERO,
) -> Waterfall:
    total_dividends = sum((d.gross_chf for d in dividends), ZERO)
    total_interest = sum((i.gross_chf for i in interest), ZERO)
    total_wht = sum((e.withholding_tax_chf for e in (*dividends, *interest)), ZERO)
    total_fees = sum((f.amount_chf for f in fees), ZERO)

    inflows: List[WaterfallLine] = []
    # Deposits/Withdrawals nets to a signed number; positive = net deposit.
    if deposits_chf > 0:
        inflows.append(WaterfallLine("Einzahlungen", deposits_chf, "inflow"))
    if total_dividends:
        inflows.append(WaterfallLine("Dividenden brutto", total_dividends, "inflow"))
    if total_interest:
        inflows.append(WaterfallLine("Zinsen brutto", total_interest, "inflow"))

    outflows: List[WaterfallLine] = []
    if deposits_chf < 0:
        outflows.append(WaterfallLine("Auszahlungen", -deposits_chf, "outflow"))
    if total_wht:
        outflows.append(WaterfallLine("Quellensteuer", total_wht, "outflow"))
    if debit_interest_chf:
        outflows.append(WaterfallLine("Sollzinsen (Margin)", debit_interest_chf, "outflow"))
    if total_fees:
        outflows.append(WaterfallLine("Gebühren", total_fees, "outflow"))

    return Waterfall(
        opening=opening_chf,
        inflows=inflows,
        outflows=outflows,
        closing=closing_chf,
    )


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def _first_non_none(*values):
    for v in values:
        if v is not None:
            return v
    return None


def _sum_optional(*values: Optional[Decimal]) -> Decimal:
    total = ZERO
    for v in values:
        if v is not None:
            total += v
    return total


def _symbol_from_name(name: str) -> str:
    # IBKR security names often look like "NAME (SYM)"; pull the parenthesized tail.
    if not name:
        return ""
    if "(" in name and name.rstrip().endswith(")"):
        return name.rsplit("(", 1)[1].rstrip(")").strip()
    return name.split()[0] if name else ""
