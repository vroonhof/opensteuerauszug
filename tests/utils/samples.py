import os
import glob
from typing import List, Optional, Pattern, Union
from pathlib import Path

def get_sample_files(pattern: str, base_dir: str = "tests/samples/") -> List[str]:
    """Get sample files matching the given pattern from both the repository and external directories.
    Args:
        pattern: Glob pattern to match files (e.g., "*.xml" or "import/schwab/*.pdf")
        base_dir: Base directory for repository samples
    Returns:
        List of file paths matching the pattern
    """
    # If pattern does not contain '**', add it for recursive search
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

def get_sample_dirs(subdir: str, extensions: List[str] = ['.pdf', '.json']) -> List[str]:
    """
    Return a list of sample directories to test: the given subdirectory under the repo and, if set, under EXTRA_SAMPLE_DIR.
    Also includes data/{subdir} in the project root as directory of last resort.
    Only include directories that exist and are not empty (contain at least one file with specified extensions).
    Args:
        subdir: Subdirectory path (relative to samples root) to look for sample files (e.g. 'import/schwab')
        extensions: List of file extensions to check for (e.g. ['.pdf', '.json'])
    Returns:
        List of directories containing at least one file with specified extensions
    """
    dirs = []
    # External sample directory
    extra_sample_dir = os.getenv("EXTRA_SAMPLE_DIR")
    if extra_sample_dir:
        extra_dir = os.path.join(os.path.expanduser(os.path.expandvars(extra_sample_dir)), subdir)
        if os.path.isdir(extra_dir):
            files = [f for f in os.listdir(extra_dir) if any(f.lower().endswith(ext) for ext in extensions)]
            if files:
                dirs.append(extra_dir)
    # Default repo directory
    repo_dir = os.path.join("tests/samples", subdir)
    if os.path.isdir(repo_dir):
        files = [f for f in os.listdir(repo_dir) if any(f.lower().endswith(ext) for ext in extensions)]
        if files:
            dirs.append(repo_dir)
    # Add data/{subdir} as directory of last resort
    data_dir = os.path.join("data", subdir)
    if os.path.isdir(data_dir):
        files = [f for f in os.listdir(data_dir) if any(f.lower().endswith(ext) for ext in extensions)]
        if files:
            dirs.append(data_dir)
    return dirs
