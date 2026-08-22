from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

START_RE = re.compile(r"^\s*#\s*<code-unit:([A-Za-z0-9_.:/-]+)>\s*$")
END_RE = re.compile(r"^\s*#\s*</code-unit:([A-Za-z0-9_.:/-]+)>\s*$")
META_RE = re.compile(r"^\s*#\s*@([A-Za-z0-9_-]+)\s+(.+?)\s*$")


@dataclass(slots=True)
class TaggedRegion:
    unit_id: str
    start_line: int
    end_line: int
    metadata: dict[str, list[str]] = field(default_factory=dict)

    def first(self, key: str, default: str = "") -> str:
        values = self.metadata.get(key, [])
        return values[0] if values else default

    def csv(self, key: str) -> list[str]:
        output: list[str] = []
        for value in self.metadata.get(key, []):
            output.extend(part.strip() for part in value.split(",") if part.strip())
        return output


def parse_regions_text(text: str) -> list[TaggedRegion]:
    lines = text.splitlines()
    stack: list[tuple[str, int, dict[str, list[str]]]] = []
    regions: list[TaggedRegion] = []

    for lineno, line in enumerate(lines, 1):
        start = START_RE.match(line)
        if start:
            stack.append((start.group(1), lineno, {}))
            continue

        if stack:
            meta = META_RE.match(line)
            if meta:
                stack[-1][2].setdefault(meta.group(1).lower(), []).append(meta.group(2).strip())
                continue

        end = END_RE.match(line)
        if end:
            if not stack:
                raise ValueError(f"Unmatched code-unit end tag at line {lineno}: {end.group(1)}")
            unit_id, start_line, metadata = stack.pop()
            if unit_id != end.group(1):
                raise ValueError(
                    f"Mismatched code-unit tags: opened {unit_id!r} at line {start_line}, "
                    f"closed {end.group(1)!r} at line {lineno}"
                )
            regions.append(TaggedRegion(unit_id, start_line, lineno, metadata))

    if stack:
        unit_id, start_line, _ = stack[-1]
        raise ValueError(f"Unclosed code-unit tag {unit_id!r} opened at line {start_line}")

    return regions


def parse_regions(path: Path) -> list[TaggedRegion]:
    return parse_regions_text(path.read_text(encoding="utf-8"))
