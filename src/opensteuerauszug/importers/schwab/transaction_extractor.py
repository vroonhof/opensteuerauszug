import json
from typing import List, Optional, Tuple, Any, Annotated
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from opensteuerauszug.model.position import Position, SecurityPosition, CashPosition
from opensteuerauszug.model.ech0196 import SecurityStock, SecurityPayment, CurrencyId, QuotationType

# Known actions from formats.md
KNOWN_ACTIONS = {
    "Buy", "Cash In Lieu", "Credit Interest", "Deposit", "Dividend", "Journal",
    "NRA Tax Adj", "Reinvest Dividend", "Reinvest Shares", "Sale", "Stock Split",
    "Tax Withholding", "Transfer"
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
        grouped_by_position: dict[str, dict[str, Any]] = {}
        default_cash_currency = "USD" # Assume USD for Schwab cash

        for schwab_tx in raw_transactions:
            action = schwab_tx.get("Action", "").strip()
            if not action or action not in KNOWN_ACTIONS:
                # Skip or raise error (already handled in _process_single_transaction theoretically)
                continue 

            symbol = schwab_tx.get("Symbol", "").strip()
            group_key = symbol if symbol else "__CASH__"
            is_cash_only_txn = not symbol

            # Ensure the group exists
            if group_key not in grouped_by_position:
                pos: Position
                if symbol:
                    desc = schwab_tx.get("Description")
                    if not desc or desc == symbol: desc = None
                    pos = SecurityPosition(depot=depot, symbol=symbol, description=desc)
                else:
                    pos = CashPosition(depot=depot, currentCy=default_cash_currency)
                
                grouped_by_position[group_key] = {"position": pos, "stocks": [], "payments": []}
            
            # Get the position object for context
            current_pos_object = grouped_by_position[group_key]["position"]

            # Process the transaction
            sec_stock, sec_payment, cash_stock = self._process_single_transaction(schwab_tx, current_pos_object)

            # Assign results to appropriate lists
            if sec_stock:
                 if not is_cash_only_txn: # Add to security's stock list
                      grouped_by_position[group_key]["stocks"].append(sec_stock)
                 # else: Should not happen - sec_stock generated only if symbol exists?
                      
            if sec_payment:
                 if action == "Credit Interest": # Special case: payment belongs to cash account
                     # Ensure cash group exists
                     if "__CASH__" not in grouped_by_position:
                         grouped_by_position["__CASH__"] = {
                             "position": CashPosition(depot=depot, currentCy=default_cash_currency),
                             "stocks": [], "payments": []
                         }
                     grouped_by_position["__CASH__"]["payments"].append(sec_payment)
                 elif not is_cash_only_txn: # Add to security's payment list
                      grouped_by_position[group_key]["payments"].append(sec_payment)
                 # else: Payment generated without symbol? Error?

            if cash_stock:
                 # Ensure cash group exists
                 if "__CASH__" not in grouped_by_position:
                      grouped_by_position["__CASH__"] = {
                          "position": CashPosition(depot=depot, currentCy=default_cash_currency),
                          "stocks": [], "payments": []
                      }
                 grouped_by_position["__CASH__"]["stocks"].append(cash_stock)

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
        
        try:
            tx_date = datetime.strptime(tx_date_str, "%m/%d/%Y").date()
        except ValueError:
            print(f"Warning: Could not parse transaction date: '{tx_date_str}' in {schwab_tx}")
            return None, None, None

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

        if action == "Buy":
            if schwab_qty and schwab_qty > 0 and isinstance(pos_object, SecurityPosition):
                calculated_cost = None
                cash_flow = None
                if schwab_amount:
                    calculated_cost = schwab_amount # Amount likely includes price*qty + maybe fees?
                    cash_flow = -abs(schwab_amount)
                elif schwab_qty and schwab_price:
                    calculated_cost = schwab_qty * schwab_price
                    cash_flow = -abs(calculated_cost)
                
                # TODO: Factor in schwab_fees into cost/cash_flow if needed

                sec_stock = SecurityStock(
                    referenceDate=tx_date, mutation=True, quotationType="PIECE", 
                    quantity=schwab_qty, balanceCurrency=currency, # Use currency string
                    unitPrice=schwab_price, name=f"Buy: {description}",
                    balance=calculated_cost 
                )
                if cash_flow:
                     cash_stock = create_cash_stock(cash_flow, f"Cash out for Buy {pos_object.symbol}")

        elif action == "Sale":
             if schwab_qty and isinstance(pos_object, SecurityPosition):
                sale_qty = Decimal(0)
                if schwab_qty < 0: # Handle negative quantity case (with warning)
                    symbol_for_warning = pos_object.symbol
                    print(f"Warning: Received negative quantity ({schwab_qty}) for 'Sale' action for symbol {symbol_for_warning}. Proceeding with it as a sale.")
                    sale_qty = schwab_qty # Keep negative for stock mutation
                elif schwab_qty > 0:
                    sale_qty = -schwab_qty # Convert positive JSON quantity to negative for mutation

                if sale_qty != 0:
                    calculated_proceeds = None
                    cash_flow = None
                    abs_qty = abs(sale_qty)
                    if schwab_amount:
                        calculated_proceeds = schwab_amount
                        cash_flow = abs(schwab_amount)
                    elif abs_qty and schwab_price:
                        calculated_proceeds = abs_qty * schwab_price
                        cash_flow = abs(calculated_proceeds)
                    
                    # TODO: Factor in schwab_fees into proceeds/cash_flow if needed

                    sec_stock = SecurityStock(
                        referenceDate=tx_date, mutation=True, quotationType="PIECE",
                        quantity=sale_qty, balanceCurrency=currency, # Use currency string
                        unitPrice=schwab_price, name=f"Sale: {description}",
                        balance=calculated_proceeds
                    )
                    if cash_flow:
                         cash_stock = create_cash_stock(cash_flow, f"Cash in for Sale {pos_object.symbol}")

        elif action == "Credit Interest":
            # Generates a Payment for the cash account AND a cash stock mutation
            if schwab_amount and schwab_amount > 0:
                # Payment record (will be associated with CashPosition by caller)
                sec_payment = SecurityPayment(
                    paymentDate=tx_date, quotationType="PIECE", 
                    quantity=Decimal("1"), amountCurrency=currency, # Use currency string
                    amount=schwab_amount, name=f"Credit Interest: {description}",
                    grossRevenueB=schwab_amount
                )
                # Cash stock mutation
                cash_stock = create_cash_stock(schwab_amount, f"Cash in for Credit Interest")

        elif action == "Dividend":
             # Generates only a Payment record for the security
             if schwab_amount and schwab_amount > 0 and isinstance(pos_object, SecurityPosition):
                payment_quantity = schwab_qty if schwab_qty and schwab_qty != Decimal(0) else Decimal("1")
                sec_payment = SecurityPayment(
                    paymentDate=tx_date, quotationType="PIECE",
                    quantity=payment_quantity, amountCurrency=currency, # Use currency string
                    amount=schwab_amount, name=f"Dividend: {description}",
                    grossRevenueB=schwab_amount
                    # TODO: Withholding tax check might generate cash_stock here later
                )
        
        elif action == "Reinvest Dividend" or action == "Reinvest Shares":
            # Generates a Payment (dividend) and a Stock (acquisition) for the security.
            # Net cash impact within this action is assumed zero (or handled by fees later).
             if isinstance(pos_object, SecurityPosition):
                # 1. Dividend Payment part
                if schwab_amount and schwab_amount > 0:
                    payment_quantity = schwab_qty if schwab_qty and schwab_qty != Decimal(0) else Decimal("1") 
                    sec_payment = SecurityPayment(
                        paymentDate=tx_date, quotationType="PIECE",
                        quantity=payment_quantity, amountCurrency=currency, # Use currency string
                        amount=schwab_amount, name=f"{action} (Payment): {description}",
                        grossRevenueB=schwab_amount
                    )
                # 2. Share Acquisition part
                if schwab_qty and schwab_qty > 0:
                    unit_price_reinvest = schwab_price # Prioritize explicit price first
                    if not unit_price_reinvest and schwab_amount and schwab_qty != Decimal(0):
                        unit_price_reinvest = schwab_amount / schwab_qty
                    
                    calculated_balance_reinvest = schwab_amount # Amount usually represents the total value
                    if not calculated_balance_reinvest and schwab_qty and unit_price_reinvest:
                        calculated_balance_reinvest = schwab_qty * unit_price_reinvest
                    
                    sec_stock = SecurityStock(
                        referenceDate=tx_date, mutation=True, quotationType="PIECE",
                        quantity=schwab_qty, balanceCurrency=currency, # Use currency string
                        unitPrice=unit_price_reinvest, name=f"{action} (Acquisition): {description}",
                        balance=calculated_balance_reinvest
                    )
                    # No separate cash_stock here - the two legs (payment + stock) balance out cash-wise.
        
        elif action == "Stock Split":
            if schwab_qty and schwab_qty != 0 and isinstance(pos_object, SecurityPosition):
                sec_stock = SecurityStock(
                    referenceDate=tx_date, mutation=True, quotationType="PIECE",
                    quantity=schwab_qty, balanceCurrency=currency, # Use currency string
                    name=f"Stock Split: {description}"
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
                    unitPrice=vest_fmv_decimal, name=f"Deposit: {description}{award_details_str}",
                    balance=calculated_balance_deposit
                )
                # if cash_flow:
                #     cash_stock = create_cash_stock(cash_flow, f"Implied cash out for Deposit {pos_object.symbol}")
        
        elif action == "Tax Withholding" or action == "NRA Tax Adj":
            # Creates a Payment for the security AND a cash stock mutation
            if schwab_amount and schwab_amount != 0:
                sec_payment = SecurityPayment(
                    paymentDate=tx_date, quotationType="PIECE",
                    quantity=Decimal("1"), amountCurrency=currency, # Use currency string
                    amount=schwab_amount, name=f"{action}: {description}",
                    nonRecoverableTax=abs(schwab_amount) if schwab_amount < 0 else None,
                    grossRevenueB=schwab_amount if schwab_amount > 0 else None
                )
                # Cash stock reflects the actual cash movement
                cash_stock = create_cash_stock(schwab_amount, f"Cash flow for {action} {pos_object.symbol if isinstance(pos_object, SecurityPosition) else 'Cash'}")

        elif action == "Cash In Lieu":
            # Creates a Payment for the security AND a cash stock mutation
             if schwab_amount and schwab_amount > 0:
                sec_payment = SecurityPayment(
                    paymentDate=tx_date, quotationType="PIECE", 
                    quantity=Decimal("1"), amountCurrency=currency, # Use currency string
                    amount=schwab_amount, name=f"Cash In Lieu: {description}",
                    grossRevenueB=schwab_amount
                )
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
                elif schwab_qty and schwab_price and schwab_price !=0:
                     calculated_value = schwab_qty * schwab_price
                     cash_flow = -calculated_value if schwab_qty > 0 else abs(calculated_value)
                     
                sec_stock = SecurityStock(
                    referenceDate=tx_date, mutation=True, quotationType="PIECE",
                    quantity=schwab_qty, balanceCurrency=currency, # Use currency string
                    name=f"Journal (Shares): {description}", balance=calculated_value # Add value if known
                )
                if cash_flow:
                     cash_stock = create_cash_stock(cash_flow, f"Cash flow for Journal {pos_object.symbol}")

            elif schwab_amount and pos_object.type == "cash": # Cash journal
                 # Just generate cash stock mutation
                 cash_stock = create_cash_stock(schwab_amount, f"Cash Journal: {description}")

        elif action == "Transfer":
            if schwab_qty and schwab_tx.get("Symbol") and isinstance(pos_object, SecurityPosition): # Share transfer
                # No cash flow for transfer
                assert not schwab_amount
                assert schwab_qty > 0

                sec_stock = SecurityStock(
                    referenceDate=tx_date, mutation=True, quotationType="PIECE",
                    quantity=schwab_qty, balanceCurrency=currency, # Use currency string
                    unitPrice=schwab_price, name=f"Transfer (Shares): {description}",
                )

            elif schwab_amount and not schwab_tx.get("Symbol") and isinstance(pos_object, CashPosition): # Cash transfer
                  cash_stock = create_cash_stock(schwab_amount, f"Cash Transfer: {description}")

        # Fees are ignored for now in cash flow calculation

        return sec_stock, sec_payment, cash_stock 