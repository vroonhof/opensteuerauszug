from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple
from decimal import Decimal
from opensteuerauszug.model.ech0196 import SecurityStock, CurrencyId, QuotationType
from opensteuerauszug.util.sorting import sort_security_stocks

@dataclass
class ReconciledQuantity:
    """Represents a reconciled quantity at a specific date."""
    reference_date: date
    quantity: Decimal
    currency: Optional[CurrencyId] = None # For context, especially for zero balances

class PositionReconciler:
    """
    Reconciles a list of SecurityStock statements for a single security or cash position.
    It sorts stock events, checks for consistency between balances and mutations,
    and can synthesize positions at given dates.
    """
    def __init__(self, initial_stocks: List[SecurityStock], identifier: str = "UnknownPosition"):
        """
        Initializes the reconciler with a list of stock events.

        Args:
            initial_stocks: A list of SecurityStock objects.
            identifier: A string identifier for the position (e.g., symbol or account ID) for logging.
        """
        self.identifier = identifier
        self.sorted_stocks: List[SecurityStock] = sort_security_stocks(initial_stocks)
        self.reconciliation_log: List[str] = []

    def _add_log(self, message: str, print_immediately: bool = False):
        """Adds a message to the internal log. Optionally prints it."""
        self.reconciliation_log.append(message)
        if print_immediately:
            print(message)

    def get_log(self) -> List[str]:
        """Returns the collected log messages."""
        return list(self.reconciliation_log)

    def check_consistency(self, print_log: bool = False, raise_on_error: bool = False) -> Tuple[bool, List[str]]:
        """
        Walks through the sorted stock events, applying mutations and verifying quantities
        against balance statements (mutation=False).

        Focuses on quantity reconciliation. Value reconciliation is not yet implemented.

        Args:
            print_log: If True, prints log messages to console as they are generated.
            raise_on_error: If True, raises a ValueError if inconsistencies are found.

        Returns:
            A tuple: (is_consistent, log_messages).
            is_consistent is True if all balances match calculated quantities, False otherwise.
        
        Raises:
            ValueError: If raise_on_error is True and inconsistencies are found.
        """
        self.reconciliation_log = [] # Reset log
        log_prefix = f"[{self.identifier}]"

        if not self.sorted_stocks:
            self._add_log(f"{log_prefix} No stock data to check.", print_immediately=print_log)
            return True, self.reconciliation_log # Empty is trivially consistent

        first_balance_idx = -1
        for i, stock in enumerate(self.sorted_stocks):
            if not stock.mutation:
                first_balance_idx = i
                break
        
        if first_balance_idx == -1:
            msg = f"{log_prefix} Consistency check failed: No balance statement (mutation=False) found to start reconciliation."
            self._add_log(msg, print_immediately=print_log)
            if raise_on_error:
                raise ValueError(msg)
            return False, self.reconciliation_log

        start_balance_event = self.sorted_stocks[first_balance_idx]
        current_quantity = start_balance_event.quantity
        current_date = start_balance_event.referenceDate
        
        self._add_log(f"{log_prefix} Starting consistency check from initial balance on {current_date}. Initial Qty: {current_quantity} ({start_balance_event.balanceCurrency}).", print_immediately=print_log)
        
        is_consistent = True

        for i in range(first_balance_idx + 1, len(self.sorted_stocks)):
            stock_event = self.sorted_stocks[i]
            event_date = stock_event.referenceDate
            
            if event_date < current_date:
                 # This should not happen if stocks are correctly sorted.
                self._add_log(f"ERROR: {log_prefix} Stock events appear out of order: event on {event_date} after processing {current_date}. Aborting.", print_immediately=print_log)
                is_consistent = False
                break 
            
            # Log date advancement if applicable (can be multiple events on same day)
            # current_date = event_date # Update current_date as we process events for this date

            if stock_event.mutation:
                delta_quantity = stock_event.quantity # For mutations, quantity is the change
                calculated_new_quantity = current_quantity + delta_quantity
                self._add_log(f"{log_prefix} Date: {event_date}. Applying mutation: Name='{stock_event.name or 'N/A'}', Qty Change={delta_quantity}. Old Qty: {current_quantity}, Calc New Qty: {calculated_new_quantity}.", print_immediately=print_log)
                current_quantity = calculated_new_quantity
                current_date = event_date # Event processed, advance current_date cursor
            else: # This is a new balance statement
                reported_quantity = stock_event.quantity
                self._add_log(f"{log_prefix} Date: {event_date}. Encountered balance statement: Name='{stock_event.name or 'N/A'}', Reported Qty={reported_quantity}. Current Calculated Qty: {current_quantity}.", print_immediately=print_log)

                if current_quantity != reported_quantity:
                    is_consistent = False
                    discrepancy = reported_quantity - current_quantity
                    self._add_log(f"ERROR: {log_prefix} Mismatch on {event_date}! Calculated Qty: {current_quantity}, Reported Qty in statement: {reported_quantity}. Discrepancy: {discrepancy}.", print_immediately=print_log)
                else:
                    self._add_log(f"{log_prefix} Match on {event_date}: Calculated Qty {current_quantity} == Reported Qty {reported_quantity}.", print_immediately=print_log)
                
                # Reset current_quantity to the reported balance for continued reconciliation from this known point.
                current_quantity = reported_quantity
                current_date = event_date # Event processed, advance current_date cursor
        
        if is_consistent:
            self._add_log(f"{log_prefix} Consistency check finished successfully.", print_immediately=print_log)
        else:
            self._add_log(f"{log_prefix} Consistency check finished with errors.", print_immediately=print_log)
            if raise_on_error:
                error_summary = f"[{self.identifier}] Position reconciliation failed. Log:\n" + "\n".join(self.reconciliation_log)
                raise ValueError(error_summary)
            
        return is_consistent, self.reconciliation_log

    def synthesize_position_at_date(self, target_date: date, print_log: bool = False) -> Optional[ReconciledQuantity]:
        """
        Calculates the position (quantity) at the START of the target_date.
        This means mutations on target_date itself are not included.

        Args:
            target_date: The date for which to synthesize the position.
            print_log: If True, prints log messages to console as they are generated.

        Returns:
            A ReconciledQuantity object if successful, None otherwise.
        """
        # Use a separate log for synthesis to avoid interference if called multiple times
        synthesis_log: List[str] = []
        log_prefix = f"[{self.identifier}]"

        def _synth_log(msg):
            synthesis_log.append(msg)
            if print_log:
                print(msg)

        if not self.sorted_stocks:
            _synth_log(f"{log_prefix} Cannot synthesize position for {target_date}: No stock data.")
            self.reconciliation_log.extend(synthesis_log) # Append to main log
            return None

        last_balance_event: Optional[SecurityStock] = None
        last_balance_idx = -1

        # Find the latest balance (mutation=False) that is effective at or before the START of target_date.
        # A balance on target_date itself is the state at the START of target_date.
        for i, stock in enumerate(self.sorted_stocks):
            if not stock.mutation and stock.referenceDate <= target_date:
                last_balance_event = stock
                last_balance_idx = i
            elif stock.referenceDate > target_date and not stock.mutation: 
                # Found a balance statement after target_date, so the one chosen (if any) is the latest relevant.
                break
            # If stock.referenceDate > target_date and stock.mutation, keep searching for earlier balances.
        
        if last_balance_event is not None:
            # --- Forward Synthesis Path --- 
            current_quantity = last_balance_event.quantity
            current_currency = last_balance_event.balanceCurrency 
            effective_balance_date = last_balance_event.referenceDate
            
            _synth_log(f"{log_prefix} Synthesizing FORWARD for START of {target_date}: Starting from balance on {effective_balance_date}, Qty: {current_quantity} ({current_currency}).")

            # Apply mutations that occurred strictly AFTER the effective_balance_date
            # AND strictly BEFORE the target_date.
            for i in range(last_balance_idx + 1, len(self.sorted_stocks)):
                mutation_event = self.sorted_stocks[i]
                
                if mutation_event.referenceDate >= target_date:
                    break 
                
                if mutation_event.mutation:
                    delta_quantity = mutation_event.quantity
                    current_quantity += delta_quantity
                    _synth_log(f"{log_prefix} Synthesizing FORWARD for {target_date}: Applied mutation on {mutation_event.referenceDate}, Name='{mutation_event.name or 'N/A'}', Qty Change={delta_quantity}. New Qty: {current_quantity}.")

            _synth_log(f"{log_prefix} Synthesized FORWARD position for START of {target_date}: Final Qty: {current_quantity} ({current_currency}).")
            self.reconciliation_log.extend(synthesis_log)
            return ReconciledQuantity(reference_date=target_date, quantity=current_quantity, currency=current_currency)
        else:
            # --- Attempt Backward Synthesis Path --- 
            _synth_log(f"{log_prefix} No balance found at or before {target_date}. Attempting BACKWARD synthesis.")
            
            first_future_balance_event: Optional[SecurityStock] = None
            first_future_balance_idx = -1

            # Find the earliest balance (mutation=False) strictly AFTER target_date
            for i in range(len(self.sorted_stocks)):
                stock = self.sorted_stocks[i]
                if not stock.mutation and stock.referenceDate > target_date:
                    first_future_balance_event = stock
                    first_future_balance_idx = i
                    break # Found the earliest one
            
            if first_future_balance_event is None:
                _synth_log(f"{log_prefix} Cannot synthesize BACKWARD for {target_date}: No balance (mutation=False) found after this date to serve as a starting point.")
                self.reconciliation_log.extend(synthesis_log)
                return None

            current_quantity = first_future_balance_event.quantity
            current_currency = first_future_balance_event.balanceCurrency
            effective_future_balance_date = first_future_balance_event.referenceDate

            _synth_log(f"{log_prefix} Synthesizing BACKWARD for START of {target_date}: Starting from future balance on {effective_future_balance_date}, Qty: {current_quantity} ({current_currency}).")

            # Iterate backward from the event *before* first_future_balance_event
            # down to events that are still *after* target_date.
            # Mutations on target_date itself are *not* considered for synthesizing position at START of target_date.
            for i in range(first_future_balance_idx - 1, -1, -1):
                mutation_event = self.sorted_stocks[i]

                if mutation_event.referenceDate <= target_date:
                    # We've gone too far back, or reached target_date events.
                    # Mutations on target_date are not used for start-of-day balance.
                    break
                
                # Only consider mutations that happened between target_date and effective_future_balance_date
                if mutation_event.mutation: # Is a transaction/mutation
                    delta_quantity = mutation_event.quantity
                    current_quantity -= delta_quantity # Un-apply the mutation
                    _synth_log(f"{log_prefix} Synthesizing BACKWARD for {target_date}: Un-applied mutation on {mutation_event.referenceDate}, Name='{mutation_event.name or 'N/A'}', Qty Change={-delta_quantity}. New Qty: {current_quantity}.")
            
            _synth_log(f"{log_prefix} Synthesized BACKWARD position for START of {target_date}: Final Qty: {current_quantity} ({current_currency}).")
            self.reconciliation_log.extend(synthesis_log)
            return ReconciledQuantity(reference_date=target_date, quantity=current_quantity, currency=current_currency) 