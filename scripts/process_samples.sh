#!/usr/bin/env bash
# Process all XML files in test/samples and private/samples
# Output PDFs to private/output

set -e  # Exit on any error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$ROOT_DIR/private/output"

# Default phase selection
VERIFY_MODE=true

# Process command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --render)
      VERIFY_MODE=false
      shift
      ;;
    --verify)
      VERIFY_MODE=true
      shift
      ;;
    *)
      # Unknown option
      echo "Unknown option: $1"
      echo "Usage: $0 [--render|--verify]"
      echo "  --render: Run calculate and render phases"
      echo "  --verify: Run verify phase only (default)"
      exit 1
      ;;
  esac
done

# Set phases based on mode
if [[ "$VERIFY_MODE" == true ]]; then
  PHASES="-p verify"
  echo "Running in VERIFY mode"
else
  PHASES="-p calculate -p render"
  echo "Running in CALCULATE and RENDER mode"
fi

EXTRA_ARGS="--tax-year 2024"

# Ensure output directory exists
mkdir -p "$OUTPUT_DIR"

# Load EXTRA_SAMPLE_DIR from .env if set
if [ -f "$ROOT_DIR/.env" ]; then
  # shellcheck disable=SC1090
  set -a
  . "$ROOT_DIR/.env"
  set +a
fi

echo "Starting batch processing of XML files..."

# Process files in test/samples
echo "Processing files from test/samples..."
for xml_file in "$ROOT_DIR/tests/samples/"*.xml; do
  if [[ -f "$xml_file" ]]; then
    filename=$(basename "$xml_file")
    pdf_name="${filename%.xml}.pdf"
    echo "Processing $filename..."
    python -m opensteuerauszug.steuerauszug "$xml_file" --raw-import $PHASES -o "$OUTPUT_DIR/$pdf_name" ${EXTRA_ARGS:-}
  fi
done

# Process files in EXTRA_SAMPLE_DIR if set, otherwise private/samples
PRIVATE_SAMPLE_DIR="$ROOT_DIR/private/samples"
if [[ -n "$EXTRA_SAMPLE_DIR" ]]; then
  # Expand tilde if present
  SAMPLE_DIR=$(eval echo "$EXTRA_SAMPLE_DIR")
  echo "Processing files from EXTRA_SAMPLE_DIR: $SAMPLE_DIR..."
else
  SAMPLE_DIR="$PRIVATE_SAMPLE_DIR"
  echo "Processing files from private/samples..."
fi
for xml_file in "$SAMPLE_DIR"/*.xml; do
  if [[ -f "$xml_file" ]]; then
    filename=$(basename "$xml_file")
    pdf_name="${filename%.xml}.pdf"
    echo "Processing $filename..."
    python -m opensteuerauszug.steuerauszug "$xml_file" --raw-import $PHASES -o "$OUTPUT_DIR/$pdf_name" ${EXTRA_ARGS:-}
  fi
done

echo "All files processed. Output PDFs are in $OUTPUT_DIR"