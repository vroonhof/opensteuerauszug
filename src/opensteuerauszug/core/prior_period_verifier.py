"""
Prior-period position verifier.

Loads a previous-period eCH-0196 tax statement and verifies that every
security's opening (start-of-year) position in the current statement matches
the closing (end-of-year) position reported in the prior statement.

Matching is performed by ISIN first, then by valor number as a fallback.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from ..model.ech0196 import Security, TaxStatement

logger = logging.getLogger(__name__)


@dataclass
class PositionMismatch:
    """Describes a mismatch between prior-period ending and current opening position."""

    security_name: str
    isin: Optional[str]
    valor: Optional[int]
    prior_quantity: Decimal
    current_quantity: Decimal
    depot: Optional[str] = None

    @property
    def difference(self) -> Decimal:
        return self.current_quantity - self.prior_quantity

    def __str__(self) -> str:
        identifier = self.isin or (f"valor={self.valor}" if self.valor else self.security_name)
        depot_info = f" depot={self.depot}" if self.depot else ""
        return (
            f"Position mismatch for {identifier}{depot_info}: "
            f"prior ending qty={self.prior_quantity}, "
            f"current opening qty={self.current_quantity}, "
            f"difference={self.difference}"
        )


@dataclass
class MissingSecurity:
    """A security that exists in one statement but not the other."""

    security_name: str
    isin: Optional[str]
    valor: Optional[int]
    quantity: Decimal
    depot: Optional[str] = None

    def __str__(self) -> str:
        identifier = self.isin or (f"valor={self.valor}" if self.valor else self.security_name)
        depot_info = f" depot={self.depot}" if self.depot else ""
        return f"{identifier}{depot_info}: qty={self.quantity}"


@dataclass
class PriorPeriodVerificationResult:
    """Result of comparing prior-period ending positions to current opening positions."""

    mismatches: List[PositionMismatch] = field(default_factory=list)
    missing_in_current: List[MissingSecurity] = field(default_factory=list)
    missing_in_prior: List[MissingSecurity] = field(default_factory=list)
    matched_count: int = 0

    @property
    def is_ok(self) -> bool:
        return not self.mismatches and not self.missing_in_current and not self.missing_in_prior

    @property
    def error_count(self) -> int:
        return len(self.mismatches) + len(self.missing_in_current) + len(self.missing_in_prior)


def _security_key(security: Security) -> Optional[str]:
    """Return a canonical lookup key for a security, preferring ISIN over valor."""
    if security.isin:
        return f"isin:{security.isin}"
    if security.valorNumber:
        return f"valor:{security.valorNumber}"
    return None


def _get_ending_positions(
    statement: TaxStatement,
) -> Dict[str, Tuple[Decimal, Security, Optional[str]]]:
    """Extract ending (closing) positions from a tax statement.

    The ending position is the quantity from the security's ``taxValue``
    element whose ``referenceDate`` equals the statement's ``periodTo``.

    Returns:
        Mapping of security key -> (quantity, Security object, depot number).
    """
    positions: Dict[str, Tuple[Decimal, Security, Optional[str]]] = {}
    if not statement.listOfSecurities:
        return positions

    for depot in statement.listOfSecurities.depot:
        depot_number = depot.depotNumber
        for security in depot.security:
            key = _security_key(security)
            if key is None:
                logger.warning(
                    "Cannot identify security '%s' (positionId=%s) for prior-period "
                    "matching — no ISIN or valor number.",
                    security.securityName,
                    security.positionId,
                )
                continue

            if security.taxValue is None:
                logger.debug(
                    "Security %s has no taxValue — skipping for ending position.",
                    key,
                )
                continue

            quantity = security.taxValue.quantity
            if quantity == Decimal(0):
                logger.debug(
                    "Security %s has zero ending quantity — including in map.",
                    key,
                )

            positions[key] = (quantity, security, depot_number)

    return positions


def _get_opening_positions(
    statement: TaxStatement,
) -> Dict[str, Tuple[Decimal, Security, Optional[str]]]:
    """Extract opening (start-of-year) positions from a tax statement.

    The opening position is the first ``stock`` entry with ``mutation=False``
    for each security.  The eCH-0196 convention is that a balance stock entry
    records the position at the *start* of its ``referenceDate``.

    Returns:
        Mapping of security key -> (quantity, Security object, depot number).
    """
    positions: Dict[str, Tuple[Decimal, Security, Optional[str]]] = {}
    if not statement.listOfSecurities:
        return positions

    for depot in statement.listOfSecurities.depot:
        depot_number = depot.depotNumber
        for security in depot.security:
            key = _security_key(security)
            if key is None:
                logger.warning(
                    "Cannot identify security '%s' (positionId=%s) for prior-period "
                    "matching — no ISIN or valor number.",
                    security.securityName,
                    security.positionId,
                )
                continue

            # Find the first balance stock entry (mutation=False), ordered by date
            opening_stock = None
            for stock in sorted(security.stock, key=lambda s: (s.referenceDate, s.mutation)):
                if not stock.mutation:
                    opening_stock = stock
                    break

            if opening_stock is None:
                logger.debug(
                    "Security %s has no opening balance stock entry — skipping.",
                    key,
                )
                continue

            positions[key] = (opening_stock.quantity, security, depot_number)

    return positions


def verify_prior_period_positions(
    prior_statement: TaxStatement,
    current_statement: TaxStatement,
) -> PriorPeriodVerificationResult:
    """Compare ending positions from a prior-period statement against opening
    positions in the current statement.

    Args:
        prior_statement: The previous tax period's ``TaxStatement``.
        current_statement: The current tax period's ``TaxStatement``.

    Returns:
        A ``PriorPeriodVerificationResult`` with details of any mismatches
        or missing securities.
    """
    result = PriorPeriodVerificationResult()

    prior_ending = _get_ending_positions(prior_statement)
    current_opening = _get_opening_positions(current_statement)

    all_keys = set(prior_ending.keys()) | set(current_opening.keys())

    for key in sorted(all_keys):
        in_prior = key in prior_ending
        in_current = key in current_opening

        if in_prior and in_current:
            prior_qty, prior_sec, prior_depot = prior_ending[key]
            current_qty, current_sec, current_depot = current_opening[key]

            if prior_qty == current_qty:
                result.matched_count += 1
                logger.debug(
                    "Security %s: prior ending qty %s matches current opening qty.",
                    key,
                    prior_qty,
                )
            else:
                mismatch = PositionMismatch(
                    security_name=current_sec.securityName,
                    isin=current_sec.isin,
                    valor=current_sec.valorNumber,
                    prior_quantity=prior_qty,
                    current_quantity=current_qty,
                    depot=current_depot,
                )
                result.mismatches.append(mismatch)
                logger.warning("Prior-period verification: %s", mismatch)

        elif in_prior and not in_current:
            prior_qty, prior_sec, prior_depot = prior_ending[key]
            # Only flag as missing if the prior ending quantity was non-zero
            if prior_qty != Decimal(0):
                missing = MissingSecurity(
                    security_name=prior_sec.securityName,
                    isin=prior_sec.isin,
                    valor=prior_sec.valorNumber,
                    quantity=prior_qty,
                    depot=prior_depot,
                )
                result.missing_in_current.append(missing)
                logger.warning(
                    "Prior-period verification: security %s with qty %s "
                    "exists in prior period but has no opening position in current period.",
                    key,
                    prior_qty,
                )
            else:
                logger.debug(
                    "Security %s has zero ending quantity in prior period "
                    "and no opening in current — OK (fully sold).",
                    key,
                )
                result.matched_count += 1

        else:  # in_current and not in_prior
            current_qty, current_sec, current_depot = current_opening[key]
            # Only flag if the current opening quantity is non-zero
            if current_qty != Decimal(0):
                missing = MissingSecurity(
                    security_name=current_sec.securityName,
                    isin=current_sec.isin,
                    valor=current_sec.valorNumber,
                    quantity=current_qty,
                    depot=current_depot,
                )
                result.missing_in_prior.append(missing)
                logger.warning(
                    "Prior-period verification: security %s with opening qty %s "
                    "exists in current period but not in prior period.",
                    key,
                    current_qty,
                )
            else:
                logger.debug(
                    "Security %s has zero opening quantity in current period "
                    "and no entry in prior — OK (new position with zero start).",
                    key,
                )
                result.matched_count += 1

    return result
