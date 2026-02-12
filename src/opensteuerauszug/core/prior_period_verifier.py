"""
Prior-period position verifier.

Loads a previous-period eCH-0196 tax statement and verifies that every
security's opening (start-of-year) position in the current statement matches
the closing (end-of-year) position reported in the prior statement.

Matching is performed by depot number *and* security identifier (ISIN first,
then valor number as a fallback).

Securities without an opening balance stock entry are treated as having an
implicit opening quantity of zero — useful for newly acquired positions.
The verifier still checks that the prior period did not hold a non-zero
ending quantity for those securities.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Union

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


# A security identifier is a tagged tuple: ("isin", value) or ("valor", value).
SecurityId = Tuple[str, Union[str, int]]

# A position key combines the depot number with the security identifier.
PositionKey = Tuple[Optional[str], SecurityId]


def _security_identifier(security: Security) -> Optional[SecurityId]:
    """Return a canonical identifier for a security (without depot).

    Prefers ISIN over valor number.  Returns ``None`` when neither is
    available.
    """
    if security.isin:
        return ("isin", str(security.isin))
    if security.valorNumber:
        return ("valor", int(security.valorNumber))
    return None


def _position_key(depot_number: Optional[str], security: Security) -> Optional[PositionKey]:
    """Return a composite key that includes the depot and security identifier.

    Using the depot in the key ensures that the same security held in two
    different depots is tracked independently.
    """
    sec_id = _security_identifier(security)
    if sec_id is None:
        return None
    return (depot_number, sec_id)


# Type alias for the position maps.
_PositionMap = Dict[PositionKey, Tuple[Decimal, Security, Optional[str]]]


def _get_ending_positions(statement: TaxStatement) -> _PositionMap:
    """Extract ending (closing) positions from a tax statement.

    The ending position is the quantity from the security's ``taxValue``
    element.

    Returns:
        Mapping of position key -> (quantity, Security object, depot number).
    """
    positions: _PositionMap = {}
    if not statement.listOfSecurities:
        return positions

    for depot in statement.listOfSecurities.depot:
        depot_number = depot.depotNumber
        for security in depot.security:
            key = _position_key(depot_number, security)
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
            positions[key] = (quantity, security, depot_number)

    return positions


def _get_opening_positions(statement: TaxStatement) -> _PositionMap:
    """Extract opening (start-of-year) positions from a tax statement.

    The opening position is the first ``stock`` entry with ``mutation=False``
    for each security.  The eCH-0196 convention is that a balance stock entry
    records the position at the *start* of its ``referenceDate``.

    When no opening balance stock entry exists for a security the position is
    **not** included in the map.  The caller treats this as an implicit zero.

    Returns:
        Mapping of position key -> (quantity, Security object, depot number).
    """
    positions: _PositionMap = {}
    if not statement.listOfSecurities:
        return positions

    for depot in statement.listOfSecurities.depot:
        depot_number = depot.depotNumber
        for security in depot.security:
            key = _position_key(depot_number, security)
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
                # No opening balance → implicit zero.  We intentionally omit it
                # from the map; the comparison logic treats absence as zero and
                # will verify the prior period agrees.
                logger.debug(
                    "Security %s has no opening balance stock entry — "
                    "treating as implicit zero.",
                    key,
                )
                continue

            positions[key] = (opening_stock.quantity, security, depot_number)

    return positions


def _get_all_current_security_keys(statement: TaxStatement) -> _PositionMap:
    """Return a map of *every* identifiable security in the current statement,
    regardless of whether it has an opening balance.

    Securities without an opening balance are recorded with quantity zero.
    This lets us check that a prior-period holding was not silently dropped
    when the current statement simply omits the opening stock entry.
    """
    positions: _PositionMap = {}
    if not statement.listOfSecurities:
        return positions

    for depot in statement.listOfSecurities.depot:
        depot_number = depot.depotNumber
        for security in depot.security:
            key = _position_key(depot_number, security)
            if key is None:
                continue
            # Only add if not already present from _get_opening_positions
            if key not in positions:
                positions[key] = (Decimal(0), security, depot_number)

    return positions


def verify_prior_period_positions(
    prior_statement: TaxStatement,
    current_statement: TaxStatement,
) -> PriorPeriodVerificationResult:
    """Compare ending positions from a prior-period statement against opening
    positions in the current statement.

    Securities without an explicit opening balance stock entry are treated as
    having an opening quantity of zero.  If the prior period had a non-zero
    ending quantity for such a security the mismatch is reported.

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

    # Build the full set of security keys that appear in the current
    # statement so we can distinguish "security exists but has no opening
    # balance" from "security does not appear at all".
    all_current_keys = _get_all_current_security_keys(current_statement)

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

            # The security has no explicit opening balance in the current
            # statement.  That is fine as long as the prior ended at zero.
            # It may still *exist* in the current statement (with
            # transactions but no opening stock entry) — check for that
            # to give a better message.
            if prior_qty == Decimal(0):
                logger.debug(
                    "Security %s has zero ending quantity in prior period "
                    "and no opening in current — OK (fully sold).",
                    key,
                )
                result.matched_count += 1
            elif key in all_current_keys:
                # Security is present in the current statement but without
                # an opening balance → implicit zero vs. non-zero prior.
                _, current_sec, current_depot = all_current_keys[key]
                mismatch = PositionMismatch(
                    security_name=current_sec.securityName,
                    isin=current_sec.isin,
                    valor=current_sec.valorNumber,
                    prior_quantity=prior_qty,
                    current_quantity=Decimal(0),
                    depot=current_depot,
                )
                result.mismatches.append(mismatch)
                logger.warning("Prior-period verification: %s", mismatch)
            else:
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
                    "exists in prior period but not in current period at all.",
                    key,
                    prior_qty,
                )

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


class PriorPeriodXmlLoadError(Exception):
    """Raised when the prior-period XML file cannot be read or parsed.

    Wraps the underlying I/O or XML parsing error with a user-friendly
    message suitable for display on the CLI.
    """

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(
            f"Could not load prior-period tax statement from '{path}': {reason}"
        )


def load_prior_period_statement(file_path: str) -> TaxStatement:
    """Load and parse a prior-period eCH-0196 tax statement XML file.

    Provides user-friendly error messages for common failure modes such as
    missing files, permission errors, and malformed XML.

    Args:
        file_path: Path to the prior-period XML file.

    Returns:
        The parsed ``TaxStatement``.

    Raises:
        PriorPeriodXmlLoadError: On any I/O or parse failure.
    """
    import os

    if not os.path.exists(file_path):
        raise PriorPeriodXmlLoadError(
            file_path,
            "File does not exist. Check the path and try again.",
        )

    if not os.path.isfile(file_path):
        raise PriorPeriodXmlLoadError(
            file_path,
            "Path is not a regular file (perhaps a directory?).",
        )

    if not os.access(file_path, os.R_OK):
        raise PriorPeriodXmlLoadError(
            file_path,
            "File is not readable. Check file permissions.",
        )

    try:
        return TaxStatement.from_xml_file(file_path)
    except ValueError as exc:
        # TaxStatement.from_xml_file wraps lxml and other errors in ValueError.
        raise PriorPeriodXmlLoadError(file_path, str(exc)) from exc
    except Exception as exc:
        raise PriorPeriodXmlLoadError(
            file_path,
            f"Unexpected error: {exc}",
        ) from exc
