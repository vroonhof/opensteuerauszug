from typing import Optional, List, Dict, Union # Dict might not be used in this subtask but good to have.
from datetime import date
from decimal import Decimal
from functools import lru_cache

from pydantic import ValidationError # For catching model validation errors

from .kursliste_db_reader import KurslisteDBReader
from ..model.kursliste import (
    Kursliste, Security,
    Share, Bond, Fund, Derivative, CoinBullion, CurrencyNote, LiborSwap, # Import concrete security types
    ExchangeRate, ExchangeRateMonthly, ExchangeRateYearEnd, Sign, Da1Rate, # Added Sign, Da1Rate
    SecurityGroupESTV, SecurityTypeESTV, Da1RateType # For mapping and parameters
)


class KurslisteAccessor:
    """
    Provides a unified interface to access Kursliste data, whether it's from
    a KurslisteDBReader (SQLite) or a list of Kursliste XML model objects.
    Caches results of its methods.
    """
    # Removed _security_group_to_model_map
    # Removed _dict_to_security_model method

    def __init__(self, data_source: Union[KurslisteDBReader, List[Kursliste]], tax_year: int):
        """
        Initializes the KurslisteAccessor.

        Args:
            data_source: The data source, either a KurslisteDBReader instance or a list of Kursliste model objects.
            tax_year: The primary tax year this accessor is responsible for. 
                      Used mainly for security lookups that are year-specific.
        """
        self.data_source = data_source
        self.tax_year = tax_year

    @lru_cache(maxsize=None)
    def get_exchange_rate(self, currency: str, reference_date: date) -> Optional[Decimal]:
        """
        Retrieves the exchange rate for a given currency and date.
        The result is cached.

        Args:
            currency: The 3-letter currency code (e.g., "USD").
            reference_date: The date for which the exchange rate is needed.

        Returns:
            The exchange rate as a Decimal, or None if not found.
        """
        if currency == "CHF": # CHF is always 1:1 with itself
            return Decimal("1")

        if isinstance(self.data_source, KurslisteDBReader):
            # KurslisteDBReader.get_exchange_rate is already cached
            return self.data_source.get_exchange_rate(currency, reference_date)
        
        elif isinstance(self.data_source, list): # List[Kursliste]
            # Iterate through each Kursliste object (typically one, but could be multiple for the same year)
            for kursliste_instance in self.data_source:
                if not isinstance(kursliste_instance, Kursliste):
                    continue # Should not happen with correct type hints but good for safety

                # Logic similar to _get_exchange_rate_from_xml_kursliste from KurslisteExchangeRateProvider
                # The tax_year for comparison within XML rates should be based on the reference_date's year
                xml_tax_year = reference_date.year

                # End-of-Year Logic (only if date is exactly year-end)
                if reference_date.month == 12 and reference_date.day == 31:
                    if hasattr(kursliste_instance, 'exchangeRatesYearEnd'):
                        for rate in kursliste_instance.exchangeRatesYearEnd:
                            if rate.currency == currency and rate.year == xml_tax_year:
                                if rate.value is not None:
                                    return Decimal(str(rate.value))
                                elif rate.valueMiddle is not None: # Fallback for certain year-end rates
                                    return Decimal(str(rate.valueMiddle))
                
                # Monthly Average Logic
                if hasattr(kursliste_instance, 'exchangeRatesMonthly'):
                    month_str = f"{reference_date.month:02d}"
                    for rate in kursliste_instance.exchangeRatesMonthly:
                        if rate.currency == currency and rate.year == xml_tax_year and rate.month == month_str:
                            if rate.value is not None:
                                return Decimal(str(rate.value))

                # Daily Rate Logic
                if hasattr(kursliste_instance, 'exchangeRates'):
                    for rate in kursliste_instance.exchangeRates:
                        if rate.currency == currency and rate.date == reference_date: # Direct date match
                            if rate.value is not None:
                                return Decimal(str(rate.value))
            return None # No rate found in any Kursliste XML object in the list
        
        return None # Should not be reached if data_source is correctly typed and handled above

    @lru_cache(maxsize=None)
    def get_security_by_valor(self, valor_number: int) -> Optional[Security]:
        """
        Finds a single security by its VALOR number for the accessor's tax_year.
        Result is cached.
        """
        if isinstance(self.data_source, KurslisteDBReader):
            # KurslisteDBReader.find_security_by_valor now returns Optional[Security]
            return self.data_source.find_security_by_valor(valor_number, self.tax_year)
        elif isinstance(self.data_source, list): # List[Kursliste]
            for kl_instance in self.data_source:
                if kl_instance.year == self.tax_year: # Ensure Kursliste year matches accessor's year context
                    security = kl_instance.find_security_by_valor(valor_number)
                    if security:
                        return security # Returns the first one found
            return None
        return None

    @lru_cache(maxsize=None)
    def get_security_by_isin(self, isin: str) -> Optional[Security]:
        """
        Finds a single security by its ISIN for the accessor's tax_year.
        Result is cached.
        """
        if isinstance(self.data_source, KurslisteDBReader):
            # KurslisteDBReader.find_security_by_isin now returns Optional[Security]
            return self.data_source.find_security_by_isin(isin, self.tax_year)
        elif isinstance(self.data_source, list): # List[Kursliste]
            for kl_instance in self.data_source:
                if kl_instance.year == self.tax_year:
                    security = kl_instance.find_security_by_isin(isin)
                    if security:
                        return security # Returns the first one found
            return None
        return None

    @lru_cache(maxsize=None)
    def get_securities_by_valor(self, valor_number: int) -> List[Security]:
        """
        Finds all securities by VALOR number for the accessor's tax_year.
        Result is cached.
        """
        if isinstance(self.data_source, KurslisteDBReader):
            # KurslisteDBReader.find_securities_by_valor now returns List[Security]
            return self.data_source.find_securities_by_valor(valor_number, self.tax_year)
        elif isinstance(self.data_source, list): # List[Kursliste]
            results: List[Security] = []
            for kl_instance in self.data_source:
                if kl_instance.year == self.tax_year:
                    securities_from_xml = kl_instance.find_securities_by_valor(valor_number)
                    results.extend(securities_from_xml)
            return results
        return [] # Should not be reached if data_source is correctly typed

    @lru_cache(maxsize=None)
    def get_sign_by_value(self, sign_value: str) -> Optional[Sign]:
        """
        Retrieves a Sign object by its sign_value for the accessor's tax_year.
        Result is cached.
        """
        if isinstance(self.data_source, KurslisteDBReader):
            return self.data_source.get_sign_by_value(sign_value, self.tax_year)
        elif isinstance(self.data_source, list): # List[Kursliste]
            for kl_instance in self.data_source:
                if kl_instance.year == self.tax_year:
                    if hasattr(kl_instance, 'signs') and kl_instance.signs:
                        for sign_obj in kl_instance.signs:
                            if sign_obj.sign == sign_value:
                                return sign_obj
            return None
        return None

    @lru_cache(maxsize=None)
    def get_da1_rate(self, country: str, security_group: SecurityGroupESTV,
                     security_type: Optional[SecurityTypeESTV] = None,
                     da1_rate_type: Optional[Da1RateType] = None,
                     reference_date: Optional[date] = None) -> Optional[Da1Rate]:
        """
        Retrieves a Da1Rate object based on criteria for the accessor's tax_year.
        It first attempts to find a rate matching the specific security_type,
        and if not found, falls back to a general rate for the security_group.
        Result is cached.
        """
        candidates: List[Da1Rate] = []
        if isinstance(self.data_source, KurslisteDBReader):
            # The DB reader returns all candidates matching country and security_group
            candidates = self.data_source.get_da1_rate(
                country=country,
                security_group=security_group,
                tax_year=self.tax_year
            )
        elif isinstance(self.data_source, list):  # List[Kursliste]
            for kl_instance in self.data_source:
                if kl_instance.year == self.tax_year and hasattr(kl_instance, 'da1Rates'):
                    for rate_obj in kl_instance.da1Rates:
                        if rate_obj.country == country and rate_obj.securityGroup == security_group:
                            candidates.append(rate_obj)

        if not candidates:
            return None

        # Centralized Filtering Logic
        # First, try for a specific match on security_type if one is provided
        if security_type:
            specific_matches = [r for r in candidates if r.securityType == security_type]
            if specific_matches:
                # If we found specific matches, filter based on them
                candidates = specific_matches
            else:
                # If no specific match, consider only general rates (where securityType is None)
                candidates = [r for r in candidates if r.securityType is None]
        else:
            # If no security_type was provided, only consider general rates
            candidates = [r for r in candidates if r.securityType is None]

        if da1_rate_type:
            candidates = [r for r in candidates if r.da1RateType == da1_rate_type]

        if reference_date:
            date_filtered_candidates = []
            for rate in candidates:
                is_valid = True
                if rate.validFrom and rate.validFrom > reference_date:
                    is_valid = False
                if rate.validTo and rate.validTo < reference_date:
                    is_valid = False
                if is_valid:
                    date_filtered_candidates.append(rate)
            candidates = date_filtered_candidates

        if not candidates:
            return None

        # Return the first valid candidate.
        return candidates[0]

    @lru_cache(maxsize=None)
    def get_securities_by_isin(self, isin: str) -> List[Security]:
        """
        Finds all securities by ISIN for the accessor's tax_year.
        Result is cached.
        """
        if isinstance(self.data_source, KurslisteDBReader):
            # KurslisteDBReader.find_securities_by_isin now returns List[Security]
            return self.data_source.find_securities_by_isin(isin, self.tax_year)
        elif isinstance(self.data_source, list): # List[Kursliste]
            results: List[Security] = []
            for kl_instance in self.data_source:
                if kl_instance.year == self.tax_year:
                    securities_from_xml = kl_instance.find_securities_by_isin(isin)
                    results.extend(securities_from_xml)
            return results
        return [] # Should not be reached if data_source is correctly typed
