import os
import re

for filename in os.listdir("tests"):
    if filename.startswith("test_") and filename.endswith(".py"):
        filepath = os.path.join("tests", filename)
        with open(filepath, "r") as f:
            content = f.read()

        # Update CLI calls to include 'generate', 'verify' subcommands
        # For example: runner.invoke(app, [str(dummy_xml_file), "--raw-import", ...])
        # Needs to become: runner.invoke(app, ["generate", str(dummy_xml_file), "--raw", ...])
        # It's better to manually fix the main test files that are failing.
