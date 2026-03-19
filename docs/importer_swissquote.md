# Swissquote Importer Guide

This guide explains how to prepare your data from [Swissquote Bank](https://www.swissquote.ch/) for use with OpenSteuerAuszug.

## Required Input: Transaction CSV Export

OpenSteuerAuszug processes Swissquote data using the **transaction history CSV export** from the Swissquote web interface.

### How to Obtain the CSV Export:

1. **Log in** to your Swissquote account at [trade.swissquote.ch](https://trade.swissquote.ch/).
2. Go to **"My Account" → "Settings" → "Display Language"** and set the language to **Deutsch**. This is important — the importer expects German column names and transaction type labels.
3. Navigate to **"My Account" → "Transactions"**.
4. Set the **date range** to cover your full holding history — not just the tax year. Start from the date you first bought any security you still hold. This ensures correct opening balances are computed for the tax year.
5. Click **"Export CSV"** to download the file.

### CSV Format

The export uses a **semicolon delimiter** and **Windows-1252 (cp1252) encoding**. The importer handles both tab- and semicolon-separated files automatically.

Expected columns:

```
Datum; Auftrag #; Transaktionen; Symbol; Name; ISIN; Anzahl; Stückpreis;
Kosten; Aufgelaufene Zinsen; Nettobetrag; Währung Nettobetrag;
Nettobetrag in der Währung des Kontos; Saldo; Währung
```

## Configuration (`config.toml`)

The Swissquote importer requires a `config.toml` with at minimum:

```toml
[general]
full_name = "Vorname Nachname"
canton = "ZH"
```

Replace `ZH` with your canton abbreviation and set your full name. This information appears on the generated Steuerauszug. The config file is located at:

- **Windows**: `%LOCALAPPDATA%\opensteuerauszug\opensteuerauszug\config.toml`
- **Linux/macOS**: `~/.config/opensteuerauszug/config.toml`

Copy `config.template.toml` from the repo as a starting point.

Optionally, add a Swissquote account section to set your depot number:

```toml
[[accounts]]
kind = "swissquote"
account_number = "1234567"
broker_name = "swissquote"
account_name_alias = "Swissquote"
full_name = "Vorname Nachname"
canton = "ZH"
```

## Running OpenSteuerAuszug

```console
opensteuerauszug process --importer swissquote <path/to/transactions.csv> --tax-year 2025
```

For example:

```console
python -m opensteuerauszug.steuerauszug \
    --importer swissquote transactions_history.csv \
    --tax-year 2025 \
    --output Steuerauszug_2025.pdf \
    --xml-output Steuerauszug_2025.xml
```

## Supported Transaction Types

The following German transaction labels from the Swissquote export are supported:

| Swissquote label | Type |
|---|---|
| Kauf | Buy |
| Verkauf | Sell |
| Dividende | Cash dividend |
| Stockdividende | Stock dividend |
| Capital Gain | Capital gain distribution |
| Wertpapierleihe | Securities lending income |
| Verrechnungssteuer | Swiss withholding tax (35%) |
| Quellensteuer | Foreign withholding tax |
| Zinsen auf Einlagen | Credit interest |
| Zinsen auf Belastungen | Debit interest (margin) |
| Rückzahlung | Bond / product redemption |
| Depotgebühren | Custody fee |
| Berichtigung Börsengeb. | Exchange fee correction |
| Spesen Steuerauszug | Tax statement fee |
| Forex-Belastung / Forex-Gutschrift | FX conversion |
| Fx-Belastung Comp. / Fx-Gutschrift Comp. | FX compound conversion |
| Auszahlung / Einzahlung | Cash withdrawal / deposit |
| Twint | TWINT payment |
| Zahlung | Generic payment |
| Interne Titelumbuchung | Internal security transfer |
| Reverse Split | Reverse stock split |
| Fusion | Merger |
| Ausgabe von Anrechten | Rights issue |
| Vorrechtszeichungsangebot | Pre-emptive rights offer |
| Crypto Deposit | Cryptocurrency deposit |

If an unknown transaction type appears in your export, the importer will log a warning and skip the row. Add the label to `TRANSACTION_TYPE_MAP` in `swissquote_importer.py` to handle it.

## Importer Specifics & Known Limitations

- **Single-currency account assumed**: The importer assumes `Währung Nettobetrag` always equals `Währung` (i.e. a CHF account). Multi-currency FX rate handling is not implemented.

- **Full history export recommended**: To get correct opening balances for the tax year, export your full transaction history back to the first purchase of any security you still hold. If only the tax year is exported, all opening balances will be zero which leads to negative closing balances for positions held before the year started.

- **Securities lending without ISIN**: `Wertpapierleihe` rows with no ISIN are skipped. Add this income manually in your tax software as interest income.

- **Withholding tax**: Swissquote does not emit separate `Verrechnungssteuer` rows for Swiss securities — the dividend is already net. The Kursliste calculator will compute the gross amount and withholding tax claim automatically from the Kursliste data.

- **Delisted securities**: Securities not found in the Kursliste (e.g. Credit Suisse, Meyer Burger, BTC, ETH) will show `n.v.` tax value. Set these to 0 manually in your tax software.

- **CALIDA split warning**: The Kursliste may warn about a missing stock split mutation for CALIDA N (CH0126639464). This is a known data gap — verify the position manually.

## Troubleshooting

- **`UnicodeDecodeError`**: The CSV was exported with a language setting other than Deutsch, or saved in a different encoding. Re-export with the display language set to Deutsch.

- **All positions show zero or negative balances**: You exported only the current tax year. Re-export the full history going back to your first purchase.

- **Unknown transaction type warning**: A new transaction type appeared in your export. Add it to `TRANSACTION_TYPE_MAP` in `swissquote_importer.py` and open a GitHub issue or PR with the new label.

- **Canton not set error**: Your `config.toml` is missing or has no `canton` field. See the Configuration section above.

---
Return to [User Guide](user_guide.md)
