from __future__ import annotations

import io
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path

ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_.:/-]*"
UNIT_RE = re.compile(rf"^(?P<indent>[ \t]*)#\s+code-steward:\s*unit\s+(?P<id>{ID_PATTERN})\s*$")
BEGIN_RE = re.compile(rf"^(?P<indent>[ \t]*)#\s+code-steward:\s*begin\s+(?P<id>{ID_PATTERN})\s*$")
END_RE = re.compile(rf"^(?P<indent>[ \t]*)#\s+code-steward:\s*end\s+(?P<id>{ID_PATTERN})\s*$")


@dataclass(slots=True, frozen=True)
class UnitAlias:
    unit_id: str
    line: int
    indent: str


@dataclass(slots=True, frozen=True)
class TaggedRegion:
    unit_id: str
    start_line: int
    end_line: int
    marker_start_line: int
    marker_end_line: int
    indent: str


@dataclass(slots=True, frozen=True)
class ParsedMarkers:
    aliases: tuple[UnitAlias, ...]
    regions: tuple[TaggedRegion, ...]

    @property
    def control_lines(self) -> frozenset[int]:
        lines = {alias.line for alias in self.aliases}
        for region in self.regions:
            lines.add(region.marker_start_line)
            lines.add(region.marker_end_line)
        return frozenset(lines)


def _comment_lines(text: str) -> list[tuple[int, str]]:
    """Yield ``(lineno, line)`` for own-line comments only.

    Tags are comments by specification, so the tokenizer is the
    authority on what is a comment: text inside a string literal is
    never a tag. Only comments that begin their own logical line can
    be tags, matching the anchored regexes below.

    If ``text`` cannot be tokenized it is not valid Python, and the
    caller may not even have handed us Python. Rather than failing,
    fall back to scanning every raw line, which is exactly the
    behaviour this parser had before tokenization was introduced.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return list(enumerate(text.splitlines(), 1))

    result: list[tuple[int, str]] = []
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        lineno, col = token.start
        prefix = token.line[:col]
        if prefix.strip():
            continue
        result.append((lineno, prefix + token.string))
    return result


def parse_markers_text(text: str) -> ParsedMarkers:
    aliases: list[UnitAlias] = []
    regions: list[TaggedRegion] = []
    stack: list[tuple[str, int, str]] = []

    for lineno, line in _comment_lines(text):
        unit = UNIT_RE.match(line)
        if unit:
            aliases.append(UnitAlias(unit.group("id"), lineno, unit.group("indent")))
            continue

        begin = BEGIN_RE.match(line)
        if begin:
            stack.append((begin.group("id"), lineno, begin.group("indent")))
            continue

        end = END_RE.match(line)
        if not end:
            continue

        if not stack:
            raise ValueError(f"Unmatched Code Steward end tag at line {lineno}: {end.group('id')}")

        unit_id, marker_start_line, indent = stack.pop()
        if unit_id != end.group("id"):
            raise ValueError(
                f"Mismatched Code Steward tags: opened {unit_id!r} at line "
                f"{marker_start_line}, closed {end.group('id')!r} at line {lineno}"
            )
        if indent != end.group("indent"):
            raise ValueError(
                f"Mismatched Code Steward region indentation for {unit_id!r}: "
                f"lines {marker_start_line} and {lineno}"
            )
        if lineno == marker_start_line + 1:
            raise ValueError(
                f"Empty Code Steward region {unit_id!r} at lines {marker_start_line}-{lineno}"
            )

        regions.append(
            TaggedRegion(
                unit_id=unit_id,
                start_line=marker_start_line + 1,
                end_line=lineno - 1,
                marker_start_line=marker_start_line,
                marker_end_line=lineno,
                indent=indent,
            )
        )

    if stack:
        unit_id, marker_start_line, _ = stack[-1]
        raise ValueError(
            f"Unclosed Code Steward tag {unit_id!r} opened at line {marker_start_line}"
        )

    return ParsedMarkers(tuple(aliases), tuple(regions))


def parse_markers(path: Path) -> ParsedMarkers:
    return parse_markers_text(path.read_text(encoding="utf-8"))


def parse_regions_text(text: str) -> list[TaggedRegion]:
    """Return only conceptual regions."""
    return list(parse_markers_text(text).regions)


def parse_regions(path: Path) -> list[TaggedRegion]:
    return list(parse_markers(path).regions)
