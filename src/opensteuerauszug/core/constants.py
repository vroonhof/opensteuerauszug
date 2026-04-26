from decimal import Decimal

# Legacy quantity sentinel retained for backward compatibility with older test
# fixtures and importer data paths. New code should use None for missing
# quantity values.
UNINITIALIZED_QUANTITY = Decimal("-1")
# Standard Swiss withholding tax rate used for revenue subject to withholding.
WITHHOLDING_TAX_RATE = Decimal("0.35")
