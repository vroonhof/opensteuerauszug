import os
import glob
from typing import List, Optional, Pattern, Union
from pathlib import Path

def get_sample_files(pattern: str, base_dir: str = "tests/samples/") -> List[str]:
    """Get sample files matching the given pattern from both the repository and external directories.
    
    Args:
        pattern: Glob pattern to match files (e.g., "*.xml")
        base_dir: Base directory for repository samples
        
    Returns:
        List of file paths matching the pattern
    """
    # Get samples from the repository
    sample_files = glob.glob(os.path.join(base_dir, pattern))
    
    # Get samples from external directory if specified
    extra_sample_dir = os.getenv("EXTRA_SAMPLE_DIR")
    if extra_sample_dir:
        extra_pattern = os.path.join(
            os.path.expanduser(
                os.path.expandvars(extra_sample_dir)), pattern)
        sample_files.extend(glob.glob(extra_pattern))
    
    return sample_files
