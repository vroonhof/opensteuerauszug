import pytest
from decimal import Decimal
from opensteuerauszug.util import round_accounting

@pytest.mark.parametrize(
    "input_value, expected_output",
    [
        # Values < 100 (round to 3 decimal places)
        (Decimal("99.1234"), Decimal("99.123")),
        (Decimal("99.1235"), Decimal("99.124")),
        (Decimal("0.1234"), Decimal("0.123")),
        (Decimal("0.1235"), Decimal("0.124")),
        (Decimal("-99.1234"), Decimal("-99.123")),
        (Decimal("-99.1235"), Decimal("-99.124")),
        (Decimal("50"), Decimal("50.000")),
        (50, Decimal("50.000")), # int input
        (50.1234, Decimal("50.123")), # float input
        (50.1235, Decimal("50.124")), # float input
        (Decimal("99.9995"), Decimal("100.000")), # Rounds up to 100, still 3 decimals? Spec says < 100
        (Decimal("99.9994"), Decimal("99.999")),

        # Values >= 100 (round to 2 decimal places)
        (Decimal("100"), Decimal("100.00")),
        (Decimal("100.123"), Decimal("100.12")),
        (Decimal("100.125"), Decimal("100.13")),
        (Decimal("1234.567"), Decimal("1234.57")),
        (Decimal("-100"), Decimal("-100.00")),
        (Decimal("-100.123"), Decimal("-100.12")),
        (Decimal("-100.125"), Decimal("-100.13")),
        (100, Decimal("100.00")), # int input
        (100.123, Decimal("100.12")), # float input
        (100.125, Decimal("100.13")), # float input

        # Zero
        (Decimal("0"), Decimal("0.000")),
        (0, Decimal("0.000")),
        (0.0, Decimal("0.000")),

        # Edge case exactly 100 after rounding from < 100
        # According to spec "Beträge kleiner 100 sind mit 3 Nachkommastellen darzustellen"
        # Even if rounding makes it 100, the *original* value was < 100.
        (Decimal("99.9995"), Decimal("100.000")),

        # Edge case exactly 100
         (Decimal("100.000"), Decimal("100.00")),
         (Decimal("100.004"), Decimal("100.00")),
         (Decimal("100.005"), Decimal("100.01")),

         # Edge case slightly below 100
         (Decimal("99.999"), Decimal("99.999")),

    ],
)
def test_round_accounting(input_value, expected_output):
    """Tests the round_accounting function with various inputs."""
    assert round_accounting(input_value) == expected_output

# Test specifically the rounding rule (DIN 1333 / ROUND_HALF_UP)
@pytest.mark.parametrize(
    "input_value, precision, expected_output",
    [
        (Decimal("10.124"), 2, Decimal("10.12")), # < 5 rounds down
        (Decimal("10.125"), 2, Decimal("10.13")), # = 5 rounds up
        (Decimal("10.126"), 2, Decimal("10.13")), # > 5 rounds up
        (Decimal("10.1234"), 3, Decimal("10.123")), # < 5 rounds down
        (Decimal("10.1235"), 3, Decimal("10.124")), # = 5 rounds up
        (Decimal("10.1236"), 3, Decimal("10.124")), # > 5 rounds up
    ]
)
def test_rounding_mode(input_value, precision, expected_output):
    """Verifies the rounding mode specifically."""
    if abs(input_value) < 100:
         # For values < 100, we expect 3 decimal places
         assert round_accounting(input_value) == input_value.quantize(Decimal("0.001"), rounding='ROUND_HALF_UP')
    else:
         # For values >= 100, we expect 2 decimal places
         assert round_accounting(input_value) == input_value.quantize(Decimal("0.01"), rounding='ROUND_HALF_UP')

    # Direct check based on precision param for clarity
    if precision == 2:
        quantizer = Decimal("0.01")
    else: # precision == 3
        quantizer = Decimal("0.001")
    assert input_value.quantize(quantizer, rounding='ROUND_HALF_UP') == expected_output

