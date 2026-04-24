"""French translations for PDF rendering."""

TRANSLATIONS = {
    # === DOCUMENT METADATA ===
    "created_with": "créé avec OpenSteuerauszug",
    "converted_with": "converti avec OpenSteuerauszug",
    "taxstatement": "extrait fiscal",

    # === PAGE STRUCTURE ===
    "page": "page {page} de {total}",

    # === CLIENT INFORMATION ===
    "client": "Client",
    "client_number": "Ctn°",
    "male": "M.",
    "female": "Mme",
    "address": "Adresse",
    "canton": "Canton",
    "period": "Période",
    "portfolio": "Ctn°",
    "created_at": "Créé le",

    # === SECTION TITLES ===
    "summary": "Sommaire",
    "bank_accounts": "Comptes bancaires",
    "a_values_with_vst": "A-Valeurs avec retenue à la source",
    "b_values_without_vst": "B-Valeurs sans retenue à la source",
    "values_with_da1_usa": "Valeurs avec l'imputation d'impôts étrangers prélevés à la source / retenue suppl. d'impôt USA",
    "liabilities": "Dettes",
    "liabilities_title": "Dettes",
    "reconciliation_kursliste_broker": "Rapprochement Kursliste / paiements du courtier",
    "tax_statement_in_chf": "Relevé fiscal en CHF",

    # === BARCODE PAGE ===
    "barcode_page": "Feuilles de codes à barres {page} de {total}",

    # === COMMON LABELS ===
    "date": "Date",
    "description": "Description",
    "currency": "Devise",
    "exchange_rate": "Cours",
    "data_from": "Données du",
    "na": "n.d.",
    "column_a": "A",
    "column_b": "B",

    # === SUMMARY TABLE HEADERS ===
    "tax_value_ab_header": "<b>Valeur fiscale</b> de<br/>valeurs <b>A</b> et <b>B</b><br/>au {date}",
    "gross_revenue_values_with_vst": "<b>Revenu brut</b><br/>{period} valeurs <b>avec</b><br/>IA-déduction",
    "gross_revenue_values_without_vst": "<b>Revenu brut</b><br/>{period} valeurs <b>sans</b><br/>IA-déduction",
    "withholding_tax_claim": "Retenue à<br/>la source",
    "tax_value_da1_usa_header": "<b>Valeur fiscale</b> de<br/>valeurs <b>DA-1</b> et <b>USA</b><br/>au {date}",
    "gross_revenue_da1_usa_header": "<b>Revenu brut</b> {period}<br/>valeurs <b>DA-1</b> et <b>USA</b>",
    "withholding_usa": "Retenue<br/>fiscale USA",
    "foreign_tax_credit_header": "Retenue d'impôt<br/>étranger éligible",
    "total_tax_value_header": "<b>Total valeur fiscale</b> de<br/>valeurs <b>A, B, DA-1</b> et <b>USA</b><br/>au {date}",
    "total_gross_revenue_a_with_vst": "<b>Total revenu brut</b> {period} valeurs <b>A</b> <b>avec</b><br/>IA-déduction",
    "total_gross_revenue_b_da1_usa_without_vst": "<b>Total revenu brut</b> {period} valeurs <b>B, DA-1</b> et <b>USA</b> <b>sans</b><br/>IA-déduction",
    "total_gross_revenue_all_values": "<b>Total revenu brut</b> {period}<br/>valeurs <b>A, B, DA-1</b> et <b>USA</b>",
    "liabilities_header": "<b>Dettes</b><br/>au {date}",
    "liabilities_interest_summary_header": "<b>Intérêts des<br/>dettes</b> {period}",

    # === BANK ACCOUNTS TABLE ===
    "total_bank_accounts": "Total comptes bancaires",
    "designation_bank_account_interest": "Description<br/>Compte bancaire<br/>Intérêts",
    "opening": "Ouverture {date}",
    "closing": "Clôture {date}",
    "value_header": "Valeur<br/>{date}<br/>en CHF",
    "total_paid_bank_fees": "Total frais",
    "tax_value_revenue": "Valeur fiscale / Revenu brut",
    "dissolution_revenue": "Dissolution / Revenu brut",

    # === SECURITIES TABLE ===
    "valor_number_date": "Valeur-N°<br/>Date",
    "depot_number_designation_isin": "Dépôt-N°<br/>Description<br/>ISIN",
    "quantity_nominal": "Quantité<br/>Nominal",
    "currency_country": "Devise<br/>Pays",
    "unit_price_nominal_revenue": "Prix unitaire<br/>Nominal<br/>Revenu",
    "ex_date_short": "Ex-<br/>Date",
    "tax_value_header": "<b>Valeur fiscale</b><br/>{date}<br/>en CHF",
    "tax_value_date": "<b>Valeur fiscale</b> {date}<br/>en CHF",
    "tax_value_revenue_header": "Valeur fiscale<br/>Revenu",
    "gross_revenue_with_vst_header": "<b>Revenu brut</b><br/>{year} avec IA<br/>en CHF",
    "gross_revenue_without_vst_header": "<b>Revenu brut</b><br/>{year} sans IA<br/>en CHF",
    "gross_revenue_with_vst_year": "<b>Revenu brut</b> {year} avec IA<br/>en CHF",
    "gross_revenue_without_vst_year": "<b>Revenu brut</b> {year} sans IA<br/>en CHF",
    "depot": "<b>Dépôt {number}</b>",
    "balance": "Solde",
    "stock_tax_value_revenue": "Position / Valeur fiscale / Revenu brut",
    "total_a_values": "Total titres",
    "total_b_values": "Total titres",
    "total_da1_usa": "Total l'imputation d'impôts prélevés à la source / retenue supplémentaire d'impôt USA",
    "foreign_tax_credit": "<b>Retenue d'impôt<br/>étranger éligible</b><br/>en CHF",
    "usa_withholding": "<b>Retenue<br/>fiscale USA</b><br/>en CHF",
    'country_total': 'Total {country}',

    # === LIABILITIES TABLE ===
    "designation_liabilities_interest": "Description<br/>Dettes<br/>Intérêts",
    "liabilities_amount_interest_header": "Dettes<br/>Intérêts<br/>la dette",
    "liabilities_amount_header": "<b>Dettes</b><br/>{date}<br/>en CHF",
    "liabilities_interest_header": "<b>Intérêts des dettes</b> {year}<br/>en CHF",
    "tax_value_liabilities_interest": "Dette / Intérêts des dettes",
    "total_liabilities": "Total dettes",

    # === PAYMENT RECONCILIATION TABLE ===
    "reconciliation_payments": "Rapprochement des paiements ({country})",
    "kl_dividend_chf": "KL dividende CHF",
    "kl_withholding_chf": "KL retenue CHF",
    "broker_dividend": "Dividende courtier",
    "broker_withholding": "Retenue courtier",
    "ok": "OK",
    "security": "Titre",

    # === INSTRUCTIONS & FOOTNOTES ===
    "footnote_ab_breakdown": "(1) Dont <b>A</b> {} et <b>B</b> {}",
    "instruction_securities_register": 'Valeurs pour le formulaire <b>"Détail état des titres et autres\nplacements de capitaux"</b> (y compris les comptes, sans les\nvaleurs DA-1 et USA)',
    "instruction_da1_form": "Valeurs pour le formulaire supplémentaire <b>\"Demande de\ncrédit retenue d'impôt étranger et l'impôt supplémentaire\nrétention USA\"</b> (DA-1)",
    "instruction_no_da1": "Si <b>aucun</b> crédit pour la retenue d'impôt étranger (DA-1) n'est\ndemandé, alors ces totaux doivent être inscrits dans l'état des\ntitres.",
    "instruction_liabilities_register": 'Valeurs pour le formulaire de déclaration d\'impôt supplémentaire\n<b>"Etat des dettes"</b>',
    "expense_deductibility_notice": "(2) Frais: L'autorité fiscale compétente décide de la déductibilité des frais.",

    # === EXPENSE INFORMATION ===
    "expense_type": "Frais",

    # === PLACEHOLDERS ===
    "minimal_placeholder": "Ceci n'est pas un extrait fiscal officiel. Ce document minimal sert uniquement à importer les données bancaires via des codes-barres. Les totaux n'étant pas calculés, aucun résumé n'est affiché.",

    # === CRITICAL WARNINGS ===
    "critical_warnings_title": "AVERTISSEMENTS CRITIQUES",
    "warning": "avertissement",
    "warnings": "avertissements",
    "critical_warnings_hint": "Cet extrait contient <b>{count}</b> {plural} critique(s). Veuillez consulter les pages d'information à la fin de ce document.",

    # === XML TRANSLATIONS ===
    "debit_interest": "Paiements d'intérêts",
    "credit_interest": "Intérêts créditeurs",
    "dividend": "Dividende",
    "stock_split": "Fractionnement d'actions",
    "reverse_stock_split": "Regroupement d'actions",
    "distribution": "Distribution",
    "stock_dividend": "Dividende en actions",
    "other_monetary_benefits": "Autres avantages monétaires",
    "premium_agio": "Prime/Agio",
    "taxable_income_from_accumulating_fund": "Revenus imposables du fonds d'accumulation",
    "buy": "Acheter",
    "sell": "Vendre",
    "option_expiration": "Expiration d'option",
    "option_assignment": "Exercice/Attribution d'option",
    "transfer": "Transfert de titres",
}
