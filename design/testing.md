# Integration Testing Methodology

## Overview

This document describes the approach for integration testing in the OpenSteuerauszug project, particularly for testing with real-world samples that cannot be included in the repository.

## External Sample Testing

The project supports testing with external sample files that may contain sensitive or proprietary data that cannot be committed to the repository. This approach allows developers and contributors to test with real-world data while keeping that data private.

### How It Works

1. The test framework looks for sample files in two locations:
   - Standard test samples in the repository (`tests/samples/`)
   - External samples in a directory specified by the `EXTRA_SAMPLE_DIR` environment variable

2. Tests are parameterized to run against all available samples, allowing the same test logic to be applied to both internal and external samples.

3. For XML round-trip testing, the framework:
   - Loads the sample file
   - Parses it into the appropriate model
   - Serializes the model back to XML
   - Normalizes both the original and generated XML (removing whitespace differences, namespace declarations, etc.)
   - Compares the normalized XMLs to ensure they match

### Using External Samples

To test with external samples:

1. Set the `EXTRA_SAMPLE_DIR` environment variable to point to a directory containing your sample files:
   ```bash
   export EXTRA_SAMPLE_DIR=~/my-private-samples
   ```

2. Run the tests:
   ```bash
   pytest tests/
   ```

The test framework will automatically discover and use samples from both the standard test directory and your external directory.

## XML Normalization

XML comparison is challenging due to differences in whitespace, attribute order, and namespace declarations that don't affect the semantic meaning. The testing framework includes utilities to normalize XML for comparison:

- Removing whitespace differences
- Sorting elements for consistent order
- Handling namespace declarations consistently
- Converting decimal representations to a standard format

## Adding New Integration Tests

When adding new integration tests that should work with external samples:

1. Use the `get_sample_files` helper from `tests.utils.samples` to get the list of sample files
2. Use the XML comparison utilities from `tests.utils.xml` for comparing XML outputs
3. Parameterize your test with the sample files

Example:

```python
@pytest.mark.parametrize("sample_file", get_sample_files("*.xml"))
def test_my_feature(sample_file):
    # Test logic using the sample file
    pass
```

## Extending to Other Phases

This approach can be extended to test other phases of the processing pipeline:

- **Import Phase**: Test that files can be correctly imported into the model
- **Validation Phase**: Test that validation rules correctly identify valid/invalid data
- **Calculation Phase**: Test that calculations produce expected results
- **Render Phase**: Test that rendering produces expected output

For each phase, create parameterized tests that use both repository samples and external samples.
