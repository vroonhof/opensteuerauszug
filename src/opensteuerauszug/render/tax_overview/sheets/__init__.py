"""Per-sheet writers for the tax-overview workbook.

Each module owns exactly one sheet; orchestration lives in :mod:`..render`.
Sheets are pure functions: they take a :class:`TaxOverviewData` and mutate a
:class:`openpyxl.Workbook`, never performing arithmetic of their own. This
separation keeps visual regressions (column widths, styling) isolated from
numerical regressions (waterfall, FIFO).
"""

from .da1 import write_da1_sheet
from .fees import write_fees_sheet
from .fx import write_fx_rates_sheet
from .income import write_dividends_sheet, write_interest_sheet
from .ks36 import write_ks36_criteria_sheet, write_ks36_evidence_sheet
from .orders_sheet import write_orders_sheet
from .performance import write_performance_sheet
from .securities import write_securities_sheet
from .uebersicht import write_uebersicht_sheet
from .verzeichnis import write_verzeichnis_sheet

__all__ = [
    "write_da1_sheet",
    "write_dividends_sheet",
    "write_fees_sheet",
    "write_fx_rates_sheet",
    "write_interest_sheet",
    "write_ks36_criteria_sheet",
    "write_ks36_evidence_sheet",
    "write_orders_sheet",
    "write_performance_sheet",
    "write_securities_sheet",
    "write_uebersicht_sheet",
    "write_verzeichnis_sheet",
]
