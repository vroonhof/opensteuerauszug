#!/usr/bin/env bash
# Process all XML files in test/samples and private/samples
# Output PDFs to private/output

set -e  # Exit on any error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$ROOT_DIR/private/output"


for xml_file in "$OUTPUT_DIR/"*.xml; do
  if [[ -f "$xml_file" ]]; then
    java -cp ./scripts/ XmlValidator "$xml_file" specs/eCH-0196-2-2.xsd
  fi
done
