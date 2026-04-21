"""Shared helpers for building the Client object and canton assignment.

Broker statements expose holder names in a variety of shapes: sometimes
as separate first/last, sometimes as a single "Firstname Lastname"
string, sometimes as a looser "accountHolderName" field.  And the canton
on the eCH-0196 TaxStatement is typically embedded in an address string
like ``"CH-ZH"`` or comes straight from the user's config.

This module provides three small, pure helpers that each importer can
compose.  No inheritance, no hidden state.
"""

from typing import Optional, Tuple, cast, get_args

from opensteuerauszug.model.ech0196 import (
    CantonAbbreviation,
    Client,
    ClientNumber,
)


def is_nonempty_string(value: object) -> bool:
    """True if *value* is a non-empty / non-whitespace string."""
    return value is not None and isinstance(value, str) and bool(value.strip())


def split_full_name(value: object) -> Tuple[Optional[str], str]:
    """Split ``"First Middle Last"`` into ``("First", "Middle Last")``.

    Single-token inputs return ``(None, <token>)`` so callers can still
    place the value in ``lastName`` if that is all they have.
    """
    parts = str(value).strip().split()
    if len(parts) > 1:
        return parts[0], " ".join(parts[1:])
    return None, str(value).strip()


def resolve_first_last_name(
    *,
    first_name: object = None,
    last_name: object = None,
    full_name: object = None,
    account_holder_name: object = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Pick the best first/last name pair from a set of candidates.

    Precedence mirrors the existing importer logic:

    1. Explicit first_name + last_name
    2. Explicit first_name + split of full_name for the surname
    3. Split of full_name
    4. Split of account_holder_name
    """
    if is_nonempty_string(first_name) and is_nonempty_string(last_name):
        return str(first_name).strip(), str(last_name).strip()
    if is_nonempty_string(first_name) and is_nonempty_string(full_name):
        _, surname = split_full_name(full_name)
        return str(first_name).strip(), surname
    if is_nonempty_string(full_name):
        return split_full_name(full_name)
    if is_nonempty_string(account_holder_name):
        return split_full_name(account_holder_name)
    return None, None


def parse_swiss_canton(value: object) -> Optional[CantonAbbreviation]:
    """Return a validated CantonAbbreviation from loose input, or None.

    Accepts values like ``"ZH"``, ``"zh"`` or an ``"CH-ZH"`` style
    address string.  Returns ``None`` if the canton cannot be extracted
    or is not a recognised abbreviation.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    candidate = raw
    if "-" in raw:
        parts = raw.split("-")
        if len(parts) == 2 and parts[0].upper() == "CH":
            candidate = parts[1]
        else:
            return None
    candidate = candidate.strip().upper()
    valid = get_args(CantonAbbreviation)
    if candidate in valid:
        return cast(CantonAbbreviation, candidate)
    return None


def build_client(
    client_number: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
) -> Optional[Client]:
    """Construct a ``Client`` from an id + name pair, or return None.

    We require at minimum a client number; names are optional.  Callers
    should treat ``None`` as "nothing authoritative to put on the
    statement" and leave ``TaxStatement.client`` unset.
    """
    if not client_number:
        return None
    return Client(
        clientNumber=ClientNumber(client_number),
        firstName=first_name,
        lastName=last_name,
    )
