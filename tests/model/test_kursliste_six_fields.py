
import pytest
from decimal import Decimal
from opensteuerauszug.model.kursliste import Payment, Legend

def test_payment_six_id_support():
    """Test that Payment supports paymentIdSIX."""
    # Instantiating with paymentIdSIX. If it's not supported, it might be ignored or raise an error.
    # The user states it is currently ignored.
    payment = Payment(
        id=1,
        currency="CHF",
        paymentIdSIX="SIX123"
    )

    # This assertion should fail if the field is missing/ignored
    assert hasattr(payment, "paymentIdSIX")
    assert payment.paymentIdSIX == "SIX123"

def test_legend_six_id_support():
    """Test that Legend supports eventIdSIX."""
    legend = Legend(
        id=1,
        eventIdSIX="EVT456"
    )

    # This assertion should fail if the field is missing/ignored
    assert hasattr(legend, "eventIdSIX")
    assert legend.eventIdSIX == "EVT456"
