from typing import List
from opensteuerauszug.model.ech0196 import SecurityPayment, SecurityStock, BankAccountPayment

def sort_security_stocks(stocks: List[SecurityStock]) -> List[SecurityStock]:
    """
    Sorts stock events primarily by referenceDate and secondarily by mutation status.
    Balances (mutation=False) precede mutations (mutation=True) for the same date.
    This is a stable sort.
    """
    return sorted(stocks, key=lambda s: (s.referenceDate, s.mutation))

def sort_payments(payments: List[BankAccountPayment]) -> List[BankAccountPayment]:
    """
    Sorts payment events by paymentDate.
    This is a stable sort.
    """
    return sorted(payments, key=lambda p: p.paymentDate)

def sort_security_payments(payments: List[SecurityPayment]) -> List[SecurityPayment]:
    """
    Sorts security payment events by paymentDate.
    This is a stable sort.
    """
    return sorted(payments, key=lambda p: p.paymentDate)
