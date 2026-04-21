"""Best-name-wins registry for security display names.

Broker statements describe the same security in many places (trades,
open positions, dividend postings).  Importers want to use the most
authoritative one.  Each importer historically re-implemented the same
defaultdict-based bookkeeping around a ``(best_name, priority)`` tuple.

``SecurityNameRegistry`` is a small value object that encapsulates that
bookkeeping so importers can compose it in instead of copying the code.
"""

from collections import defaultdict
from typing import Iterator, Tuple

from opensteuerauszug.model.position import SecurityPosition

from .types import SecurityNameMetadata


class SecurityNameRegistry:
    """Tracks the highest-priority name seen for each SecurityPosition.

    Priorities are caller-defined; higher wins, ties keep the existing
    entry.  Typical conventions used by broker importers:

    * 10 — OpenPositions snapshot (authoritative)
    * 8  — Trade rows
    * 5  — Transfers
    * 0  — CashTransaction descriptions (fallback only)

    The class only records names; resolving the final display string
    (including fallbacks to description or symbol) is the importer's
    responsibility via :meth:`resolve`.
    """

    def __init__(self) -> None:
        self._entries: defaultdict[SecurityPosition, SecurityNameMetadata] = defaultdict(
            lambda: {"best_name": None, "priority": -1}
        )

    def update(self, position: SecurityPosition, name: str, priority: int) -> None:
        """Record *name* for *position* if *priority* beats the current best."""
        entry = self._entries[position]
        if priority > entry["priority"]:
            entry["best_name"] = name
            entry["priority"] = priority

    def best(self, position: SecurityPosition) -> str | None:
        """Return the best name recorded so far, or ``None`` if none."""
        return self._entries[position]["best_name"]

    def resolve(self, position: SecurityPosition) -> str:
        """Return the best name, falling back to description then symbol."""
        name = self.best(position)
        if name:
            return name
        if position.description:
            return position.description
        return position.symbol

    def __contains__(self, position: SecurityPosition) -> bool:
        return position in self._entries

    def items(self) -> Iterator[Tuple[SecurityPosition, SecurityNameMetadata]]:
        return iter(self._entries.items())
