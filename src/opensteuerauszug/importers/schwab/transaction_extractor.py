import logging
import json
from typing import List, Optional, Tuple, Any, Annotated
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from opensteuerauszug.model.position import Position, SecurityPosition, CashPosition
from opensteuerauszug.model.ech0196 import SecurityStock, SecurityPayment, CurrencyId, QuotationType
from opensteuerauszug.core.constants import UNINITIALIZED_QUANTITY

# A logger for this module
logger = logging.getLogger(__name__)

# Known actions from formats.md
KNOWN_ACTIONS = {
    "Buy", "Cash In Lieu", "Credit Interest", "Deposit", "Dividend", "Journal",
    "NRA Tax Adj", "Reinvest Dividend", "Reinvest Shares", "Sale", "Stock Split",
    "Tax Withholding", "Transfer", "Wire Transfer"
}

class TransactionExtractor:
    """
    Extracts transaction data from Schwab JSON files in the expected format.
    """
    def __init__(self, filename: str):
        self.filename = filename

    def extract_transactions(self) -> Optional[List[Tuple[Position, List[SecurityStock], Optional[List[SecurityPayment]], str, Tuple[date, date]]]]:
        """
        Parses the JSON file and returns a list of tuples:
            (Position, list of SecurityStock, optional list of SecurityPayment, depot, covered date range)
        The actual extraction logic is stubbed out.
        """
        with open(self.filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return self._extract_transactions_from_dict(data)

    def _extract_transactions_from_dict(self, data: dict) -> Optional[List[Tuple[Position, List[SecurityStock], Optional[List[SecurityPayment]], str, Tuple[date, date]]]]:
        """
        Helper method to process the loaded JSON data and extract transactions.
        Refactored to use _process_single_transaction returning tuple.
        """
        if not data:
            return None

        from_date_str = data.get("FromDate")
        to_date_str = data.get("ToDate")

        if not from_date_str or not to_date_str:
            # print("Warning: Missing FromDate or ToDate in JSON data.")
            return None

        try:
            start_date = datetime.strptime(from_date_str, "%m/%d/%Y").date()
            end_date = datetime.strptime(to_date_str, "%m/%d/%Y").date()
        except ValueError:
            # print(f"Warning: Could not parse FromDate ('{from_date_str}') or ToDate ('{to_date_str}').")
            return None
        
        date_range = (start_date, end_date)
        
        processed_transactions = []
        depot: str
        raw_transactions: List[dict]

        if "BrokerageTransactions" in data:
            # Attempt to extract account number from filename for depot
            # Filename format: Individual_XXX178_Transactions_20250309-115444.json
            try:
                # Extract the part before "_Transactions_"
                name_part = self.filename.split('_Transactions_')[0]
                # Take the last part after the last underscore (should be XXX123)
                depot_identifier = name_part.split('_')[-1]
                # Get last 3 digits if it's longer, otherwise use as is.
                # Ensure it's digits only if it has non-digits at the start.
                # For "Individual ...123" this is just "123"
                # For "IRA ...XYZ789" this could be "XYZ789" -> "789"
                # We only want the numeric part at the end.
                numeric_part = ''.join(filter(str.isdigit, depot_identifier))
                if len(numeric_part) >= 3:
                    depot = numeric_part[-3:]
                elif numeric_part: # if there are some digits but less than 3
                    depot = numeric_part
                else: # if no digits found, or original identifier was non-numeric
                    print(f"Warning: Could not reliably extract 3-digit depot from filename: {self.filename}. Using full identifier: {depot_identifier}")
                    depot = depot_identifier # Fallback
            except Exception:
                print(f"Warning: Could not parse depot from filename: {self.filename}. Using 'UNKNOWN_BROKERAGE_DEPOT'.")
                depot = "UNKNOWN_BROKERAGE_DEPOT"
            raw_transactions = data.get("BrokerageTransactions", [])
        elif "Transactions" in data:
            depot = "AWARDS"
            raw_transactions = data.get("Transactions", [])
        else:
            # print("Warning: Neither 'BrokerageTransactions' nor 'Transactions' key found in JSON data.")
            return None

        # Group transactions by symbol (or lack thereof for cash)
        grouped_by_position: dict[Position, dict[str, Any]] = {}
        default_cash_currency = "USD" # Assume USD for Schwab cash

        for schwab_tx in raw_transactions:
            action = schwab_tx.get("Action", "").strip()
            if not action:
                raise ValueError(f"Missing action in transaction: {schwab_tx}")

            symbol_in_tx = schwab_tx.get("Symbol", "").strip()
            # is_cash_only_txn = not symbol_in_tx # Not directly used for primary pos creation anymore

            # Determine the primary security position if a symbol exists in the transaction
            security_pos_key: Optional[SecurityPosition] = None
            if symbol_in_tx:
                desc = schwab_tx.get("Description")
                if not desc or desc == symbol_in_tx: desc = None
                security_pos_key = SecurityPosition(depot=depot, symbol=symbol_in_tx, description=desc)
                if security_pos_key not in grouped_by_position:
                    grouped_by_position[security_pos_key] = {"position": security_pos_key, "stocks": [], "payments": []}
            
            # Determine context for _process_single_transaction
            # If there's a symbol, context is that security. Otherwise, a generic cash context.
            context_for_processing: Position
            if security_pos_key:
                context_for_processing = security_pos_key
            else:
                # This is a transaction without a symbol (e.g. pure cash journal in brokerage)
                # The cash_account_id for this context cash position will be None, even for AWARDS,
                # as there's no symbol from the transaction to specify it.
                context_for_processing = CashPosition(depot=depot, currentCy=default_cash_currency, cash_account_id=None)
                # Ensure this generic cash position is in grouped_by_position if it's the primary target for non-stock/non-payment items
                if context_for_processing not in grouped_by_position:
                     grouped_by_position[context_for_processing] = {"position": context_for_processing, "stocks": [], "payments": []}

            # Process the transaction
            # The pos_object argument to _process_single_transaction is context_for_processing
            sec_stock, sec_payment, cash_stock_mutation = self._process_single_transaction(schwab_tx, context_for_processing)

            # Assign results to appropriate lists
            if sec_stock:
                 if security_pos_key: # sec_stock always belongs to a security identified by symbol_in_tx
                      grouped_by_position[security_pos_key]["stocks"].append(sec_stock)
                 else:
                      # This case should ideally not occur if sec_stock is only generated when a symbol is present.
                      print(f"Warning: sec_stock generated but no security_pos_key (symbol_in_tx was empty?) for TX: {schwab_tx}")
                      
            if sec_payment:
                 if action == "Credit Interest": # Special case: payment belongs to a cash account
                     _cash_account_id_for_interest = None
                     if depot == 'AWARDS':
                         if symbol_in_tx:
                             _cash_account_id_for_interest = symbol_in_tx
                         else:
                             print(f"Warning: 'Credit Interest' for AWARDS depot has no Symbol in TX: {schwab_tx}. Associating with non-specific cash account.")
                    
                     target_cash_pos_for_interest = CashPosition(depot=depot, currentCy=default_cash_currency, cash_account_id=_cash_account_id_for_interest)
                     if target_cash_pos_for_interest not in grouped_by_position:
                         grouped_by_position[target_cash_pos_for_interest] = {"position": target_cash_pos_for_interest, "stocks": [], "payments": []}
                     grouped_by_position[target_cash_pos_for_interest]["payments"].append(sec_payment)
                 elif security_pos_key: # Other payments (e.g., Dividend) belong to the security
                      grouped_by_position[security_pos_key]["payments"].append(sec_payment)
                 else:
                      # This implies a payment was generated for a transaction with no symbol, and it's not Credit Interest.
                      print(f"Warning: sec_payment for action '{action}' but no security_pos_key (symbol_in_tx was empty?) for TX: {schwab_tx}")

            if cash_stock_mutation:
                 _cash_account_id_for_mutation = None
                 if depot == 'AWARDS':
                     if symbol_in_tx:
                         _cash_account_id_for_mutation = symbol_in_tx
                     else:
                         print(f"Warning: Cash mutation for AWARDS depot from TX with no Symbol: {schwab_tx}. Associating with non-specific cash account.")
                 
                 target_cash_pos_for_mutation = CashPosition(depot=depot, currentCy=default_cash_currency, cash_account_id=_cash_account_id_for_mutation)
                 if target_cash_pos_for_mutation not in grouped_by_position:
                      grouped_by_position[target_cash_pos_for_mutation] = {
                          "position": target_cash_pos_for_mutation,
                          "stocks": [], "payments": []
                      }
                 grouped_by_position[target_cash_pos_for_mutation]["stocks"].append(cash_stock_mutation)

        # --- Assemble final list (No more second pass) --- 
        processed_transactions = []
        for group_data in grouped_by_position.values():
            pos = group_data["position"]
            stocks = group_data["stocks"]
            payments_list = group_data["payments"]
            payments = payments_list if payments_list else None
            
            if stocks or payments:
                 processed_transactions.append(
                     (pos, stocks, payments, pos.depot, date_range)
                 )
        
        return processed_transactions if processed_transactions else None

    def _parse_schwab_decimal(self, value_str: Optional[str]) -> Optional[Decimal]:
        if value_str is None or value_str == "":
            return None
        try:
            # Remove $ and , before converting
            cleaned_value = value_str.replace('$', '').replace(',', '')
            return Decimal(cleaned_value)
        except InvalidOperation:
            print(f"Warning: Could not parse decimal from string: '{value_str}'")
            return None

    def _process_single_transaction(self, schwab_tx: dict, pos_object: Position) -> Tuple[Optional[SecurityStock], Optional[SecurityPayment], Optional[SecurityStock]]:
        """
        Processes a single Schwab transaction and returns the resulting objects:
        (security_stock, security_payment, cash_mutation_stock)
        - security_stock: Stock mutation for the primary security (if applicable)
        - security_payment: Payment event for the primary security (if applicable, e.g., Dividend)
                          OR Payment event for Cash Position (if Credit Interest)
        - cash_mutation_stock: Stock mutation representing the cash flow impact.
        """
        action = schwab_tx.get("Action", "").strip()
        tx_date_str = schwab_tx.get("Date")
        
        sec_stock: Optional[SecurityStock] = None
        sec_payment: Optional[SecurityPayment] = None
        cash_stock: Optional[SecurityStock] = None

        if not tx_date_str:
            print(f"Warning: Skipping transaction with no date: {schwab_tx}")
            return None, None, None # Return tuple of Nones
        
        # Date parsing logic
        actual_tx_date_str_part: str
        as_of_date_str_part: Optional[str] = None
        tx_date: Optional[date] = None 
        as_of_date_parsed: Optional[date] = None

        if " as of " in tx_date_str:
            parts = tx_date_str.split(" as of ", 1)
            actual_tx_date_str_part = parts[0].strip()
            if len(parts) > 1:
                as_of_date_str_part = parts[1].strip()
        else:
            actual_tx_date_str_part = tx_date_str.strip()
        
        try:
            tx_date = datetime.strptime(actual_tx_date_str_part, "%m/%d/%Y").date()
        except ValueError:
            print(f"Warning: Could not parse transaction date part: '{actual_tx_date_str_part}' from full string '{tx_date_str}' in {schwab_tx}")
            return None, None, None

        if as_of_date_str_part:
            try:
                as_of_date_parsed = datetime.strptime(as_of_date_str_part, "%m/%d/%Y").date()
                log_context_action = schwab_tx.get('Action', 'N/A')
                log_context_symbol = schwab_tx.get('Symbol', '')
                logger.debug(f"Extracted 'as of' date: {as_of_date_parsed} (transaction date: {tx_date}) from full string '{tx_date_str}' for action '{log_context_action}' symbol '{log_context_symbol}'.")
            except ValueError:
                print(f"Warning: Could not parse 'as of' date part: '{as_of_date_str_part}' from full string '{tx_date_str}' in {schwab_tx}")
                # as_of_date_parsed remains None, processing continues with tx_date

        schwab_qty = self._parse_schwab_decimal(schwab_tx.get("Quantity"))
        schwab_price = self._parse_schwab_decimal(schwab_tx.get("Price"))
        schwab_amount = self._parse_schwab_decimal(schwab_tx.get("Amount"))
        schwab_fees = self._parse_schwab_decimal(schwab_tx.get("Fees & Comm")) or self._parse_schwab_decimal(schwab_tx.get("FeesAndCommissions"))

        description = schwab_tx.get("Description", action)
        currency = "USD" # Assume USD

        # --- Handle specific actions --- 
        
        # Helper to create cash stock mutation
        def create_cash_stock(amount: Decimal, name: str) -> SecurityStock:
            return SecurityStock(
                referenceDate=tx_date,
                mutation=True,
                quotationType="PIECE", 
                quantity=amount, # Positive for inflow, negative for outflow
                balanceCurrency=currency, # Pass the string directly
                name=name,
                balance=amount # For cash, balance change equals quantity change
            )

        if action == "Buy" or action == "Reinvest Shares":
            if schwab_qty and schwab_qty > 0 and isinstance(pos_object, SecurityPosition):
                calculated_cost = None
                cash_flow = None
                if schwab_amount:
                    cash_flow = schwab_amount
                elif schwab_qty and schwab_price:
                    # This should actually never be the case, as we should have amount
                    calculated_cost = schwab_qty * schwab_price
                    cash_flow = -abs(calculated_cost)
                
                # TODO: Factor in schwab_fees into cost/cash_flow if needed

                sec_stock = SecurityStock(
                    referenceDate=tx_date, mutation=True, quotationType="PIECE", 
                    quantity=schwab_qty, balanceCurrency=currency, # Use currency string
                    unitPrice=schwab_price, name=action,
                )
                if cash_flow:
                     cash_stock = create_cash_stock(cash_flow, f"Cash out for {action} {pos_object.symbol}")

        elif action == "Sale":
             if schwab_qty and isinstance(pos_object, SecurityPosition):
                if schwab_qty < 0:
                    raise ValueError(f"Invalid negative quantity ({schwab_qty}) for 'Sale' action for symbol {pos_object.symbol}. Sales should have positive quantities representing shares sold.")
                
                # Quantity should be negative for a sale in our system
                final_qty = -schwab_qty 

                calculated_proceeds = None
                cash_flow = None
                abs_qty = abs(final_qty)
                if schwab_amount:
                    calculated_proceeds = schwab_amount
                    cash_flow = schwab_amount
                elif abs_qty and schwab_price:
                    # we should have amount
                    calculated_proceeds = abs_qty * schwab_price
                    cash_flow = abs(calculated_proceeds)
                
                # TODO: Factor in schwab_fees into proceeds/cash_flow if needed

                sec_stock = SecurityStock(
                    referenceDate=tx_date, mutation=True, quotationType="PIECE",
                    quantity=final_qty, balanceCurrency=currency, # Use currency string
                    unitPrice=schwab_price, name="Sale",
                )
                if cash_flow:
                     cash_stock = create_cash_stock(cash_flow, f"Cash in for Sale {pos_object.symbol}")

        elif action == "Credit Interest":
            # Generates a Payment for the cash account AND a cash stock mutation
            if schwab_amount and schwab_amount > 0:
                # Payment record (will be associated with CashPosition by caller)
                sec_payment = SecurityPayment(
                    paymentDate=tx_date, quotationType="PIECE", 
                    quantity=UNINITIALIZED_QUANTITY, amountCurrency=currency, # Use currency string
                    amount=schwab_amount, name="Credit Interest",
                    grossRevenueB=schwab_amount,
                    broker_label_original=action,
                )
                # Cash stock mutation
                cash_stock = create_cash_stock(schwab_amount, f"Cash in for Credit Interest")

        elif action == "Dividend" or action == "Reinvest Dividend":
            if schwab_amount and schwab_amount > 0 and isinstance(pos_object, SecurityPosition):
                if schwab_qty is not None and schwab_qty != Decimal(0):
                    print(f"Warning: Ignoring non-zero quantity ({schwab_qty}) for action '{action}' on symbol {pos_object.symbol}. Payment quantity will be uninitialized.")
                payment_quantity = UNINITIALIZED_QUANTITY
                sec_payment = SecurityPayment(
                    paymentDate=tx_date, quotationType="PIECE",
                    quantity=payment_quantity, amountCurrency=currency, # Use currency string
                    amount=schwab_amount, name="Dividend",
                    grossRevenueB=schwab_amount,
                    broker_label_original=action,
                    # TODO: Withholding tax check might generate cash_stock here later
                )
                cash_stock = create_cash_stock(schwab_amount, f"Cash in for Dividend {pos_object.symbol}")
            else:
                raise ValueError(f"Dividend action requires a positive amount and a valid SecurityPosition. Amount: {schwab_amount}, Position: {pos_object}")
                
        elif action == "Stock Split":
            if schwab_qty and schwab_qty != 0 and isinstance(pos_object, SecurityPosition):
                # TODOD: Format date string in swiss format
                if as_of_date_parsed:
                    name=f"Stock Split (As of {as_of_date_parsed})"
                else:
                    name="Stock Split"
                sec_stock = SecurityStock(
                    # TODO format date string in swiss format
                    referenceDate=tx_date, mutation=True, quotationType="PIECE",
                    quantity=schwab_qty, balanceCurrency=currency, # Use currency string
                    name=name
                )
        
        elif action == "Deposit": # Shares deposited into account
            if schwab_qty and schwab_qty > 0 and isinstance(pos_object, SecurityPosition):
                award_details_str = ""
                vest_fmv_decimal = None
                if "TransactionDetails" in schwab_tx and schwab_tx["TransactionDetails"]:
                    details = schwab_tx["TransactionDetails"][0].get("Details", {})
                    award_date = details.get("AwardDate")
                    award_id = details.get("AwardId")
                    vest_date = details.get("VestDate")
                    fmv = details.get("VestFairMarketValue")
                    award_details_str = f" (Award ID: {award_id}, Award Date: {award_date}, Vest Date: {vest_date}, FMV: {fmv})"
                    vest_fmv_decimal = self._parse_schwab_decimal(fmv)

                calculated_balance_deposit = None
                cash_flow = None
                if schwab_qty and vest_fmv_decimal:
                    calculated_balance_deposit = schwab_qty * vest_fmv_decimal
                    # Assumption: Deposit/Vesting implies value received, treat as cash OUT if we consider cost basis?
                    # Or is it just shares appearing with no cash flow in this account? Let's assume NO cash flow for now.
                    # cash_flow = -abs(calculated_balance_deposit)
                
                sec_stock = SecurityStock(
                    referenceDate=tx_date, mutation=True, quotationType="PIECE",
                    quantity=schwab_qty, balanceCurrency=currency, # Use currency string
                    unitPrice=vest_fmv_decimal, name=f"Deposit{award_details_str}",
                )
                # if cash_flow:
                #     cash_stock = create_cash_stock(cash_flow, f"Implied cash out for Deposit {pos_object.symbol}")
        
        elif action == "Tax Withholding" or action == "NRA Tax Adj":
            # Creates a Payment for the security AND a cash stock mutation
            if schwab_amount and schwab_amount != 0:
                sec_payment = SecurityPayment(
                    paymentDate=tx_date, quotationType="PIECE",
                    quantity=UNINITIALIZED_QUANTITY, amountCurrency=currency, # Use currency string
                    amount=schwab_amount, name=f"{action}",
                    nonRecoverableTax=abs(schwab_amount) if schwab_amount < 0 else None,
                    grossRevenueB=schwab_amount if schwab_amount > 0 else None,
                    broker_label_original=action,
                    nonRecoverableTaxAmountOriginal=abs(schwab_amount) if schwab_amount < 0 else None,
                )
                # Cash stock reflects the actual cash movement
                cash_stock = create_cash_stock(schwab_amount, f"Cash flow for {action} {pos_object.symbol if isinstance(pos_object, SecurityPosition) else 'Cash'}")

        elif action == "Cash In Lieu":
             if schwab_amount and schwab_amount > 0:
                # Assume Cash in Lieue are from stock splits and capital events
                # so they are income neutral, e.g. no taxable event
                # sec_payment = SecurityPayment(
                #     paymentDate=tx_date, quotationType="PIECE", 
                #     quantity=Decimal("1"), amountCurrency=currency, # Use currency string
                #     amount=schwab_amount, name="Cash In Lieu",
                #     grossRevenueB=schwab_amount
                # )
                cash_stock = create_cash_stock(schwab_amount, f"Cash in for Cash In Lieu {pos_object.symbol if isinstance(pos_object, SecurityPosition) else 'Cash'}")

        elif action == "Journal":
            if schwab_qty and pos_object.type == "security": # Security journal
                # Assume no cash impact unless Amount/Price present and non-zero?
                cash_flow = None
                calculated_value = None
                if schwab_amount and schwab_amount != 0:
                     calculated_value = schwab_amount
                     # If qty > 0 (in), cash is out? If qty < 0 (out), cash is in?
                     cash_flow = -schwab_amount if schwab_qty > 0 else abs(schwab_amount) 
                     
                sec_stock = SecurityStock(
                    referenceDate=tx_date, mutation=True, quotationType="PIECE",
                    quantity=schwab_qty, balanceCurrency=currency, # Use currency string
                    name="Journal (Shares)"
                )
                if cash_flow:
                     cash_stock = create_cash_stock(cash_flow, f"Cash flow for Journal {pos_object.symbol}")

            elif schwab_amount: # Cash journal
                 # Just generate cash stock mutation
                 cash_stock = create_cash_stock(schwab_amount, "Cash Journal")

        elif action == "Wire Transfer":
            if schwab_amount:
                cash_stock = create_cash_stock(schwab_amount, f"Wire Transfer{' ' + pos_object.symbol if isinstance(pos_object, SecurityPosition) else ''}")

        elif action == "Transfer":
            if schwab_qty and schwab_tx.get("Symbol") and isinstance(pos_object, SecurityPosition): # Share transfer
                # No cash flow for transfer
                assert not schwab_amount
                assert schwab_qty > 0

                sec_stock = SecurityStock(
                    referenceDate=tx_date, mutation=True, quotationType="PIECE",
                    quantity=-schwab_qty, balanceCurrency=currency, # Use currency string
                    unitPrice=schwab_price, name="Transfer (Shares)",
                )

            elif schwab_amount and not schwab_tx.get("Symbol") and isinstance(pos_object, CashPosition): # Cash transfer
                  cash_stock = create_cash_stock(schwab_amount, "Cash Transfer")
        elif action in KNOWN_ACTIONS:
            raise InvalidOperation('Unhandled action in _process_single_transaction', action)
        elif pos_object.type == "security":
            raise ValueError(f"Unknown action '{action}' for security position: {schwab_tx}")
        elif pos_object.type != "cash":
            raise InvalidOperation("Unhandled position type", pos_object.type)
        else:
            if not schwab_amount:
                raise ValueError(f"Unknown action '{action}' for cash position with no amount: {schwab_tx}") 
            # This is a cash position with an unknown action, which we can recover from
            # Assume the amount is always representing the cash balance change
            cash_stock = create_cash_stock(schwab_amount, f"Cash flow for {action} {description}")

        # Fees are ignored for now in cash flow calculation
        if schwab_amount and schwab_amount != 0:
            assert cash_stock is not None, f"Cash stock mutation should be generated for action '{action}' with amount {schwab_amount} in transaction: {schwab_tx}"
            assert cash_stock.quantity == schwab_amount, f"Cash stock quantity should match the amount in transaction: {schwab_tx}"
        # Ensure that for any known action, at least one type of record is generated.
        # If not, it indicates an unhandled case or data combination for that action.
        # The KNOWN_ACTIONS check in the calling _extract_transactions_from_dict method
        # should mean this function is only called for actions in KNOWN_ACTIONS.
        if sec_stock is None and sec_payment is None and cash_stock is None:
            raise ValueError(
                f"Known transaction action '{action}' for position context '{pos_object}' with data {schwab_tx} "
                f"did not result in any security stock, security payment, or cash stock mutation. "
                f"This indicates an unhandled data combination or a logic gap for this action."
            )
        return sec_stock, sec_payment, cash_stock