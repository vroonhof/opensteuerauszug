"""Italian translations for PDF rendering."""

TRANSLATIONS = {
    # === DOCUMENT METADATA ===
    "created_with": "creato con OpenSteuerauszug",
    "converted_with": "convertito con OpenSteuerauszug",
    "taxstatement": "estratto fiscale",

    # === PAGE STRUCTURE ===
    "page": "pagina {page} di {total}",

    # === CLIENT INFORMATION ===
    "client": "Cliente",
    "client_number": "Ctn°",
    "male": "Sig.",
    "female": "Sig.ra",
    "address": "Indirizzo",
    "canton": "Cantone",
    "period": "Periodo",
    "portfolio": "Ctn°",
    "created_at": "Creato il",

    # === SECTION TITLES ===
    "summary": "Sommario",
    "bank_accounts": "Conti bancari",
    "a_values_with_vst": "A-Valori con ritenuta alla fonte",
    "b_values_without_vst": "B-Valori senza ritenuta alla fonte",
    "values_with_da1_usa": "Valori con computo delle imposte estere trattenute alla fonte / trattenuta supplementare USA",
    "liabilities": "Debiti",
    "liabilities_title": "Debiti",
    "reconciliation_kursliste_broker": "Confronto Kursliste / pagamenti broker",
    "tax_statement_in_chf": "Dichiarazione fiscale in CHF",

    # === BARCODE PAGE ===
    "barcode_page": "Pagina codici a barre {page} di {total}",

    # === COMMON LABELS ===
    "date": "Data",
    "description": "Descrizione",
    "currency": "Valuta",
    "exchange_rate": "Corso",
    "data_from": "Dati del",
    "na": "n.d.",
    "column_a": "A",
    "column_b": "B",

    # === SUMMARY TABLE HEADERS ===
    "tax_value_ab_header": "<b>Valore fiscale</b><br/>dei valori <b>A</b> e <b>B</b><br/>al {date}",
    "gross_revenue_values_with_vst": "<b>Reddito lordo</b><br/>{period} valore <b>con</b><br/>ritenuta alla fonte",
    "gross_revenue_values_without_vst": "<b>Reddito lordo</b><br/>{period} valore <b>senza</b><br/>ritenuta alla fonte",
    "withholding_tax_claim": "ritenuta d'imposta<br/>alla fonte",
    "tax_value_da1_usa_header": "<b>Valore fiscale</b><br/>dei valori <b>DA-1</b> e <b>USA</b><br/>al {date}",
    "gross_revenue_da1_usa_header": "<b>Reddito lordo</b> {period}<br/>valori <b>DA-1</b> e <b>USA</b>",
    "withholding_usa": "Ritenuta<br/>d'acconto USA",
    "foreign_tax_credit_header": "Imposta alla<br/>fonte estera<br/>ammissibile",
    "total_tax_value_header": "<b>Totale dei valori fiscali</b><br/>di <b>A, B, DA-1</b> e <b>USA</b><br/>al {date}",
    "total_gross_revenue_a_with_vst": "<b>Totale reddito lordo</b> {period}<br/>dei valori <b>A</b> <b>con</b><br/>ritenuta alla fonte",
    "total_gross_revenue_b_da1_usa_without_vst": "<b>Totale reddito lordo</b> {period} dei valori <b>B, DA-1</b> e <b>USA</b> <b>senza</b> ritenuta alla fonte",
    "total_gross_revenue_all_values": "<b>Totale reddito lordo</b> {period} dei valori <b>A, B, DA-1</b> e <b>USA</b>",
    "liabilities_header": "<b>Debiti</b><br/>al {date}",
    "liabilities_interest_summary_header": "<b>Interessi</b><br/><b>passivi</b> {period}",

    # === BANK ACCOUNTS TABLE ===
    "total_bank_accounts": "Totale conti bancari",
    "designation_bank_account_interest": "Descrizione<br/>Conto bancario<br/>Interessi",
    "opening": "Apertura {date}",
    "closing": "Chiusura {date}",
    "value_header": "Valore<br/>{date}<br/>in CHF",
    "total_paid_bank_fees": "Totale spese",
    "tax_value_revenue": "Valore fiscale / Reddito lordo",
    "dissolution_revenue": "Liquidazione / Reddito lordo",

    # === SECURITIES TABLE ===
    "valor_number_date": "Valore-N°<br/>Data",
    "depot_number_designation_isin": "Deposito-N°<br/>Descrizione<br/>ISIN",
    "quantity_nominal": "Quantità<br/>Nominale",
    "currency_country": "Valuta<br/>Paese",
    "unit_price_nominal_revenue": "Prezzo unitario<br/>Nominale<br/>Reddito",
    "ex_date_short": "Ex-<br/>Data",
    "tax_value_header": "<b>Valore fiscale</b><br/>{date}<br/>in CHF",
    "tax_value_date": "<b>Valore fiscale</b> {date}<br/>in CHF",
    "tax_value_revenue_header": "Valore fiscale<br/>Reddito",
    "gross_revenue_with_vst_header": "<b>Reddito lordo</b><br/>{year} con IP<br/>in CHF",
    "gross_revenue_without_vst_header": "<b>Reddito lordo</b><br/>{year} senza IP<br/>in CHF",
    "gross_revenue_with_vst_year": "<b>Reddito lordo</b> {year} con IP<br/>in CHF",
    "gross_revenue_without_vst_year": "<b>Reddito lordo</b> {year} senza IP<br/>in CHF",
    "depot": "<b>Deposito {number}</b>",
    "balance": "Saldo",
    "stock_tax_value_revenue": "Saldo / valore fiscale / Reddito lordo",
    "total_a_values": "Totale titoli",
    "total_b_values": "Totale titoli",
    "total_da1_usa": "Totale del computo delle imposte estere prelevate alla fonte / trattenuta supplementare USA",
    "foreign_tax_credit": "<b>Imposta alla fonte<br/>estera ammissibile</b><br/>in CHF",
    "usa_withholding": "<b>Ritenuta<br/>d'acconto USA</b><br/>in CHF",
    'country_total': 'Totale {country}',

    # === LIABILITIES TABLE ===
    "designation_liabilities_interest": "Descrizione<br/>Debiti<br/>Interessi",
    "liabilities_amount_interest_header": "Debiti<br/>Interessi<br/>passivi",
    "liabilities_amount_header": "<b>Debiti</b><br/>{date}<br/>in CHF",
    "liabilities_interest_header": "<b>Interessi passivi</b><br/>{year}<br/>in CHF",
    "tax_value_liabilities_interest": "Debito / Interessi passivi",
    "total_liabilities": "Totale debiti",

    # === PAYMENT RECONCILIATION TABLE ===
    "reconciliation_payments": "Confronto pagamenti ({country})",
    "kl_dividend_chf": "KL dividendo CHF",
    "kl_withholding_chf": "KL ritenuta CHF",
    "broker_dividend": "Dividendo broker",
    "broker_withholding": "Ritenuta broker",
    "ok": "OK",
    "security": "Titolo",

    # === INSTRUCTIONS & FOOTNOTES ===
    "footnote_ab_breakdown": "(1) Di cui <b>A</b> {} e <b>B</b> {}",
    "instruction_securities_register": 'Valori per il modulo <b>"Elenco dei titoli e altri collocamenti in\ncapitale"</b> (compresi i conti, senza valori DA-1 e USA)',
    "instruction_da1_form": 'Valori per il foglio complementare <b>"Istanza per il computo di\nimposte alla fonte estere e rimborso della deduzione fiscale\nalla fonte estere per i dividendi e gli interessi esteri"</b> (DA-1)',
    "instruction_no_da1": "Se <b>non</b> viene richiesto alcun credito per l'imposta alla fonte\nestera (DA-1), questi valori totali devono essere inseriti nell'\nelenco titoli.",
    "instruction_liabilities_register": 'Valori per il modulo di dichiarazione dei redditi complementare\n<b>"Elenco debiti"</b>',
    "expense_deductibility_notice": "* Spese: L'autorità fiscale competente decide sulla deducibilità delle spese.",

    # === EXPENSE INFORMATION ===
    "expense_type": "Spese",

    # === PLACEHOLDERS ===
    "minimal_placeholder": "Questo non è un estratto fiscale ufficiale. Questo documento minimale serve solo per importare i dati bancari tramite codici a barre. Poiché i totali non sono calcolati, non viene mostrato alcun riepilogo.",

    # === CRITICAL WARNINGS ===
    "critical_warnings_title": "AVVISI CRITICI",
    "warning": "avviso",
    "warnings": "avvisi",
    "critical_warnings_hint": "Questo estratto contiene <b>{count}</b> {plural} critico/i. Si prega di consultare le pagine informative alla fine di questo documento.",

    # === XML TRANSLATIONS ===
    "debit_interest": "Pagamenti di interessi",
    "credit_interest": "Interessi attivi",
    "dividend": "Dividendo",
    "stock_split": "Frazionamento azionario",
    "distribution": "Distribuzione",
    "stock_dividend": "Dividendo in azioni",
    "other_monetary_benefits": "Altri benefici monetari",
    "premium_agio": "Premio/Agio",
    "taxable_income_from_accumulating_fund": "Reddito imponibile da fondo di accumulazione",
    "buy": "Compra",
    "sell": "Vendi",
    "option_expiration": "Scadenza opzione",
    "option_assignment": "Esercizio/Attribuzione opzione",
}
