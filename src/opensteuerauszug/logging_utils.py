import logging
from typing import Dict, List

class CustomFormatter(logging.Formatter):
    """Custom formatter to remove the project name from the logger name."""

    def format(self, record):
        if record.name.startswith('opensteuerauszug'):
            record.name = record.name[len('opensteuerauszug'):]
            if record.name.startswith('.'):
                record.name = record.name[1:]
        return super().format(record)

def setup_logging(verbose: bool):
    """Set up logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO
    formatter = CustomFormatter('%(levelname)s:%(name)s:%(message)s')
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    
    root_logger = logging.getLogger('opensteuerauszug')
    root_logger.setLevel(level)
    root_logger.addHandler(handler)
    # Prevent propagation to the root logger to avoid duplicate messages
    root_logger.propagate = False

    

class RemarkCollector:
    """Collects remarks for securities and global notes."""

    def __init__(self) -> None:
        self.security_remarks: Dict[str, List[str]] = {}
        self.general_remarks: List[str] = []

    def add_security_remark(self, security_id: str, remark: str) -> None:
        self.security_remarks.setdefault(security_id, []).append(remark)

    def add_general_remark(self, remark: str) -> None:
        self.general_remarks.append(remark)

    def get_security_remarks(self, security_id: str) -> List[str]:
        return self.security_remarks.get(security_id, [])

    def get_all_general_remarks(self) -> List[str]:
        return list(self.general_remarks)