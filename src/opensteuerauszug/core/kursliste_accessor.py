import sqlite3
from typing import Optional, List, Union
from datetime import date
from decimal import Decimal
from functools import lru_cache

from .kursliste_db_reader import KurslisteDBReader
from opensteuerauszug.kursliste.converter import convert_kursliste_models_to_sqlite
from opensteuerauszug.model.kursliste import (
    Kursliste,
    Security,
    Sign,
    Da1Rate,
    SecurityGroupESTV,
    SecurityTypeESTV,
    Da1RateType,
)


class KurslisteAccessor:
    """
    Provides a unified interface to access Kursliste data backed by a
    KurslisteDBReader (on-disk or in-memory SQLite).
    Caches results of its methods.
    """

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
        self._db_reader: Optional[KurslisteDBReader] = (
            data_source if isinstance(data_source, KurslisteDBReader) else None
        )

    def _get_db_reader(self) -> Optional[KurslisteDBReader]:
        if self._db_reader is not None:
            return self._db_reader
        if isinstance(self.data_source, list):
            conn = sqlite3.connect(":memory:")
            convert_kursliste_models_to_sqlite(
                self.data_source, conn, default_tax_year=self.tax_year
            )
            self._db_reader = KurslisteDBReader(conn)
            return self._db_reader
        return None

    @lru_cache(maxsize=None)
    def get_exchange_rate(self, currency: str, reference_date: date) -> Optional[Decimal]:
        """
        Retrieves the exchange rate for a given currency and date.
        The result is cached.
        """
        if currency == "CHF":  # CHF is always 1:1 with itself
            return Decimal("1")

        reader = self._get_db_reader()
        if reader is not None:
            return reader.get_exchange_rate(currency, reference_date)
        return None

    @lru_cache(maxsize=None)
    def get_security_by_valor(self, valor_number: int) -> Optional[Security]:
        """
        Finds a single security by its VALOR number for the accessor's tax_year.
        Result is cached.
        """
        reader = self._get_db_reader()
        if reader is not None:
            return reader.find_security_by_valor(valor_number, self.tax_year)
        return None

    @lru_cache(maxsize=None)
    def get_security_by_isin(self, isin: str) -> Optional[Security]:
        """
        Finds a single security by its ISIN for the accessor's tax_year.
        Result is cached.
        """
        reader = self._get_db_reader()
        if reader is not None:
            return reader.find_security_by_isin(isin, self.tax_year)
        return None

    @lru_cache(maxsize=None)
    def get_securities_by_valor(self, valor_number: int) -> List[Security]:
        """
        Finds all securities by VALOR number for the accessor's tax_year.
        Result is cached.
        """
        reader = self._get_db_reader()
        if reader is not None:
            return reader.find_securities_by_valor(valor_number, self.tax_year)
        return []

    @lru_cache(maxsize=None)
    def get_sign_by_value(self, sign_value: str) -> Optional[Sign]:
        """
        Retrieves a Sign object by its sign_value for the accessor's tax_year.
        Result is cached.
        """
        reader = self._get_db_reader()
        if reader is not None:
            return reader.get_sign_by_value(sign_value, self.tax_year)
        return None

    @lru_cache(maxsize=None)
    def get_da1_rate(
        self,
        country: str,
        security_group: SecurityGroupESTV,
        security_type: Optional[SecurityTypeESTV] = None,
        da1_rate_type: Optional[Da1RateType] = None,
        reference_date: Optional[date] = None,
    ) -> Optional[Da1Rate]:
        """
        Retrieves a Da1Rate object based on criteria for the accessor's tax_year.
        It first attempts to find a rate matching the specific security_type,
        and if not found, falls back to a general rate for the security_group.
        Result is cached.
        """
        reader = self._get_db_reader()
        if reader is None:
            return None

        candidates = (
            reader.get_da1_rate(
                country=country, security_group=security_group, tax_year=self.tax_year
            )
            or []
        )
        if not candidates:
            return None

        if security_type:
            specific_matches = [r for r in candidates if r.securityType == security_type]
            if specific_matches:
                candidates = specific_matches
            else:
                candidates = [r for r in candidates if r.securityType is None]
        else:
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

        return candidates[0]

    @lru_cache(maxsize=None)
    def get_securities_by_isin(self, isin: str) -> List[Security]:
        """
        Finds all securities by ISIN for the accessor's tax_year.
        Result is cached.
        """
        reader = self._get_db_reader()
        if reader is not None:
            return reader.find_securities_by_isin(isin, self.tax_year)
        return []
