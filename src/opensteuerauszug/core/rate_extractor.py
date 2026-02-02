import datetime
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Set, Tuple, Iterator, Optional
import logging

logger = logging.getLogger(__name__)

class ImpliedRateManager:
    def __init__(self):
        # currency -> date -> rate
        self.implied_rates: Dict[str, Dict[datetime.date, str]] = defaultdict(dict)
        # currency -> set of dates
        self.official_rates: Dict[str, Set[datetime.date]] = defaultdict(set)

    def add_payment(self, date_str: str, currency: str, rate_str: str) -> None:
        """
        Add a rate derived from a payment.

        Args:
            date_str: Date string in YYYY-MM-DD format
            currency: Currency code (e.g. USD)
            rate_str: Exchange rate as string
        """
        if not date_str or not currency or not rate_str:
            return

        try:
            date_obj = datetime.date.fromisoformat(date_str)
        except ValueError:
            logger.warning(f"Invalid date format: {date_str}")
            return

        if currency == "CHF":
            # CHF to CHF rate is always 1, not useful to track
            return

        existing_rate_str = self.implied_rates[currency].get(date_obj)

        if existing_rate_str is not None:
            if existing_rate_str != rate_str:
                if self._are_rates_compatible(existing_rate_str, rate_str):
                     # If compatible, prefer the one with higher precision (more length usually implies more precision for decimals)
                     # or explicit decimal check.
                     if len(rate_str) > len(existing_rate_str):
                         self.implied_rates[currency][date_obj] = rate_str
                         # logger.debug(f"Upgraded precision for {currency} on {date_str} from {existing_rate_str} to {rate_str}")
                else:
                    logger.warning(
                        f"Conflicting implied rates for {currency} on {date_str}: "
                        f"keeping {existing_rate_str}, ignoring {rate_str}"
                    )
        else:
            self.implied_rates[currency][date_obj] = rate_str

    def _are_rates_compatible(self, rate1_str: str, rate2_str: str) -> bool:
        """
        Check if two rate strings are compatible (i.e., one is a rounded version of the other).
        """
        try:
            d1 = Decimal(rate1_str)
            d2 = Decimal(rate2_str)
        except Exception:
            return False

        # Determine precision by looking at the exponent
        # Decimal('0.85').as_tuple().exponent is -2
        exp1 = d1.as_tuple().exponent
        exp2 = d2.as_tuple().exponent

        # If exponents are equal and values different, they are incompatible
        if exp1 == exp2:
            return d1 == d2

        # Identify which one is more precise (smaller exponent = more negative)
        if exp1 < exp2:
            high_prec, low_prec = d1, d2
            low_prec_exp = exp2
        else:
            high_prec, low_prec = d2, d1
            low_prec_exp = exp1

        # Round the high precision value to the low precision's scale
        # quantized = high_prec.quantize(Decimal(10) ** low_prec_exp, rounding=ROUND_HALF_UP)
        # However, exp is negative, so 10**-2 is 0.01.
        # Decimal.quantize takes another Decimal as the exponent/pattern.

        quantized = high_prec.quantize(Decimal(f"1e{low_prec_exp}"), rounding=ROUND_HALF_UP)

        return quantized == low_prec

    def add_official_rate(self, date_str: str, currency: str) -> None:
        """
        Mark a date as covered by an official explicit rate.

        Args:
            date_str: Date string in YYYY-MM-DD format
            currency: Currency code
        """
        if not date_str or not currency:
            return

        try:
            date_obj = datetime.date.fromisoformat(date_str)
            self.official_rates[currency].add(date_obj)
        except ValueError:
            logger.warning(f"Invalid date format for official rate: {date_str}")

    def get_missing_days(self, year: int) -> Dict[str, List[datetime.date]]:
        """
        Identify trading days (Mon-Fri) that have no rate (neither official nor implied).

        Args:
            year: The tax year to check.

        Returns:
            Dict mapping currency to list of missing dates.
        """
        missing_days = defaultdict(list)

        # Consider all currencies we have encountered either in implied or official rates
        all_currencies = set(self.implied_rates.keys()) | set(self.official_rates.keys())

        start_date = datetime.date(year, 1, 1)
        end_date = datetime.date(year, 12, 31)

        # Iterate through every day of the year
        current_date = start_date
        while current_date <= end_date:
            # Check if weekday (Mon=0, Sun=6). We want Mon-Fri (0-4).
            if current_date.weekday() < 5:
                for currency in all_currencies:
                    has_official = current_date in self.official_rates[currency]
                    has_implied = current_date in self.implied_rates[currency]

                    if not has_official and not has_implied:
                        missing_days[currency].append(current_date)

            current_date += datetime.timedelta(days=1)

        return dict(missing_days)

    def generate_db_rows(self, year: int, source_file: str) -> Iterator[Tuple]:
        """
        Yield tuples for insertion into exchange_rates_daily.
        Filters out rates that are already covered by official rates.

        Args:
            year: The tax year (used for validation/filtering if needed, though rates carry their own dates)
            source_file: Name of the source file.

        Yields:
            Tuple: (currency_code, date, rate, denomination, tax_year, source_file)
        """
        source_marker = f"{source_file} (IMPLIED)"
        denomination = 1 # Implied rates are usually per 1 unit, or at least the rate field implies the multiplier is handled.
                         # Kursliste usually has denomination for explicit rates.
                         # For payments: paymentValueCHF = paymentValue * exchangeRate.
                         # So exchangeRate is per unit of currency.

        for currency, dates_map in self.implied_rates.items():
            for date_obj, rate_str in dates_map.items():
                # Skip if we have an official rate for this day
                if date_obj in self.official_rates[currency]:
                    continue

                # We assume the rate is for the tax year of the file roughly,
                # but payments can happen anytime. We store them as is.
                # However, for the DB schema `tax_year` column, we should probably use the `year` passed in,
                # or extract it from the date?
                # The DB schema has `tax_year` column.
                # Usually `tax_year` in these tables refers to the statement year.

                yield (
                    currency,
                    date_obj.isoformat(),
                    rate_str,
                    denomination,
                    year,
                    source_marker
                )
