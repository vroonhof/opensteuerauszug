"""English translations for PDF rendering."""

TRANSLATIONS = {
    # === DOCUMENT METADATA ===
    "created_with": "created with OpenSteuerauszug",
    "converted_with": "converted with OpenSteuerauszug",
    "taxstatement": "tax statement",

    # === PAGE STRUCTURE ===
    "page": "page {page} of {total}",

    # === CLIENT INFORMATION ===
    "client": "Client",
    "client_number": "Ctno.",
    "male": "Mr.",
    "female": "Mrs.",
    "address": "Address",
    "canton": "Canton",
    "period": "Period",
    "portfolio": "Ctno.",
    "created_at": "Created on",

    # === SECTION TITLES ===
    "summary": "Overview",
    "bank_accounts": "Bank accounts",
    "a_values_with_vst": "A-Values with withholding tax",
    "b_values_without_vst": "B-Values without withholding tax",
    "values_with_da1_usa": "Values with recognition of foreign withholding tax / tax deduction USA",
    "liabilities": "Debts",
    "liabilities_title": "Liabilities",
    "reconciliation_kursliste_broker": "Kursliste / broker payments reconciliation",
    "tax_statement_in_chf": "Tax statement in CHF",

    # === BARCODE PAGE ===
    "barcode_page": "Barcode page {page} of {total}",

    # === COMMON LABELS ===
    "date": "Date",
    "description": "Description",
    "currency": "Currency",
    "exchange_rate": "Rate",
    "data_from": "Data from",
    "na": "n/a",
    "column_a": "A",
    "column_b": "B",

    # === SUMMARY TABLE HEADERS ===
    "tax_value_ab_header": "<b>Tax value</b> of<br/><b>A</b>- and <b>B</b>-values<br/>at {date}",
    "gross_revenue_values_with_vst": "<b>Gross revenue</b><br/>{period} values <b>with</b><br/>WHT-deduction",
    "gross_revenue_values_without_vst": "<b>Gross revenue</b><br/>{period} <b>without</b><br/>WHT-deduction",
    "withholding_tax_claim": "Withholding<br/> tax claim",
    "tax_value_da1_usa_header": "<b>Tax value</b> of<br/><b>DA-1</b> and <b>USA</b>-values<br/>at {date}",
    "gross_revenue_da1_usa_header": "<b>Gross revenue</b> {period}<br/><b>DA-1</b> and <b>USA</b>-values",
    "withholding_usa": "Withholding<br/>tax USA",
    "foreign_tax_credit_header": "Recognition of foreign<br/>withholding tax",
    "total_tax_value_header": "<b>Total tax value</b> of<br/><b>A, B, DA-1</b> and <b>USA</b>-<br/>values at {date}",
    "total_gross_revenue_a_with_vst": "<b>Total gross revenue</b> {period}<br/><b>A</b>-values <b>with</b><br/>WHT-deduction",
    "total_gross_revenue_b_da1_usa_without_vst": "<b>Total gross revenue</b> {period} <b>B, DA-1</b> and <b>USA</b>-values <b>without</b> WHT-deduction",
    "total_gross_revenue_all_values": "<b>Total gross revenue</b> {period}<br/><b>A, B, DA-1</b> and <b>USA</b>-values",
    "liabilities_header": "<b>Liabilities</b><br/>at {date}",
    "liabilities_interest_summary_header": "<b>Debt<br/> interests</b> {period}",

    # === BANK ACCOUNTS TABLE ===
    "total_bank_accounts": "Total bank accounts",
    "designation_bank_account_interest": "Description<br/>Bank account<br/>Interests",
    "total_tax_value": "Total tax value",
    "opening": "Opening {date}",
    "closing": "Closing {date}",
    "value_header": "Value<br/>{date}<br/>in CHF",
    "total_paid_bank_fees": "Total expenses",
    "tax_value_revenue": "Tax value / Gross revenue",
    "dissolution_revenue": "Dissolution / Gross revenue",

    # === SECURITIES TABLE ===
    "valor_number_date": "Valor-No.<br/>Date",
    "depot_number_designation_isin": "Depot-No.<br/>Description<br/>ISIN",
    "quantity_nominal": "Quantity<br/>Nominal",
    "currency_country": "Currency<br/>Country",
    "unit_price_nominal_revenue": "Unit price<br/>Nominal<br/>Revenue",
    "ex_date_short": "Ex-<br/>Date",
    "tax_value_header": "<b>Tax value</b><br/>{date}<br/>in CHF",
    "tax_value_date": "<b>Tax value</b> {date}<br/>in CHF",
    "tax_value_revenue_header": "Tax value<br/>Revenue",
    "gross_revenue_with_vst_header": "<b>Gross revenue</b><br/>{year} with WHT<br/>in CHF",
    "gross_revenue_without_vst_header": "<b>Gross revenue</b><br/>{year} without WHT in CHF",
    "gross_revenue_with_vst_year": "<b>Gross revenue</b> {year} with WHT in CHF",
    "gross_revenue_without_vst_year": "<b>Gross revenue</b> {year} without WHT in CHF",
    "depot": "<b>Depot {number}</b>",
    "balance": "Balance",
    "stock_tax_value_revenue": "Stock / Tax value / Gross revenue",
    "total_a_values": "Total Securities",
    "total_b_values": "Total Securities",
    "total_da1_usa": "Total recognition of foreign withholding tax / tax deduction USA",
    "foreign_tax_credit": "<b>Recognition<br/>foreign WHT</b><br/>in CHF",
    "usa_withholding": "<b>Withholding<br/>tax USA</b><br/>in CHF",

    # === LIABILITIES TABLE ===
    "designation_liabilities_interest": "Description<br/>Debts<br/>Interests",
    "liabilities_amount_interest_header": "Debts<br/>Debt<br/> interests",
    "liabilities_amount_header": "<b>Debts</b><br/>{date}<br/>in CHF",
    "liabilities_interest_header": "<b>Debt interests</b><br/>{year}<br/>in CHF",
    "tax_value_liabilities_interest": "Debts / Debt interests",
    "total_liabilities": "Total liabilities",

    # === PAYMENT RECONCILIATION TABLE ===
    "reconciliation_payments": "Payment reconciliation ({country})",
    "kl_dividend_chf": "KL dividend CHF",
    "kl_withholding_chf": "KL withholding CHF",
    "broker_dividend": "Broker dividend",
    "broker_withholding": "Broker withholding",
    "ok": "OK",
    "security": "Security",

    # === INSTRUCTIONS & FOOTNOTES ===
    "footnote_ab_breakdown": "(1) Thereof <b>A</b> {} and <b>B</b> {}",
    "instruction_securities_register": 'Values for the <b>"State of Securities and Other Capital Investment"</b> form (including accounts, without DA-1 and USA values)',
    "instruction_da1_form": 'Values for the supplementary form <b>"Request for recognition\nof foreign withholding taxes and additional retention tax\nUSA"</b> (DA-1)',
    "instruction_no_da1": "If <b>no</b> recognition of foreign withholding tax (DA-1) is claimed, then\nthe total values must be entered in the list of securities.",
    "instruction_liabilities_register": 'Values for the supplementary tax return form <b>"State of debts"</b>',
    "expense_deductibility_notice": "(2) Expenses: The competent tax authority decides on the deductibility of expenses.",

    # === EXPENSE INFORMATION ===
    "expense_type": "Expenses",

    # === PLACEHOLDERS ===
    "minimal_placeholder": "This is not a real tax statement. This minimal document only serves to import bank data via barcodes. Since totals are not determined, no summary is shown.",

    # === CRITICAL WARNINGS ===
    "critical_warnings_title": "CRITICAL WARNINGS",
    "warning": "warning",
    "warnings": "warnings",
    "critical_warnings_hint": "This statement has <b>{count}</b> critical {plural}. Please review the information pages at the end of this document.",
}
