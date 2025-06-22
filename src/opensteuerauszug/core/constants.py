from decimal import Decimal

# For marking a quantity that is mandatory in the model, but we cannot compute it it yet.
# TODO(consider making it optional in our internal copy of the model)
UNINITIALIZED_QUANTITY = Decimal('-1')
# Standard Swiss withholding tax rate used for revenue subject to withholding.
WITHHOLDING_TAX_RATE = Decimal("0.35")
