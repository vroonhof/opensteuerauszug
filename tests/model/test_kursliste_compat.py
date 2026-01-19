
import pytest
from pathlib import Path
from opensteuerauszug.model.kursliste import Kursliste

@pytest.fixture
def samples_dir() -> Path:
    return Path(__file__).parent.parent / "samples" / "kursliste"

def test_load_v2_2_kursliste(samples_dir):
    """Test loading the updated v2.2 Kursliste file."""
    file_path = samples_dir / "kursliste_mini.xml"
    assert file_path.exists()

    kursliste = Kursliste.from_xml_file(file_path)
    assert kursliste.version == "2.2.0.0"
    assert kursliste.year == 2024
    assert len(kursliste.currencies) == 4
    # Check if a specific element is found (just basic validation)
    assert kursliste.find_security_by_valor(1246192) is not None

def test_load_v2_0_kursliste_compat():
    """Test loading the legacy v2.0 Kursliste file (compatibility mode)."""
    file_path = Path(__file__).parent / "test_data" / "kursliste_2_0.xml"
    assert file_path.exists()

    # This should trigger the _ensure_namespace logic
    kursliste = Kursliste.from_xml_file(file_path)
    # The version in the file is 2.0.0.0, but the model parses it.
    # Note: validation of 'version' attribute might fail if regex doesn't match?
    # I updated the regex to `2\.[02]\.0\.\d`. So 2.0.0.0 should match.
    assert kursliste.version == "2.0.0.0"
    assert kursliste.year == 2024

    # Check if data is preserved
    assert len(kursliste.currencies) == 4
    assert kursliste.find_security_by_valor(1246192) is not None

def test_version_pattern_validation():
    """Verify that version pattern supports both 2.0 and 2.2."""
    from pydantic import ValidationError

    # Valid 2.2
    k22 = Kursliste(version="2.2.0.0", creationDate="2023-01-01T00:00:00", year=2023)
    assert k22.version == "2.2.0.0"

    # Valid 2.0
    k20 = Kursliste(version="2.0.0.0", creationDate="2023-01-01T00:00:00", year=2023)
    assert k20.version == "2.0.0.0"

    # Invalid
    with pytest.raises(ValidationError):
        Kursliste(version="2.1.0.0", creationDate="2023-01-01T00:00:00", year=2023)
