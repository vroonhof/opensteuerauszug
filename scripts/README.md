### Kursliste Filtering Script (`scripts/filter_kursliste.py`)

This script filters a large Kursliste XML file (as provided by the Swiss Federal Tax Administration, ESTV) to create a smaller, more manageable version. This is useful for testing, specific analysis, or when only a subset of securities is relevant. The filtering is based on specified valor numbers, and data can also be sourced from eCH-0196 tax statement XML files.

**Purpose:**

To reduce the size of a Kursliste XML file by selecting specific securities (shares, funds, bonds) based on their valor numbers and including all necessary related data (currency definitions, country definitions, institutions, and relevant exchange rates).

**Command-Line Arguments:**

*   `--input-file <path>`: (Required) Path to the full Kursliste XML file.
*   `--output-file <path>`: (Required) Path where the filtered Kursliste XML will be saved.
*   `--valor-numbers <numbers>`: (Optional) A comma-separated string of valor numbers to include (e.g., "12345,67890").
*   `--tax-statement-files <paths...>`: (Optional) One or more paths to eCH-0196 tax statement XML files (separated by spaces). Valor numbers and relevant currency codes will be automatically extracted from these files.
*   `--include-bonds`: (Optional) If specified, bonds matching the valor numbers will also be included. By default, bonds are excluded unless this flag is present.
*   `--target-currency <CUR>`: (Optional) The main target currency (e.g., "CHF", "USD"). Exchange rates relevant to this currency and currencies of selected securities will be prioritized. Defaults to "CHF".
*   `--log-level <LEVEL>`: (Optional) Sets the logging level. Options are DEBUG, INFO, WARNING, ERROR. Defaults to "INFO".

**Input Logic:**

*   **Valor Numbers:** The script determines the final set of valor numbers to filter by taking the *union* of:
    1.  Valor numbers explicitly provided via the `--valor-numbers` argument.
    2.  Valor numbers found within all eCH-0196 tax statement files specified via the `--tax-statement-files` argument.
    *At least one of these sources must provide some valor numbers for the script to select specific securities.*
*   **Relevant Currencies:** The script identifies relevant currencies to ensure their definitions and exchange rates are included. This set is built from:
    1.  The `--target-currency`.
    2.  Currencies found in the provided eCH-0196 tax statement files (from bank accounts, securities, etc.).
    3.  Currencies associated with the securities that are ultimately selected from the Kursliste based on the consolidated valor numbers.

**Usage Example:**

```bash
python scripts/filter_kursliste.py     --input-file data/kursliste/kursliste_2023.xml     --output-file data/kursliste/filtered_kursliste_test.xml     --valor-numbers "12345,67890"     --tax-statement-files "tests/samples/sample_ech0196_statement1.xml" "tests/samples/sample_ech0196_statement2.xml"     --include-bonds     --target-currency CHF     --log-level DEBUG
```

This example would:
- Read `data/kursliste/kursliste_2023.xml`.
- Extract valor numbers from the `--valor-numbers` argument and from both specified tax statement files.
- Filter the Kursliste to include securities matching these combined valor numbers (including bonds if `--include-bonds` is present).
- Ensure definitions and exchange rates for CHF, and any other currencies related to the selected securities or found in the tax statements, are included.
- Save the smaller XML to `data/kursliste/filtered_kursliste_test.xml`.
- Output detailed DEBUG logs.

### Local Action Runner (`scripts/local_action_runner.py`)

This script runs a command locally against a repository ref and publishes the results back to GitHub
as a check run, with artifacts stored on a dedicated branch. This is useful for private data that
cannot be uploaded to a GitHub Action runner.

**Requirements:**

* Python 3.10+
* `git` available in PATH
* A GitHub token with `repo` and `checks:write` scopes in `GITHUB_TOKEN`

**Command-Line Arguments:**

* `--repo <owner/repo>`: (Required unless `GITHUB_REPOSITORY` is set) Target repository.
* `--ref <ref>`: (Optional) Branch, tag, or SHA to run. Defaults to repo default branch.
* `--pr <number>`: (Optional) Pull request number to run (uses the PR head ref).
* `--command <cmd>`: (Required) Command to run locally.
* `--result-path <path>`: (Optional, repeatable) Relative paths to include in a zipped artifact.
* `--show-diff`: (Optional) Show a diff before running the command.
* `--artifact-branch <branch>`: (Optional) Branch used to store artifacts. Defaults to `local-action-artifacts`.
* `--artifact-name <name>`: (Optional) Base name for the artifact zip file. Defaults to `local-run`.
* `--check-name <name>`: (Optional) Name for the GitHub check run. Defaults to `local-action`.
* `--upload-artifacts`: (Optional) Upload artifacts to the artifact branch (requires `--confirm-upload`).
* `--confirm-upload`: (Optional) Confirm upload to GitHub (required to create a check run).
* `--print-check-summary`: (Optional) Print the text uploaded to GitHub (default).
* `--no-print-check-summary`: (Optional) Disable printing the check summary.

**Usage Example:**

```bash
export GITHUB_TOKEN="..."
python scripts/local_action_runner.py \
  --repo my-org/my-repo \
  --ref feature/my-branch \
  --command "python scripts/my_private_job.py --input /secure/data" \
  --result-path results/output.json \
  --result-path results/logs \
  --artifact-name private-run
```

This will:
- Clone the target ref to a temporary folder.
- Run the command locally.
- Store logs and optional result paths under `local-action-results/<run-id>/`.
- Only upload artifacts and create a check run when `--upload-artifacts` and `--confirm-upload` are set.

**Safety note:** this repository is public. By default the script does not upload artifacts or
create a check run. When you opt in to `--confirm-upload` without `--upload-artifacts`, only the
stderr text is sent to the check run summary. Only opt in after reviewing outputs and confirming
they are safe to publish.
