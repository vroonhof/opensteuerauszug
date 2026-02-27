import argparse
import sys
from pathlib import Path

# Ensure src is in python path if running from root
# This allows the script to find opensteuerauszug package
src_path = Path(__file__).resolve().parent.parent / "src"
if src_path.exists():
    sys.path.insert(0, str(src_path))

try:
    from opensteuerauszug.kursliste.converter import convert_kursliste_xml_to_sqlite
except ImportError:
    print("Error: Could not import opensteuerauszug.kursliste.converter. Please ensure the package is installed or PYTHONPATH includes src/.")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Convert Kursliste XML to SQLite database.")
    parser.add_argument("xml_file", help="Path to the Kursliste XML file.")
    parser.add_argument("db_file", help="Path to the SQLite database file.")
    args = parser.parse_args()

    try:
        # Call the core conversion function
        convert_kursliste_xml_to_sqlite(args.xml_file, args.db_file)
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
