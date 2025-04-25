#!/usr/bin/env bash
# Process all XML files in test/samples and private/samples
# Output PDFs to private/output

set -e  # Exit on any error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$ROOT_DIR/private/output"
PHASES="-p calculate -p render"

# Ensure output directory exists
mkdir -p "$OUTPUT_DIR"

echo "Starting batch processing of XML files..."

# Process files in test/samples
echo "Processing files from test/samples..."
for xml_file in "$ROOT_DIR/tests/samples/"*.xml; do
  if [[ -f "$xml_file" ]]; then
    filename=$(basename "$xml_file")
    pdf_name="${filename%.xml}.pdf"
    echo "Processing $filename..."
    python -m opensteuerauszug.steuerauszug "$xml_file" --raw-import $PHASES -o "$OUTPUT_DIR/$pdf_name"
  fi
done

# Process files in private/samples
echo "Processing files from private/samples..."
for xml_file in "$ROOT_DIR/private/samples/"*.xml; do
  if [[ -f "$xml_file" ]]; then
    filename=$(basename "$xml_file")
    pdf_name="${filename%.xml}.pdf"
    echo "Processing $filename..."
    python -m opensteuerauszug.steuerauszug "$xml_file" --raw-import $PHASES -o "$OUTPUT_DIR/$pdf_name"
  fi
done

echo "All files processed. Output PDFs are in $OUTPUT_DIR"