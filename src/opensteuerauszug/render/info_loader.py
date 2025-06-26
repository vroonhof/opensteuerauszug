from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, List


class MarkdownInfo:
    """Load markdown sections and convert them for ReportLab."""

    def __init__(self, md_path: Path) -> None:
        self.md_path = md_path
        self.sections = self._load_sections()

    def _load_sections(self) -> Dict[str, str]:
        sections: Dict[str, str] = {}
        if not self.md_path.exists():
            return sections

        current_title: Optional[str] = None
        current_lines: List[str] = []
        with open(self.md_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    if current_title is not None:
                        sections[current_title] = "".join(current_lines).strip()
                    current_title = line.lstrip("#").strip()
                    current_lines = []
                else:
                    current_lines.append(line)
        if current_title is not None:
            sections[current_title] = "".join(current_lines).strip()
        return sections

    def get_html(self, title: str) -> str:
        return self._markdown_to_html(self.sections.get(title, ""))

    @staticmethod
    def _markdown_to_html(text: str) -> str:
        lines = text.strip().splitlines()
        parts: List[str] = []
        paragraph: List[str] = []
        i = 0
        while i < len(lines):
            raw = lines[i].rstrip()
            stripped = raw.strip()
            if stripped == "":
                if paragraph:
                    parts.append(" ".join(paragraph))
                    paragraph = []
                i += 1
                continue
            if stripped.startswith(('- ', '* ')):
                if paragraph:
                    parts.append(" ".join(paragraph))
                    paragraph = []
                bullets: List[str] = []
                while i < len(lines):
                    bline = lines[i].strip()
                    if not bline.startswith(('- ', '* ')):
                        break
                    bullets.append('\u2022 ' + bline[2:].strip())
                    i += 1
                parts.append("<br/>".join(bullets))
                continue
            paragraph.append(stripped)
            i += 1
        if paragraph:
            parts.append(" ".join(paragraph))
        return "<br/><br/>".join(parts)
