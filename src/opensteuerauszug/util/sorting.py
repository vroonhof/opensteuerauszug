import bisect
import datetime
from typing import List
from opensteuerauszug.model.ech0196 import SecurityPayment, SecurityStock, BankAccountPayment

def sort_security_stocks(stocks: List[SecurityStock]) -> List[SecurityStock]:
    """
    Sorts stock events primarily by referenceDate and secondarily by mutation status.
    Balances (mutation=False) precede mutations (mutation=True) for the same date.
    This is a stable sort.
    """
    return sorted(stocks, key=lambda s: (s.referenceDate, s.mutation))

def find_index_of_date(date: datetime.date, sorted_stocks: List[SecurityStock]) -> int:
    """
    Finds the index of the first stock event with a referenceDate greater than or equal to the given date.
    Returns len(stocks) if no such event is found.
    """
    return bisect.bisect_left(sorted_stocks, date, key=lambda s: s.referenceDate)

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
