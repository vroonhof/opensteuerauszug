import logging
from typing import Dict, List


def setup_logging(level: int = logging.INFO) -> None:
    """Configure basic logging for the package."""
    logging.basicConfig(level=level, format="%(levelname)s:%(name)s:%(message)s")


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
