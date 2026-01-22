#!/bin/bash

# Wrapper script to invoke TaxStatementMain Java application
# Can be called from any directory

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Invoke the Java application with passed arguments
java -Dxlsx=true -cp "$SCRIPT_DIR/*" ch.ewv.taxstatement.examples.TaxStatementMain "$@"
