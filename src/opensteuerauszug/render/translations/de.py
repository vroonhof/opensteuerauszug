"""German translations for PDF rendering."""

TRANSLATIONS = {
    # === DOCUMENT METADATA ===
    'created_with': 'erstellt mit OpenSteuerauszug',
    'converted_with': 'konvertiert mit OpenSteuerauszug',
    'taxstatement': 'Steuerauszug',

    # === PAGE STRUCTURE ===
    'page': 'Seite {page} von {total}',

    # === CLIENT INFORMATION ===
    'client': 'Kunde',
    'client_number': 'Kdnr.',
    'male': 'Herr',
    'female': 'Frau',
    'address': 'Adresse',
    'canton': 'Kanton',
    'period': 'Periode',
    'portfolio': 'Portfolio',
    'created_at': 'Erstellt am',

    # === SECTION TITLES ===
    'summary': 'Zusammenfassung',
    'bank_accounts': 'Bankkonten',
    'a_values_with_vst': 'A-Werte mit Verrechnungssteuerabzug',
    'b_values_without_vst': 'B-Werte ohne Verrechnungssteuerabzug',
    'values_with_da1_usa': 'Werte mit Anrechnung ausländischer Quellensteuer / zusätzlicher Steuerrückbehalt USA',
    'liabilities': 'Schulden',
    'liabilities_title': 'Schulden',
    'reconciliation_kursliste_broker': 'Abgleich Kursliste / Brokerzahlungen',
    'tax_statement_in_chf': 'Steuerauszug in CHF',

    # === BARCODE PAGE ===
    'barcode_page': 'Barcode Seite {page} von {total}',

    # === COMMON LABELS ===
    'date': 'Datum',
    'description': 'Bezeichnung',
    'currency': 'Währung',
    'exchange_rate': 'Kurs',
    'data_from': 'Daten von',
    'na': 'n.v.',
    'column_a': 'A',
    'column_b': 'B',

    # === SUMMARY TABLE HEADERS ===
    'tax_value_ab_header': '<b>Steuerwert</b> der<br/><b>A</b>- und <b>B</b>-Werte am {date}',
    'gross_revenue_values_with_vst': '<b>Bruttoertrag</b><br/>{period} Werte <b>mit</b> VSt.-Abzug',
    'gross_revenue_values_without_vst': '<b>Bruttoertrag</b><br/>{period} Werte <b>ohne</b> VSt.-Abzug',
    'withholding_tax_claim': 'Verrechnungs- steueranspruch',
    'tax_value_da1_usa_header': '<b>Steuerwert</b> der <b>DA-1</b> und <b>USA</b>- Werte am {date}',
    'gross_revenue_da1_usa_header': '<b>Bruttoertrag</b> {period}<br/><b>DA-1</b> und <b>USA</b>-Werte',
    'withholding_usa': 'Steuerrückbehalt USA',
    'foreign_tax_credit_header': 'Anrechnung ausländischer Quellensteuer',
    'total_tax_value_header': '<b>Total Steuerwert</b> der <b>A, B, DA-1</b> und <b>USA</b>-Werte am {date}',
    'total_gross_revenue_a_with_vst': '<b>Total Bruttoertrag</b> {period} <b>A</b>-Werte <b>mit</b><br/>VSt.-Abzug',
    'total_gross_revenue_b_da1_usa_without_vst': '<b>Total Bruttoertrag</b> {period} <b>B, DA-1</b> und <b>USA</b>-Werte <b>ohne</b> VSt.-Abzug',
    'total_gross_revenue_all_values': '<b>Total Bruttoertrag</b> {period} <b>A, B, DA-1</b> und <b>USA</b>-Werte',
    'liabilities_header': '<b>Schulden</b><br/>am {date}',
    'liabilities_interest_summary_header': '<b>Schuldzinsen</b> {period}',

    # === BANK ACCOUNTS TABLE ===
    'total_bank_accounts': 'Total Bankkonten',
    'designation_bank_account_interest': 'Bezeichnung<br/>Bankkonto<br/>Zinsen',
    'total_tax_value': 'Total Steuerwert',
    'opening': 'Eröffnung {date}',
    'closing': 'Saldierung {date}',
    'value_header': 'Wert<br/>{date}<br/>in CHF',
    'total_paid_bank_fees': 'Total bezahlte Bankspesen',
    'tax_value_revenue': 'Steuerwert / Ertrag',
    'dissolution_revenue': 'Auflösung / Ertrag',

    # === SECURITIES TABLE ===
    'valor_number_date': 'Valoren-Nr<br/>Datum',
    'depot_number_designation_isin': 'Depot-Nr<br/>Bezeichnung<br/>ISIN',
    'quantity_nominal': 'Anzahl<br/>Nominal',
    'currency_country': 'Währung<br/>Land',
    'unit_price_nominal_revenue': 'Stückpreis<br/>Nominal<br/>Ertrag',
    'ex_date_short': 'Ex-<br/>Datum',
    'tax_value_header': '<b>Steuerwert</b><br/>{date}<br/>in CHF',
    'tax_value_date': '<b>Steuerwert</b> {date}<br/>in CHF',
    'tax_value_revenue_header': 'Steuerwert<br/>Ertrag',
    'gross_revenue_with_vst_header': '<b>Bruttoertrag</b><br/>{year} mit VSt.<br/>in CHF',
    'gross_revenue_without_vst_header': '<b>Bruttoertrag</b><br/>{year} ohne VSt.<br/>in CHF',
    'gross_revenue_with_vst_year': '<b>Bruttoertrag</b> {year} mit VSt. in CHF',
    'gross_revenue_without_vst_year': '<b>Bruttoertrag</b> {year} ohne VSt. in CHF',
    'depot': '<b>Depot {number}</b>',
    'balance': 'Saldo',
    'stock_tax_value_revenue': 'Bestand / Steuerwert / Ertrag',
    'total_a_values': 'Total A-Werte',
    'total_b_values': 'Total B-Werte',
    'total_da1_usa': 'Total Anrechnung ausländischer Quellensteuer / zusätzlicher Steuerrückbehalt USA',
    'foreign_tax_credit': '<b>Anrechenbare ausl. Quellen- steuer</b> in CHF',
    'usa_withholding': '<b>Steuerrückbehalt USA</b><br/>in CHF',

    # === LIABILITIES TABLE ===
    'designation_liabilities_interest': 'Bezeichnung<br/>Schulden<br/>Zinsen',
    'liabilities_amount_interest_header': 'Schulden<br/>Schuldzinsen',
    'liabilities_amount_header': '<b>Schulden</b><br/>{date}<br/>in CHF',
    'liabilities_interest_header': '<b>Schuldzinsen</b><br/>{year}<br/>in CHF',
    'tax_value_liabilities_interest': 'Steuerwert / Schuldzinsen',
    'total_liabilities': 'Total Schulden',

    # === PAYMENT RECONCILIATION TABLE ===
    'reconciliation_payments': 'Abgleich Zahlungen ({country})',
    'kl_dividend_chf': 'KL Div CHF',
    'kl_withholding_chf': 'KL Quellenst. CHF',
    'broker_dividend': 'Broker Div',
    'broker_withholding': 'Broker Quellenst.',
    'ok': 'OK',
    'security': 'Wertschrift',

    # === INSTRUCTIONS & FOOTNOTES ===
    'footnote_ab_breakdown': '(1) Davon <b>A</b> {} und <b>B</b> {}',
    'instruction_securities_register': 'Werte für Formular <b>"Wertschriften- und Guthabenverzeichnis"</b>\n(inkl. Konti, ohne Werte DA-1 und USA)',
    'instruction_da1_form': 'Werte für zusätzliches Formular <b>"DA-1 Antrag auf Anrechnung\nausländischer Quellensteuer und zusätzlichen Steuerrückbehalt\nUSA"</b> (DA-1)',
    'instruction_no_da1': '''Falls <b>keine</b> Anrechnung ausländischer Quellensteuern (DA-1)
geltend gemacht wird, sind diese Totalwerte im
Wertschriftenverzeichnis einzusetzen.''',
    'instruction_liabilities_register': '''Werte für zusätzliches Steuererklärungsformular <b>"Schuldenverzeichnis"</b>''',
    'expense_deductibility_notice': '(2) Über die Abzugsfähigkeit der Spesen entscheidet die zuständige Veranlagungsbehörde.',

    # === EXPENSE INFORMATION ===
    'expense_type': 'Spesentyp',

    # === PLACEHOLDERS ===
    'minimal_placeholder': '''Dies ist kein echter Steuerauszug. Dieses Minimaldokument dient nur dazu, die Bankdaten über Barcodes zu importieren. Da die Totale nicht ermittelt werden, wird auf eine Zusammenfassung verzichtet.''',

    # === CRITICAL WARNINGS ===
    'critical_warnings_title': 'KRITISCHE WARNUNGEN',
    'warning': 'Warnung',
    'warnings': 'Warnungen',
    'critical_warnings_hint': 'Dieser Steuerauszug enthält <b>{count}</b> kritische {plural}. Bitte überprüfen Sie die Informationsseiten am Ende dieses Dokuments.',
}

