from datetime import date
from decimal import Decimal
from pathlib import Path

from opensteuerauszug.config.models import FidelityAccountSettings
from opensteuerauszug.importers.fidelity.fidelity_importer import FidelityImporter

STATEMENT_HEADER = (
    "Account Type,Account,Beginning mkt Value,Change in Investment,"
    "Ending mkt Value,Short Balance,Ending Net Value,Dividends This Period,"
    "Dividends Year to Date,Interest This Year,Interest Year to Date,"
    "Total This Period,Total Year to Date\n"
)
POSITIONS_HEADER = (
    "Symbol/CUSIP,Description,Quantity,Price,Beginning Value,Ending Value,Cost Basis\n"
)
TRANSACTIONS_HEADER = (
    "Run Date,Account,Account Number,Action,Symbol,Description,Type,"
    "Price ($),Quantity,Commission ($),Fees ($),Accrued Interest ($),"
    "Amount ($),Settlement Date\n"
)


def _write_statement(
    directory: Path,
    filename: str,
    *,
    account: str = "U12349876",
    ending_mkt_value: str = "1000.00",
    ending_net_value: str = "1250.00",
    position_rows: list[str],
) -> Path:
    path = directory / filename
    content = (
        STATEMENT_HEADER
        + f"My Fidelity Account,{account},0.,0.,{ending_mkt_value},,{ending_net_value},0.,0.,0.,0.,0.,0.\n"
        + "\n"
        + POSITIONS_HEADER
        + f"{account}\n"
        + "Stocks\n"
        + "".join(f"{row}\n" for row in position_rows)
    )
    path.write_text(content, encoding="us-ascii")
    return path


def _write_transactions(directory: Path, rows: list[str]) -> Path:
    path = directory / "Accounts_History.csv"
    content = TRANSACTIONS_HEADER + "".join(f"{row}\n" for row in rows) + "\n"
    path.write_text(content, encoding="us-ascii")
    return path


def test_synthetic_opening_and_closing_balances_use_fidelity_labels(tmp_path: Path):
    # AAPL held at year-end (100 shares) with 40 bought during the year -> synthetic opening of 60.
    # MSFT bought and sold completely during the year -> synthetic closing of 0.
    stmt_file = _write_statement(
        tmp_path,
        "Statement12312025.csv",
        position_rows=[
            "AAPL,APPLE INC,100.00000,200.00000,12000.00,20000.00,15000.00",
        ],
    )
    tx_file = _write_transactions(
        tmp_path,
        rows=[
            '06/15/2025,"My Fidelity Account","U12349876","YOU BOUGHT APPLE INC (AAPL) (Cash)",AAPL,"APPLE INC",Cash,180.00,40,,,,-7200.00,06/16/2025',
            '03/10/2025,"My Fidelity Account","U12349876","YOU BOUGHT MICROSOFT CORP (MSFT) (Cash)",MSFT,"MICROSOFT CORP",Cash,250.00,20,,,,-5000.00,03/11/2025',
            '09/10/2025,"My Fidelity Account","U12349876","YOU SOLD MICROSOFT CORP (MSFT) (Cash)",MSFT,"MICROSOFT CORP",Cash,300.00,-20,,,,6000.00,09/11/2025',
        ],
    )

    importer = FidelityImporter(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        account_settings_list=[],
    )
    statement = importer.import_files([str(stmt_file), str(tx_file)])

    assert statement.listOfSecurities is not None
    (depot,) = statement.listOfSecurities.depot
    by_symbol = {sec.symbol: sec for sec in depot.security}

    aapl_opening = [
        s for s in by_symbol["AAPL"].stock if not s.mutation and s.referenceDate == date(2025, 1, 1)
    ]
    assert len(aapl_opening) == 1
    assert aapl_opening[0].quantity == Decimal("60")
    assert aapl_opening[0].name == "Opening balance"

    msft_closing = [
        s for s in by_symbol["MSFT"].stock if not s.mutation and s.referenceDate == date(2026, 1, 1)
    ]
    assert len(msft_closing) == 1
    assert msft_closing[0].quantity == Decimal("0")
    assert msft_closing[0].name == "Closing balance"


def test_latest_statement_summary_wins_for_closing_cash_balance_and_folds_payments(
    tmp_path: Path,
):
    early_stmt = _write_statement(
        tmp_path,
        "Statement06302025.csv",
        ending_mkt_value="1000.00",
        ending_net_value="1100.00",
        position_rows=[
            "VT,VANGUARD INTL EQUITY INDEX FDS TT WRLD ST ETF,10.00000,100.00000,1000.00,1000.00,1000.00",
        ],
    )
    late_stmt = _write_statement(
        tmp_path,
        "Statement12312025.csv",
        ending_mkt_value="1000.00",
        ending_net_value="1350.00",
        position_rows=[
            "VT,VANGUARD INTL EQUITY INDEX FDS TT WRLD ST ETF,10.00000,100.00000,1000.00,1000.00,1000.00",
        ],
    )
    tx_file = _write_transactions(
        tmp_path,
        rows=[
            '12/31/2025,"My Fidelity Account","U12349876","INTEREST EARNED as of Dec-30-2025 (Cash)",,"No Description",Cash,,0.000,,,,1.25,',
        ],
    )

    importer = FidelityImporter(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        account_settings_list=[],
    )
    statement = importer.import_files([str(late_stmt), str(early_stmt), str(tx_file)])

    assert statement.listOfBankAccounts is not None
    (bank_account,) = statement.listOfBankAccounts.bankAccount
    assert bank_account.bankAccountName == "U12349876 USD position"
    assert bank_account.bankAccountNumber == "U12349876-USD"
    assert bank_account.taxValue is not None
    assert bank_account.taxValue.balance == Decimal("350.00")
    assert len(bank_account.payment) == 1
    assert bank_account.payment[0].amount == Decimal("1.25")


def test_client_and_canton_resolved_from_account_settings(tmp_path: Path):
    stmt_file = _write_statement(
        tmp_path,
        "Statement12312025.csv",
        position_rows=[
            "VT,VANGUARD INTL EQUITY INDEX FDS TT WRLD ST ETF,10.00000,100.00000,1000.00,1000.00,1000.00",
        ],
    )
    settings = FidelityAccountSettings(
        broker_name="fidelity",
        account_number="U12349876",
        account_name_alias="Fidelity Main",
        full_name="Jane Doe",
        canton="ZH",
    )

    importer = FidelityImporter(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        account_settings_list=[settings],
    )
    statement = importer.import_files([str(stmt_file)])

    assert statement.canton == "ZH"
    assert statement.client is not None
    assert len(statement.client) == 1
    assert statement.client[0].clientNumber == "U12349876"
    assert statement.client[0].firstName == "Jane"
    assert statement.client[0].lastName == "Doe"
