#!/usr/bin/env bash
# Runs the known imports with user provided sample data
# At the moment this is is specific to the Author's setp
# Output PDFs to private/output

set -e  # Exit on any error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$ROOT_DIR/private/output"

# Default phase selection
VERIFY_MODE=true
TAX_CALCULATION_LEVEL="kursliste"
PDF_POSTFIX=".pdf"
XML_POSTFIX=".xml"

if [[ "$1" == "--minimal" ]]; then
  TAX_CALCULATION_LEVEL="minimal"
  PDF_POSTFIX="_min.pdf"
  XML_POSTFIX="_min.xml"
  shift # consume the argument
fi

PHASES="-p import -p calculate -p render"

EXTRA_ARGS="--tax-year 2024 --tax-calculation-level $TAX_CALCULATION_LEVEL"

# Ensure output directory exists
mkdir -p "$OUTPUT_DIR"

# Load EXTRA_SAMPLE_DIR from .env if set
if [ -f "$ROOT_DIR/.env" ]; then
  # shellcheck disable=SC1090
  set -a
  . "$ROOT_DIR/.env"
  set +a
fi

PRIVATE_SAMPLE_DIR="$ROOT_DIR/private/samples"
if [[ -n "$EXTRA_SAMPLE_DIR" ]]; then
  # Expand tilde if present
  SAMPLE_DIR=$(eval echo "$EXTRA_SAMPLE_DIR")
  echo "Processing files from EXTRA_SAMPLE_DIR: $SAMPLE_DIR..."
else
  SAMPLE_DIR="$PRIVATE_SAMPLE_DIR"
  echo "Processing files from private/samples..."
fi

IMPORT_INPUTS=("schwab" "ibkr/*.xml")

for input in "${IMPORT_INPUTS[@]}"; do
  echo "Processing $input... looking at $SAMPLE_DIR/import/$input"
  for input_leaf in "$SAMPLE_DIR"/import/$input; do
    # exists as file or directory
    if [[ -d "$input_leaf" ]]; then
        pdf_name="${input}${PDF_POSTFIX}"
        xml_name="${input}${XML_POSTFIX}"
    else
        if [[ -f "$input_leaf" ]]; then
            filename=$(basename "$input_leaf")
            pdf_name="${filename%.xml}${PDF_POSTFIX}"
            xml_name="${filename%.xml}${XML_POSTFIX}"
            echo "Processing $filename..."
        else
            continue
        fi
    fi
    importer=$(echo "$input" | cut -d'/' -f1)
    python -m opensteuerauszug.steuerauszug "$input_leaf" --importer "$importer" $PHASES -o "$OUTPUT_DIR/$pdf_name"  --xml-output "$OUTPUT_DIR/$xml_name" --debug-dump $OUTPUT_DIR/debug_$importer ${EXTRA_ARGS:-}
  done
done

echo "All files processed. Output PDFs are in $OUTPUT_DIR"
