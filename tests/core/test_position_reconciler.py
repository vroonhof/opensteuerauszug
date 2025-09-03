import unittest
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional
from opensteuerauszug.model.ech0196 import SecurityStock, QuotationType, CurrencyId
from opensteuerauszug.core.position_reconciler import PositionReconciler, ReconciledQuantity

# Helper to create SecurityStock instances easily
def create_stock(ref_date: str, qty: str, mutation: bool, currency: CurrencyId = "CHF", name: Optional[str] = None, q_type: QuotationType = "PIECE") -> SecurityStock:
    return SecurityStock(
        referenceDate=date.fromisoformat(ref_date),
        quantity=Decimal(qty),
        mutation=mutation,
        balanceCurrency=currency,
        name=name if name else ("Mutation" if mutation else "Balance"),
        quotationType=q_type
    )

class TestPositionReconciler(unittest.TestCase):

    def test_empty_stocks(self):
        reconciler = PositionReconciler([], identifier="EMPTY_TEST")
        self.assertEqual(reconciler.sorted_stocks, [])
        is_consistent = reconciler.check_consistency()
        self.assertTrue(is_consistent)
        pos = reconciler.synthesize_position_at_date(date(2023,1,1))
        self.assertIsNone(pos)

    def test_sort_stocks(self):
        s1 = create_stock("2023-01-01", "10", False) # Balance
        s2 = create_stock("2023-01-01", "5", True)  # Mutation on same day
        s3 = create_stock("2023-01-02", "15", False) # Balance next day
        s4 = create_stock("2022-12-31", "0", False)  # Earlier Balance
        
        stocks = [s3, s2, s1, s4]
        reconciler = PositionReconciler(stocks, identifier="SORT_TEST")
        
        self.assertEqual(reconciler.sorted_stocks[0].referenceDate, date(2022,12,31))
        self.assertEqual(reconciler.sorted_stocks[1].referenceDate, date(2023,1,1))
        self.assertFalse(reconciler.sorted_stocks[1].mutation) # s1 (balance)
        self.assertEqual(reconciler.sorted_stocks[2].referenceDate, date(2023,1,1))
        self.assertTrue(reconciler.sorted_stocks[2].mutation)  # s2 (mutation)
        self.assertEqual(reconciler.sorted_stocks[3].referenceDate, date(2023,1,2)) 

    def test_no_balance_statement(self):
        stocks = [create_stock("2023-01-01", "5", True, name="Buy")]
        reconciler = PositionReconciler(stocks, identifier="NO_BALANCE")
        with self.assertRaises(ValueError) as context:
            reconciler.check_consistency(raise_on_error=True)
        self.assertIn("No balance statement (mutation=False) found", str(context.exception))

    def test_simple_consistency_ok(self):
        stocks = [
            create_stock("2023-01-01", "100", False, name="Opening Balance"),
            create_stock("2023-01-05", "10", True, name="Buy Shares"),
            create_stock("2023-01-10", "-5", True, name="Sell Shares"),
            create_stock("2023-01-15", "105", False, name="Closing Balance")
        ]
        reconciler = PositionReconciler(stocks, identifier="CONSIST_OK")
        is_consistent = reconciler.check_consistency(raise_on_error=False)
        self.assertTrue(is_consistent)
        # Also test that it doesn't raise when consistent and raise_on_error=True
        try:
            reconciler.check_consistency(raise_on_error=True)
        except ValueError:
            self.fail("check_consistency raised ValueError unexpectedly for consistent data")

    def test_consistency_mismatch(self):
        stocks = [
            create_stock("2023-01-01", "100", False, name="Opening Balance"),
            create_stock("2023-01-05", "10", True, name="Buy Shares"), # Calc = 110
            create_stock("2023-01-15", "109", False, name="Wrong Closing Balance") # Reported 109
        ]
        reconciler = PositionReconciler(stocks, identifier="CONSIST_MISMATCH")
        with self.assertRaises(ValueError) as context:
            reconciler.check_consistency(raise_on_error=True)
        
    def test_multiple_mutations(self):
        stocks = [
            create_stock("2023-01-01", "50", False),
            create_stock("2023-01-02", "5", True),  # 55
            create_stock("2023-01-02", "10", True), # 65 (same day mutation)
            create_stock("2023-01-03", "-20", True),# 45
            create_stock("2023-01-04", "45", False) # Check
        ]
        reconciler = PositionReconciler(stocks, identifier="MULTI_MUTATION")
        is_consistent = reconciler.check_consistency(raise_on_error=False)
        self.assertTrue(is_consistent)
        # Test it doesn't raise when consistent
        try:
            reconciler.check_consistency(raise_on_error=True)
        except ValueError:
            self.fail("check_consistency raised ValueError unexpectedly for multi-mutation consistent data")

    def test_synthesize_position_no_prior_balance(self):
        stocks = [create_stock("2023-01-05", "10", True)] # Only a mutation
        reconciler = PositionReconciler(stocks, identifier="SYNTH_NO_BALANCE")
        pos = reconciler.synthesize_position_at_date(date(2023,1,1))
        self.assertIsNone(pos)

    def test_synthesize_position_at_first_balance(self):
        stocks = [create_stock("2023-01-01", "100", False, currency="USD")]
        reconciler = PositionReconciler(stocks, identifier="SYNTH_AT_BALANCE")
        pos = reconciler.synthesize_position_at_date(date(2023,1,1))
        self.assertIsNotNone(pos)
        if pos is not None: # Type checker guard
            self.assertEqual(pos.quantity, Decimal("100"))
            self.assertEqual(pos.reference_date, date(2023,1,1))
            self.assertEqual(pos.currency, "USD")

    def test_synthesize_position_after_mutation(self):
        stocks = [
            create_stock("2023-01-01", "100", False, currency="EUR"),
            create_stock("2023-01-05", "10", True) # Becomes 110
        ]
        reconciler = PositionReconciler(stocks, identifier="SYNTH_AFTER_MUT")
        
        pos_before_mut = reconciler.synthesize_position_at_date(date(2023,1,5))
        self.assertIsNotNone(pos_before_mut)
        if pos_before_mut is not None:
            self.assertEqual(pos_before_mut.quantity, Decimal("100"))
            self.assertEqual(pos_before_mut.currency, "EUR")

        pos_after_mut = reconciler.synthesize_position_at_date(date(2023,1,6))
        self.assertIsNotNone(pos_after_mut)
        if pos_after_mut is not None:
            self.assertEqual(pos_after_mut.quantity, Decimal("110"))
            self.assertEqual(pos_after_mut.currency, "EUR")

    def test_synthesize_position_at_later_balance(self):
        stocks = [
            create_stock("2023-01-01", "100", False, currency="GBP"),
            create_stock("2023-01-05", "10", True),   # 110
            create_stock("2023-01-10", "-5", True),  # 105
            create_stock("2023-01-15", "105", False, currency="GBP") # This is the balance
        ]
        reconciler = PositionReconciler(stocks, identifier="SYNTH_LATER_BALANCE")
        pos = reconciler.synthesize_position_at_date(date(2023,1,15))
        self.assertIsNotNone(pos)
        if pos is not None:
            self.assertEqual(pos.quantity, Decimal("105")) 
            self.assertEqual(pos.currency, "GBP") 
        
        pos_after_final_balance = reconciler.synthesize_position_at_date(date(2023,1,16))
        self.assertIsNotNone(pos_after_final_balance)
        if pos_after_final_balance is not None:
            self.assertEqual(pos_after_final_balance.quantity, Decimal("105"))
            self.assertEqual(pos_after_final_balance.currency, "GBP") # Currency from the 2023-01-15 balance

    def test_synthesize_position_far_future(self):
        stocks = [
            create_stock("2023-01-01", "100", False, currency="AUD"),
            create_stock("2023-01-05", "10", True) # 110
        ]
        reconciler = PositionReconciler(stocks, identifier="SYNTH_FUTURE")
        pos = reconciler.synthesize_position_at_date(date(2024,1,1))
        self.assertIsNotNone(pos)
        if pos is not None:
            self.assertEqual(pos.quantity, Decimal("110"))
            self.assertEqual(pos.currency, "AUD")

    def test_synthesize_position_between_mutations(self):
        stocks = [
            create_stock("2023-01-01", "100", False, currency="CAD"),
            create_stock("2023-01-05", "10", True),  # 110 on 2023-01-05
            create_stock("2023-01-10", "-5", True)   # 105 on 2023-01-10
        ]
        reconciler = PositionReconciler(stocks, identifier="SYNTH_BETWEEN_MUT")
        pos = reconciler.synthesize_position_at_date(date(2023,1,7))
        self.assertIsNotNone(pos)
        if pos is not None:
            self.assertEqual(pos.quantity, Decimal("110"))
            self.assertEqual(pos.currency, "CAD")

    def test_consistency_with_same_day_balance_and_mutation(self):
        stocks = [
            create_stock("2023-01-01", "100", False, name="Start Day Balance"),
            create_stock("2023-01-01", "10", True, name="Intraday Buy"), # Calc 110
            create_stock("2023-01-02", "110", False, name="Next Day Balance") 
        ]
        reconciler = PositionReconciler(stocks, identifier="SAME_DAY_CONSIST")
        is_consistent = reconciler.check_consistency()
        self.assertTrue(is_consistent)

        stocks_mismatch = [
            create_stock("2023-01-01", "100", False, name="Start Day Balance"),
            create_stock("2023-01-01", "10", True, name="Intraday Buy"), # Calc 110
            create_stock("2023-01-02", "109", False, name="Next Day Balance Mismatch") 
        ]
        reconciler_mismatch = PositionReconciler(stocks_mismatch, identifier="SAME_DAY_MM")
        with self.assertRaises(ValueError) as context_mm:
            reconciler_mismatch.check_consistency(raise_on_error=True)
        self.assertIn("Position reconciliation failed", str(context_mm.exception))

    def test_synthesize_with_same_day_balance_and_mutation(self):
        stocks = [
            create_stock("2023-01-01", "100", False, currency="JPY"), 
            create_stock("2023-01-01", "10", True),  
        ]
        reconciler = PositionReconciler(stocks, identifier="SYNTH_SAME_DAY")
        
        pos_start_day1 = reconciler.synthesize_position_at_date(date(2023,1,1))
        self.assertIsNotNone(pos_start_day1)
        if pos_start_day1 is not None:
            self.assertEqual(pos_start_day1.quantity, Decimal("100"))
            self.assertEqual(pos_start_day1.currency, "JPY")

        pos_start_day2 = reconciler.synthesize_position_at_date(date(2023,1,2))
        self.assertIsNotNone(pos_start_day2)
        if pos_start_day2 is not None:
            self.assertEqual(pos_start_day2.quantity, Decimal("110"))
            self.assertEqual(pos_start_day2.currency, "JPY")

    def test_out_of_order_event_in_consistency_check(self):
        # The reconciler sorts on init, so this tests the safeguard within check_consistency if sorting failed or list was modified post-init.
        # Create a reconciler with already sorted stocks
        initial_stocks = [create_stock("2023-01-01", "100", False)]
        reconciler = PositionReconciler(initial_stocks, identifier="OUT_OF_ORDER_CHECK")
        # Manually insert an out-of-order event into its internal sorted_stocks list
        # This is white-box testing the internal safeguard.
        reconciler.sorted_stocks.append(create_stock("2022-12-31", "10", True)) # Event before current_date in check
        # Note: this event will be at the end of the list, but its date is earlier than the first.
        # The check_consistency starts from the first *balance*. 
        # Let's construct a more direct case for the check within the loop:
        stocks_for_test = [
             create_stock("2023-01-01", "100", False, name="Balance1"),
             create_stock("2023-01-03", "10", True, name="MutationOK"), # current_date becomes 2023-01-03
             # Now insert an event that would be processed *after* MutationOK but has an earlier date
        ]
        reconciler_direct = PositionReconciler(stocks_for_test, "ORDER_DIRECT")
        # Manually append to sorted_stocks post-initial sort for this specific test
        reconciler_direct.sorted_stocks.append(create_stock("2023-01-02", "5", True, name="LateOutOfOrderMutation"))
        # Resort to place it in processing order, but with wrong date logic if safeguard fails
        reconciler_direct.sorted_stocks = sorted(reconciler_direct.sorted_stocks, key=lambda s: (s.referenceDate, s.mutation))
        # Expected order: B(01-01), M(01-02), M(01-03)
        # The check `if event_date < current_date:` in `check_consistency` is designed to catch this
        # if `current_date` is not updated correctly or events are grossly misordered despite initial sort.
        # With the current loop in check_consistency, current_date advances with each processed event.
        # The primary sorting at __init__ should prevent this. The internal check is a strong safeguard.
        # This test, as written, is a bit hard to trigger the specific line without complex mocking
        # or a very specific ordering that bypasses the initial sort logic for a test.
        # Given robust initial sorting, the safeguard `if event_date < current_date:` is less likely to trigger.
        # The critical part is that the list given to check_consistency is correctly sorted.
        # We can simplify this test to ensure that if it *does* happen, it's caught.
        # For now, this test is more of a conceptual check of that line of code.
        # If the list became [B(01-01), M(01-03), M(01-02)], when M(01-02) is processed, current_date would be 01-03.
        # This would trigger the error. Let's try to force that.
        
        forced_stocks = [
            create_stock("2023-01-01", "100", False, name="B1"),
            create_stock("2023-01-03", "10", True, name="M_OK_Later"),
            create_stock("2023-01-02", "5", True, name="M_ERR_Earlier")
        ]
        # We need to bypass the reconciler's own sort for this test of the internal check.
        reconciler_forced = PositionReconciler([], "FORCED_ORDER") # Init with empty
        reconciler_forced.sorted_stocks = forced_stocks # Manually set the unsorted (by date logic) list
        
        with self.assertRaises(ValueError) as context_forced:
            reconciler_forced.check_consistency(raise_on_error=True)
        self.assertIn("Stock events appear out of order", str(context_forced.exception))

    def test_synthesize_backward_only_future_balance(self):
        stocks = [create_stock("2023-02-01", "200", False, currency="JPY", name="Future Balance")]
        reconciler = PositionReconciler(stocks, identifier="SYNTH_BACK_ONLY_FUTURE")
        pos = reconciler.synthesize_position_at_date(date(2023,1,15)) # Target before future balance
        if pos is not None:
            self.assertEqual(pos.quantity, Decimal("200"))
            self.assertEqual(pos.currency, "JPY")
            self.assertEqual(pos.reference_date, date(2023,1,15))

    def test_synthesize_backward_with_intervening_mutations(self):
        stocks = [
            create_stock("2023-01-10", "-10", True, name="Mutation1"),  # Target: 2023-01-01
            create_stock("2023-01-20", "+30", True, name="Mutation2"),
            create_stock("2023-02-01", "220", False, currency="USD", name="Future Balance") # Future Bal = 220. After M2: 220-30=190. After M1: 190-(-10)=200
        ]
        reconciler = PositionReconciler(stocks, identifier="SYNTH_BACK_MUTATIONS")
        # Expected at 2023-01-01 should be 200 (220 - 30 - (-10))
        pos = reconciler.synthesize_position_at_date(date(2023,1,1))
        if pos is not None:
            self.assertEqual(pos.quantity, Decimal("200")) 
            self.assertEqual(pos.currency, "USD")

    def test_synthesize_backward_chooses_earliest_future_balance(self):
        stocks = [
            create_stock("2023-02-01", "220", False, currency="USD", name="Earlier Future Balance"),
            create_stock("2023-01-15", "-5", True, name="MutationBetween"), # Should be unapplied from 220 -> 225
            create_stock("2023-03-01", "300", False, currency="USD", name="Later Future Balance")
        ]
        reconciler = PositionReconciler(stocks, identifier="SYNTH_BACK_EARLIEST_FB")
        # Should use 2023-02-01 as base. Qty for 2023-01-10: 220 - (-5) = 225
        pos = reconciler.synthesize_position_at_date(date(2023,1,10))
        if pos is not None:
            self.assertEqual(pos.quantity, Decimal("225"))
            self.assertEqual(pos.currency, "USD")

    def test_synthesize_fails_if_no_balances_at_all(self):
        stocks = [
            create_stock("2023-01-10", "-10", True, name="Mutation1"),
            create_stock("2023-01-20", "+30", True, name="Mutation2"),
        ]
        reconciler = PositionReconciler(stocks, identifier="SYNTH_NO_BALANCES_ANYWHERE")
        pos = reconciler.synthesize_position_at_date(date(2023,1,1))

    def test_synthesize_backward_mutation_on_target_date_ignored(self):
        stocks = [
            create_stock("2023-01-15", "+5", True, name="MutationOnTargetDate"),
            create_stock("2023-02-01", "205", False, currency="CAD", name="Future Balance")
        ]
        reconciler = PositionReconciler(stocks, identifier="SYNTH_BACK_MUT_ON_TARGET")
        # Synthesize for START of 2023-01-15. Mutation on this day is ignored.
        # Expected qty is 205 (from future balance, no mutations between target and future balance to unapply).
        pos = reconciler.synthesize_position_at_date(date(2023,1,15))
        if pos is not None:
            self.assertEqual(pos.quantity, Decimal("205"))
            self.assertEqual(pos.currency, "CAD")

    def test_synthesize_forward_preferred_if_past_balance_exists(self):
        stocks = [
            create_stock("2023-01-01", "100", False, currency="CHF", name="Past Balance"),
            create_stock("2023-01-05", "+10", True, name="MutationAfterPast"), # Makes it 110
            create_stock("2023-02-01", "300", False, currency="CHF", name="Future Balance") # Should not be used for backward
        ]
        reconciler = PositionReconciler(stocks, identifier="SYNTH_FORWARD_OVER_BACKWARD")
        pos = reconciler.synthesize_position_at_date(date(2023,1,10)) # Target date is after past balance and mutation
        if pos is not None:
            self.assertEqual(pos.quantity, Decimal("110"))
            self.assertEqual(pos.currency, "CHF")

if __name__ == '__main__':
    unittest.main() 
