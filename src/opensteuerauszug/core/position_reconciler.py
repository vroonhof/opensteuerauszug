import bisect
import logging
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple
from decimal import Decimal
from opensteuerauszug.model.ech0196 import SecurityStock, CurrencyId, QuotationType
from opensteuerauszug.util.sorting import sort_security_stocks

# A logger for this module
logger = logging.getLogger(__name__)

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
        log_prefix = f"[{self.identifier}]"

        if not self.sorted_stocks:
            logger.info(f"{log_prefix} No stock data to check.")
            return True, [] # Empty is trivially consistent

        first_balance_idx = -1
        for i, stock in enumerate(self.sorted_stocks):
            if not stock.mutation:
                first_balance_idx = i
                break
        
        if first_balance_idx == -1:
            msg = f"{log_prefix} Consistency check failed: No balance statement (mutation=False) found to start reconciliation."
            logger.error(msg)
            if raise_on_error:
                raise ValueError(msg)
            return False, [msg]

        start_balance_event = self.sorted_stocks[first_balance_idx]
        current_quantity = start_balance_event.quantity
        current_date = start_balance_event.referenceDate
        
        logger.debug(f"{log_prefix} Starting consistency check from initial balance on {current_date}. Initial Qty: {current_quantity} ({start_balance_event.balanceCurrency}).")
        
        is_consistent = True
        log_messages = []

        for i in range(first_balance_idx + 1, len(self.sorted_stocks)):
            stock_event = self.sorted_stocks[i]
            event_date = stock_event.referenceDate
            
            if event_date < current_date:
                 # This should not happen if stocks are correctly sorted.
                msg = f"ERROR: {log_prefix} Stock events appear out of order: event on {event_date} after processing {current_date}. Aborting."
                logger.error(msg)
                log_messages.append(msg)
                is_consistent = False
                break 
            
            # Log date advancement if applicable (can be multiple events on same day)
            # current_date = event_date # Update current_date as we process events for this date

            if stock_event.mutation:
                delta_quantity = stock_event.quantity # For mutations, quantity is the change
                calculated_new_quantity = current_quantity + delta_quantity
                logger.debug(f"{log_prefix} Date: {event_date}. Applying mutation: Name='{stock_event.name or 'N/A'}', Qty Change={delta_quantity}. Old Qty: {current_quantity}, Calc New Qty: {calculated_new_quantity}.")
                current_quantity = calculated_new_quantity
                current_date = event_date # Event processed, advance current_date cursor
            else: # This is a new balance statement
                reported_quantity = stock_event.quantity
                logger.debug(f"{log_prefix} Date: {event_date}. Encountered balance statement: Name='{stock_event.name or 'N/A'}', Reported Qty={reported_quantity}. Current Calculated Qty: {current_quantity}.")

                if current_quantity != reported_quantity:
                    is_consistent = False
                    discrepancy = reported_quantity - current_quantity
                    msg = f"ERROR: {log_prefix} Mismatch on {event_date}! Calculated Qty: {current_quantity}, Reported Qty in statement: {reported_quantity}. Discrepancy: {discrepancy}."
                    logger.error(msg)
                    log_messages.append(msg)
                else:
                    logger.debug(f"{log_prefix} Match on {event_date}: Calculated Qty {current_quantity} == Reported Qty {reported_quantity}.")
                
                # Reset current_quantity to the reported balance for continued reconciliation from this known point.
                current_quantity = reported_quantity
                current_date = event_date # Event processed, advance current_date cursor
        
        if is_consistent:
            logger.info(f"{log_prefix} Consistency check finished successfully.")
        else:
            logger.error(f"{log_prefix} Consistency check finished with errors.")
            if raise_on_error:
                error_summary = f"[{self.identifier}] Position reconciliation failed. Log:\n" + "\n".join(log_messages)
                raise ValueError(error_summary)
            
        return is_consistent, log_messages

    def synthesize_position_at_date(self, target_date: date, print_log: bool = False, assume_zero_if_no_balances: bool = False) -> Optional[ReconciledQuantity]:
        """
        Calculates the position (quantity) at the START of the target_date.
        This means mutations on target_date itself are not included.

        Args:
            target_date: The date for which to synthesize the position.
            print_log: If True, prints log messages to console as they are generated.
            assume_zero_if_no_balances: If True, and no balance (mutation=False) items are found, 
                                        assume an initial quantity of 0 before the earliest mutation.

        Returns:
            A ReconciledQuantity object if successful, None otherwise.
        """
        # Use a separate log for synthesis to avoid interference if called multiple times
        synthesis_log: List[str] = []
        log_prefix = f"[{self.identifier}]"

        def _synth_log(msg, level=logging.DEBUG):
            if print_log:
                logger.log(level, msg)

        if not self.sorted_stocks:
            if assume_zero_if_no_balances:
                _synth_log(f"{log_prefix} No stock data. Assuming 0 quantity at {target_date}.")
                return ReconciledQuantity(reference_date=target_date, quantity=Decimal("0"))
            _synth_log(f"{log_prefix} Cannot synthesize position for {target_date}: No stock data.")
            return None

        last_balance_event: Optional[SecurityStock] = None
        last_balance_idx = -1

        # Find the latest balance (mutation=False) that is effective at or before the START of target_date.
        # A balance on target_date itself is the state at the START of target_date.

        # Use bisect to find the point where dates go strictly > target_date
        # All stocks[:idx] have referenceDate <= target_date
        # All stocks[idx:] have referenceDate > target_date
        idx = bisect.bisect_right(self.sorted_stocks, target_date, key=lambda s: s.referenceDate)

        # Search backwards from idx-1 for the first balance event
        for i in range(idx - 1, -1, -1):
            stock = self.sorted_stocks[i]
            if not stock.mutation:
                last_balance_event = stock
                last_balance_idx = i
                break
        
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
            return ReconciledQuantity(reference_date=target_date, quantity=current_quantity, currency=current_currency)
        else:
            # --- Attempt Backward Synthesis Path --- 
            _synth_log(f"{log_prefix} No balance found at or before {target_date}. Attempting BACKWARD synthesis.")
            
            first_future_balance_event: Optional[SecurityStock] = None
            first_future_balance_idx = -1

            # Find the earliest balance (mutation=False) strictly AFTER target_date
            # We can start searching from idx, since self.sorted_stocks[idx] is the first event > target_date
            for i in range(idx, len(self.sorted_stocks)):
                stock = self.sorted_stocks[i]
                if not stock.mutation:
                    first_future_balance_event = stock
                    first_future_balance_idx = i
                    break # Found the earliest one
            
            if first_future_balance_event is None:
                # If there are NO balance items at all in the entire sorted_stocks list,
                # we assume an initial balance of 0 before any of the provided mutations.
                if assume_zero_if_no_balances and not any(not s.mutation for s in self.sorted_stocks):
                    _synth_log(f"{log_prefix} No balance items found for security. Assuming initial quantity 0.")
                    current_quantity = Decimal("0")
                    current_currency = self.sorted_stocks[0].balanceCurrency if self.sorted_stocks else None
                    
                    # Apply mutations that occurred strictly BEFORE the target_date.
                    for mutation_event in self.sorted_stocks:
                        if mutation_event.referenceDate >= target_date:
                            break
                        if mutation_event.mutation:
                            delta_quantity = mutation_event.quantity
                            current_quantity += delta_quantity
                            _synth_log(f"{log_prefix} Synthesizing from zero: Applied mutation on {mutation_event.referenceDate}, Name='{mutation_event.name or 'N/A'}', Qty Change={delta_quantity}. New Qty: {current_quantity}.")

                    _synth_log(f"{log_prefix} Synthesized from zero for START of {target_date}: Final Qty: {current_quantity} ({current_currency}).")
                    return ReconciledQuantity(reference_date=target_date, quantity=current_quantity, currency=current_currency)

                _synth_log(f"{log_prefix} Cannot synthesize BACKWARD for {target_date}: No balance (mutation=False) found after this date to serve as a starting point.")
                return None

            current_quantity = first_future_balance_event.quantity
            current_currency = first_future_balance_event.balanceCurrency
            effective_future_balance_date = first_future_balance_event.referenceDate

            _synth_log(f"{log_prefix} Synthesizing BACKWARD for START of {target_date}: Starting from future balance on {effective_future_balance_date}, Qty: {current_quantity} ({current_currency}).")

            # Iterate backward from the event *before* first_future_balance_event
            # down to events that are still at or after target_date.
            # Mutations on target_date are unapplied because they happen during
            # target_date and are therefore not part of the start-of-day position.
            for i in range(first_future_balance_idx - 1, -1, -1):
                mutation_event = self.sorted_stocks[i]

                if mutation_event.referenceDate < target_date:
                    # We've gone too far back.
                    break
                
                # Only consider mutations that happened between target_date and effective_future_balance_date
                if mutation_event.mutation: # Is a transaction/mutation
                    delta_quantity = mutation_event.quantity
                    current_quantity -= delta_quantity # Un-apply the mutation
                    _synth_log(f"{log_prefix} Synthesizing BACKWARD for {target_date}: Un-applied mutation on {mutation_event.referenceDate}, Name='{mutation_event.name or 'N/A'}', Qty Change={-delta_quantity}. New Qty: {current_quantity}.")
            
            logger.debug(f"{log_prefix} Synthesized BACKWARD position for START of {target_date}: Final Qty: {current_quantity} ({current_currency}).")
            return ReconciledQuantity(reference_date=target_date, quantity=current_quantity, currency=current_currency) 
