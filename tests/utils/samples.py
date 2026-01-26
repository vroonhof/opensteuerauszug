import os
import glob
from typing import List, Optional, Pattern, Union
from pathlib import Path

def _find_repo_root(start: Path) -> Path:
    for parent in [start, *start.parents]:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return start


REPO_ROOT = _find_repo_root(Path(__file__).resolve())

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
    base_path = Path(base_dir)
    if not base_path.is_absolute():
        base_path = REPO_ROOT / base_path
    sample_files = glob.glob(str(base_path / pattern))
    
    # Get samples from private directory if it exists
    private_dir = REPO_ROOT / "private/samples"
    if private_dir.is_dir():
        private_pattern = private_dir / pattern
        sample_files.extend(glob.glob(str(private_pattern)))
    
    # Get samples from external directory if specified
    extra_sample_dir = os.getenv("EXTRA_SAMPLE_DIR")
    if extra_sample_dir:
        extra_pattern = Path(os.path.expanduser(os.path.expandvars(extra_sample_dir))) / pattern
        sample_files.extend(glob.glob(str(extra_pattern)))
    
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
        extra_dir = Path(os.path.expanduser(os.path.expandvars(extra_sample_dir))) / subdir
        if extra_dir.is_dir():
            files = [f for f in os.listdir(extra_dir) if any(f.lower().endswith(ext) for ext in extensions)]
            if files:
                dirs.append(str(extra_dir))
    # Private samples directory
    private_dir = REPO_ROOT / "private/samples" / subdir
    if private_dir.is_dir():
        files = [f for f in os.listdir(private_dir) if any(f.lower().endswith(ext) for ext in extensions)]
        if files:
            dirs.append(str(private_dir))
    # Default repo directory
    repo_dir = REPO_ROOT / "tests/samples" / subdir
    if repo_dir.is_dir():
        files = [f for f in os.listdir(repo_dir) if any(f.lower().endswith(ext) for ext in extensions)]
        if files:
            dirs.append(str(repo_dir))
    # Add data/{subdir} as directory of last resort
    data_dir = REPO_ROOT / "data" / subdir
    if data_dir.is_dir():
        files = [f for f in os.listdir(data_dir) if any(f.lower().endswith(ext) for ext in extensions)]
        if files:
            dirs.append(str(data_dir))
    return dirs
