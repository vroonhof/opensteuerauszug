# Verifying an Existing Steuerauszug

Besides generating new Steuerauszüge, OpenSteuerAuszug can also be used to verify or re-calculate an existing Steuerauszug that is already in the eCH-0196 XML format (e.g., one provided by a Swiss bank).

This can be useful for:

*   **Cross-checking**: Comparing the values calculated by OpenSteuerAuszug against those in an official document.
*   **Understanding calculations**: Seeing how OpenSteuerAuszug interprets the data from an existing XML.
*   **Testing**: This feature is also used internally to test the accuracy and compliance of OpenSteuerAuszug's calculation and rendering engine.

## Workflow

1.  **Input**: You will need the existing Steuerauszug in its **XML format** (eCH-0196). This XML can be extracted from an e-Steuerauszug using 'scripts/decode.py'. This needs a python PDF417 decoder with support for multipart barcodes, e.g. using 

    ```console
    pip install git+https://github.com/vroonhof/pdf417decoder.git#subdirectory=python
    ```
    until the version with the fixes has been published on pypi.

2.  **Kursliste**: Have the relevant Kursliste (XML or SQLite in `data/kursliste/`) for the tax year of the Steuerauszug you are verifying. This allows OpenSteuerAuszug to perform its own lookup of tax values.
3.  **Configuration**: Your `config.toml` should be set up, although fewer parameters might be strictly necessary compared to generating a new statement from raw broker data. The tool might extract some metadata from the XML itself.
4.  **Execution**: Run OpenSteuerAuszug telling it to start with the xml as raw input and then run the verify phase:
    ```console
    python -m opensteuerauszug.steuerauszug {xml file} --tax-year {tax year} --raw-import -p verify 
    ```

5.  **Output and known issues**:
    *  The tool will report discrepancies between its calculations and the input data. You may need to refer to the XML source to find the exact source.
    * Because in practice small deviations from the norm (e.g. around rounding or by using different kursliste versions) exist, you can amend `src/opensteuerauszug/util/known_issues.py` to turn them into warnings.

This whole process can be automated to provide integration testing for the tax calculations in this software. The integration tests will fail for any deviations not listed as known_issues.
    
The author is grateful for feedback generated from this validation process including examples stripped of real financial data.
