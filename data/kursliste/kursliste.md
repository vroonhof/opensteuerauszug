# Kursliste Directory

This directory, `data/kursliste/`, is designated for storing Kursliste files, which are essential for determining the tax values of securities in Switzerland. These files can be in either XML format (`.xml`) or SQLite database format (`.sqlite`).

## Supported Formats and Naming Conventions

The `KurslisteManager` component is designed to automatically discover and load these files. For proper discovery and processing, please adhere to the following naming conventions:

### XML Files
-   **Pattern**: `kursliste_YYYY.xml` (e.g., `kursliste_2023.xml`)
-   **Alternatively**: Filenames where a four-digit year (YYYY) can be clearly identified by the manager's parsing logic (e.g., `YYYY_data.xml`, `someprefix_YYYY_othersuffix.xml`). The standard `kursliste_YYYY.xml` is preferred for clarity.
-   Multiple XML files for the same year can be present. They will be aggregated if loaded as XML data by the `KurslisteAccessor`.

### SQLite Database Files
-   **Pattern**: `kursliste_YYYY.sqlite` (e.g., `kursliste_2023.sqlite`)
-   **Alternatively**: Similar to XML, filenames like `YYYY_data.sqlite` or `someprefix_YYYY_othersuffix.sqlite` from which the year can be parsed.
-   **Preference**: If both an XML file and an SQLite database file are present for the same year (e.g., `kursliste_2023.xml` and `kursliste_2023.sqlite`), the `KurslisteManager` will **prioritize and load the SQLite database file**. The XML file for that year will be ignored by the manager when selecting the primary data source for the `KurslisteAccessor`.
-   **Specific Name Preference**: If multiple SQLite files exist for the same year (e.g., `2023.sqlite` and `kursliste_2023.sqlite`), the manager will prefer the one named `kursliste_YYYY.sqlite`.

## Data Access and Caching

All Kursliste data, whether from XML or SQLite, is accessed through the `KurslisteAccessor` for a given tax year. This accessor provides a unified interface for retrieving security information (as Pydantic models) and exchange rates.

-   **Caching**: The `KurslisteAccessor` automatically caches the results of its data retrieval methods (e.g., fetching securities by ISIN/VALOR, getting exchange rates). This means that subsequent requests for the same data will be served from the cache, significantly improving performance.
-   **Data Source Handling**: The `KurslisteManager` determines the underlying data source for the accessor (SQLite DB or a list of XML file models). The `KurslisteAccessor` then intelligently queries this source. If the source is an SQLite database, the `KurslisteDBReader` component handles the direct database interaction, including deserializing security objects from JSON BLOBs into their respective Pydantic models.

## Automatic Conversion of XML to SQLite (Recommended)

Using the SQLite format is **highly recommended** for performance, especially with large datasets or frequent access. The `KurslisteAccessor`'s caching provides benefits for both sources, but initial loading and complex queries are generally faster with a pre-processed SQLite database.

A utility script is provided to convert XML Kurslisten to the SQLite format. This script now stores each security object as a JSON BLOB in the database, allowing for full reconstruction into its original Pydantic model.

### Conversion Script
-   **Location**: `scripts/convert_kursliste_to_sqlite.py`
-   **Functionality**: Parses a Kursliste XML file and creates a structured SQLite database. Key features of the database schema include:
    -   A `securities` table where each security is stored with its `kl_id` (original XML ID) as the PRIMARY KEY.
    -   Indexed columns `valor_number`, `isin`, and `tax_year` for efficient lookups.
    -   The `security_type_identifier` (e.g., "SHARE.COMMON") is stored for quick type checking.
    -   The full Pydantic model of the security is serialized to a JSON string and stored in a `security_object_blob` (BLOB) field.
    -   Exchange rate data is stored in separate, structured tables.

### How to Use the Conversion Script
1.  **Ensure you have Python installed.**
2.  **Navigate to the project root directory** in your terminal.
3.  **Run the script** with the input XML file path and the desired output SQLite file path:
    ```bash
    python scripts/convert_kursliste_to_sqlite.py path/to/your/kursliste_YYYY.xml data/kursliste/kursliste_YYYY.sqlite
    ```
    **Example:**
    ```bash
    python scripts/convert_kursliste_to_sqlite.py external_downloads/kursliste_2023.xml data/kursliste/kursliste_2023.sqlite
    ```
4.  **Place the generated `.sqlite` file** into the `data/kursliste/` directory. The `KurslisteManager` will then automatically discover and prioritize it for the corresponding year.

## Manual Data Placement

If you have pre-existing Kursliste XML or SQLite files:
1.  Ensure they follow the naming conventions described above.
2.  Place them directly into the `data/kursliste/` directory.

If you are obtaining new Kursliste XML files from official sources (e.g., ESTV), it is strongly recommended to convert them to the SQLite format using the provided script. This ensures optimal performance and allows the system to leverage the full Pydantic models reconstructed from the database. If you choose to use XML files directly (e.g., if an SQLite database for that year is not available), the system will still process them, but performance may be reduced compared to using the SQLite version. The `KurslisteAccessor` will handle caching in either case, but the initial data parsing from multiple or large XMLs can be slower than querying a pre-built database. If an automated conversion process is not yet integrated into your workflow, please use the manual methods outlined.
