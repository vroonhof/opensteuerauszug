# DEGIRO German export with cash in two currencies

Reduced real-world DEGIRO export (account language German, year-end 2025)
contributed in https://github.com/vroonhof/opensteuerauszug/issues/396 /
https://github.com/vroonhof/opensteuerauszug/pull/420#issuecomment-5554145930.

The reporter kept the header and row structure of the real `Portfolio.csv`
but replaced the amounts for privacy and omitted the securities, leaving the
two `CASH & CASH FUND & FTX CASH (<currency>)` rows that motivate the fix:
before it, only the last cash row of `Portfolio.csv` survived the import and
the CHF balance was silently dropped.

`Account.csv` is not part of the original report; it was written by hand to be
consistent with the portfolio snapshot (a CHF deposit followed by a CHF -> USD
conversion leaving CHF 500.00 and USD 200.00) so the directory can be imported
as a whole.
