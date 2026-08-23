#!/usr/bin/env python3
"""Verify Code Steward documentation against the live codebase.

Three independent checks run from one entry point:

``coverage``
    Measure docstring coverage for ``src/code_steward`` and compare
    it against the committed ratchet in
    ``scripts/docstring_baseline.json``. Docstrings are a retrieval
    input here, not decoration: the indexer feeds the docstring
    summary line into the ``purpose`` field, which carries the
    largest single weight in ``search.search_units``.

``commands``
    Confirm every shell command quoted in the documentation names a
    real ``code-steward`` subcommand, a real ``make`` target, a real
    module, or a real script path.

``references``
    Confirm the Python symbols the documentation names in backticks
    still resolve inside the package.

Run ``python scripts/docs_check.py --help`` for usage.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = REPO_ROOT / "src" / "code_steward"
BASELINE_PATH = Path(__file__).resolve().parent / "docstring_baseline.json"

# Documentation trees scanned for commands and symbol references.
DOC_GLOBS = (
    "README.md",
    "CONTRIBUTING.md",
    "docs/*.md",
    "benchmarks/*/README.md",
    "skills/**/*.md",
    "agents/**/*.md",
    ".claude/skills/**/*.md",
)

# Interpreter spellings a documented command may use.
PYTHON_NAMES = {"python", "python3", "py"}

# Bare (undotted) symbol names the documentation promises as stable
# API. Prose contains too many plain words to check every backtick
# span, so bare names are only verified when they are listed here or
# written as a call, e.g. ``retrieve_units()``. Under-reporting is
# preferred to noise.
REQUIRED_BARE_SYMBOLS = (
    "search_units",
    "rank_units",
    "retrieve_units",
    "select_review_candidates",
    "metadata_similarity",
    "expand_query",
    "build_packet",
    "replace_hard_relationships",
    "replace_hard_relationships_for_provenance",
    "replace_soft_relationships",
    "index_python_file",
    "iter_python_files",
    "rebuild_index",
    "update_index_file",
    "HardRelationship",
    "SoftRelationship",
)

# Inline spans that look like dotted identifiers but are not Python.
REFERENCE_IGNORES = {
    "psf/requests",
}

# Trailing components that mark a span as a filename, not a symbol.
FILE_SUFFIXES = {"py", "md", "json", "toml", "yml", "yaml", "txt", "cfg", "sqlite3"}

INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
FENCE_RE = re.compile(
    r"^```(?P<lang>[A-Za-z0-9_+-]*)\s*$(?P<body>.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)
SHELL_LANGS = {"bash", "sh", "shell", "console", "zsh"}
DOTTED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
CALL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(\)$")
MAKE_TARGET_RE = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+):(?!=)", re.MULTILINE)


@dataclass
class Finding:
    """One documentation problem worth failing or reporting."""

    check: str
    location: str
    message: str

    def render(self) -> str:
        """Format the finding as a single reviewer-readable line."""
        return f"{self.check}: {self.location}: {self.message}"


@dataclass
class Unit:
    """One documentable declaration found in the package source."""

    module: str
    qualname: str
    kind: str
    line: int
    documented: bool


@dataclass
class CoverageReport:
    """Docstring coverage for the package and each of its modules."""

    units: list[Unit] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Count every declaration considered documentable."""
        return len(self.units)

    @property
    def documented(self) -> int:
        """Count declarations that carry a docstring."""
        return sum(1 for unit in self.units if unit.documented)

    @property
    def percent(self) -> float:
        """Return overall coverage as a rounded percentage."""
        if not self.units:
            return 100.0
        return round(100.0 * self.documented / self.total, 2)

    def by_module(self) -> dict[str, tuple[int, int]]:
        """Map each module to its documented and total counts."""
        rows: dict[str, list[int]] = {}
        for unit in self.units:
            row = rows.setdefault(unit.module, [0, 0])
            row[0] += int(unit.documented)
            row[1] += 1
        return {name: (row[0], row[1]) for name, row in sorted(rows.items())}


# --- coverage ---------------------------------------------------------


def iter_package_files() -> Iterator[Path]:
    """Yield every Python source file in the installed package."""
    yield from sorted(PACKAGE_ROOT.rglob("*.py"))


def _module_name(path: Path) -> str:
    rel = path.relative_to(PACKAGE_ROOT).with_suffix("")
    return ".".join(("code_steward", *rel.parts))


def collect_units(path: Path) -> list[Unit]:
    """Collect documentable declarations from one source file."""
    module = _module_name(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    units: list[Unit] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                qualname = f"{prefix}.{child.name}" if prefix else child.name
                kind = "class" if isinstance(child, ast.ClassDef) else "function"
                units.append(
                    Unit(
                        module=module,
                        qualname=qualname,
                        kind=kind,
                        line=child.lineno,
                        documented=bool(ast.get_docstring(child, clean=True)),
                    )
                )
                walk(child, qualname)
            else:
                walk(child, prefix)

    walk(tree, "")
    return units


def measure_coverage() -> CoverageReport:
    """Measure docstring coverage across the whole package."""
    report = CoverageReport()
    for path in iter_package_files():
        report.units.extend(collect_units(path))
    return report


def load_baseline() -> dict[str, object]:
    """Read the committed coverage ratchet."""
    if not BASELINE_PATH.exists():
        return {"overall_percent": 0.0, "modules": {}}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def write_baseline(report: CoverageReport) -> None:
    """Rewrite the ratchet file from the current measurement."""
    payload = {
        "_comment": (
            "Docstring coverage ratchet. Raise it when coverage improves; "
            "never lower it by hand. Refresh with: make docs-check-update"
        ),
        "overall_percent": report.percent,
        "documented": report.documented,
        "total": report.total,
        "modules": {
            name: {"documented": documented, "total": total}
            for name, (documented, total) in report.by_module().items()
        },
    }
    BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def check_coverage(report: CoverageReport) -> list[Finding]:
    """Fail when coverage drops below the committed ratchet."""
    baseline = load_baseline()
    floor = float(baseline.get("overall_percent", 0.0))
    if report.percent + 1e-9 < floor:
        return [
            Finding(
                "coverage",
                "src/code_steward",
                f"docstring coverage {report.percent:.2f}% is below the "
                f"committed ratchet {floor:.2f}%",
            )
        ]
    return []


# --- documented commands ----------------------------------------------


def iter_doc_files() -> Iterator[Path]:
    """Yield every documentation file the checks read."""
    seen: set[Path] = set()
    for pattern in DOC_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path


def iter_command_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield shell command lines quoted anywhere in one document."""
    for match in FENCE_RE.finditer(text):
        if match.group("lang").lower() not in SHELL_LANGS:
            continue
        start = text[: match.start()].count("\n") + 1
        body = match.group("body")
        buffered = ""
        for offset, raw in enumerate(body.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            line = line.removeprefix("$ ").strip()
            buffered += line
            if buffered.endswith("\\"):
                buffered = buffered[:-1] + " "
                continue
            yield start + offset, buffered
            buffered = ""

    for lineno, raw in enumerate(text.splitlines(), start=1):
        for span in INLINE_CODE_RE.findall(raw):
            value = span.strip()
            first = value.split(" ", 1)[0]
            if first in PYTHON_NAMES or first in {"make", "code-steward", "ruff"}:
                yield lineno, value


def make_targets() -> set[str]:
    """Return every target name declared in the Makefile."""
    makefile = REPO_ROOT / "Makefile"
    if not makefile.exists():
        return set()
    text = makefile.read_text(encoding="utf-8")
    names = {match.group("name") for match in MAKE_TARGET_RE.finditer(text)}
    return {name for name in names if not name.startswith(".")}


def cli_subcommands() -> set[str]:
    """Return every subcommand the installed CLI parser accepts."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    cli = importlib.import_module("code_steward.cli")
    parser = cli.build_parser()
    names: set[str] = set()
    for action in parser._subparsers._group_actions:
        names.update(getattr(action, "choices", {}) or {})
    return names


def check_command(tokens: list[str], location: str) -> list[Finding]:
    """Statically verify one documented command invocation."""
    findings: list[Finding] = []
    # Placeholders such as ``code-steward <subcommand>`` describe a
    # command shape rather than name one, so they are not checked.
    tokens = [token for token in tokens if "<" not in token and ">" not in token]
    if not tokens:
        return findings
    head, *rest = tokens

    if head == "code-steward":
        subs = [token for token in rest if not token.startswith("-")]
        if not subs:
            return findings
        known = cli_subcommands()
        if subs[0] not in known:
            findings.append(
                Finding(
                    "commands",
                    location,
                    f"unknown code-steward subcommand {subs[0]!r}; "
                    f"known: {', '.join(sorted(known))}",
                )
            )
        return findings

    if head == "make":
        targets = make_targets()
        for token in rest:
            if token.startswith("-") or "=" in token:
                continue
            if token not in targets:
                findings.append(Finding("commands", location, f"unknown make target {token!r}"))
        return findings

    if head in PYTHON_NAMES:
        if rest and rest[0] == "-m":
            if len(rest) < 2:
                return findings
            module = rest[1]
            if module.split(".")[0] in {"pip", "pytest", "compileall", "venv"}:
                return findings
            sys.path.insert(0, str(REPO_ROOT / "src"))
            sys.path.insert(0, str(REPO_ROOT))
            try:
                importlib.import_module(module)
            except ImportError:
                findings.append(
                    Finding("commands", location, f"module {module!r} is not importable")
                )
            return findings
        for token in rest:
            if token.endswith(".py"):
                if not (REPO_ROOT / token).exists():
                    findings.append(
                        Finding("commands", location, f"script {token!r} does not exist")
                    )
                break
    return findings


def check_commands() -> list[Finding]:
    """Verify every shell command quoted in the documentation."""
    findings: list[Finding] = []
    for path in iter_doc_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for lineno, command in iter_command_lines(text):
            try:
                tokens = shlex.split(command, comments=True)
            except ValueError:
                continue
            if not tokens:
                continue
            findings.extend(check_command(tokens, f"{rel}:{lineno}"))
    return findings


def run_executed_commands() -> list[Finding]:
    """Execute the documented commands that are safe to run.

    Only read-only, side-effect-free invocations run for real: the
    CLI help surface (which proves the console script and every
    subcommand parser actually construct) and ``make help`` (which
    proves the Makefile parses). Everything else documented here
    either writes to the repository, indexes a tree, clones an
    upstream project, or takes minutes, so it is verified
    statically instead.
    """
    findings: list[Finding] = []
    commands = [
        [sys.executable, "-m", "code_steward", "--help"],
        ["make", "-n", "help"],
    ]
    for command in commands:
        proc = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=_child_env(),
        )
        if proc.returncode != 0:
            findings.append(
                Finding(
                    "commands",
                    " ".join(command),
                    f"exited {proc.returncode}: {proc.stderr.strip()[:200]}",
                )
            )
    return findings


def _child_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    src = str(REPO_ROOT / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src}:{existing}" if existing else src
    return env


# --- symbol references ------------------------------------------------


def package_modules() -> set[str]:
    """Return the importable module names inside the package."""
    return {_module_name(path).split(".", 1)[1] for path in iter_package_files()}


def _resolve(dotted: str) -> bool:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    parts = dotted.split(".")
    for split in range(len(parts), 0, -1):
        module_name = ".".join(parts[:split])
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        target: object = module
        for attribute in parts[split:]:
            if not hasattr(target, attribute):
                return False
            target = getattr(target, attribute)
        return True
    return False


def iter_reference_spans(text: str) -> Iterator[tuple[int, str]]:
    """Yield inline code spans that could name a Python symbol."""
    in_fence = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if raw.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for span in INLINE_CODE_RE.findall(raw):
            value = span.strip()
            called = value.endswith("()")
            if called:
                value = value[:-2]
            if value.rsplit(".", 1)[-1] in FILE_SUFFIXES:
                continue
            yield lineno, value + ("()" if called and "." not in value else "")


def check_references(bare_symbols: Iterable[str] = REQUIRED_BARE_SYMBOLS) -> list[Finding]:
    """Verify backticked Python symbols named in the docs resolve."""
    findings: list[Finding] = []
    modules = package_modules()
    required = set(bare_symbols)
    known_bare = _known_bare_symbols()

    for path in iter_doc_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, span in iter_reference_spans(path.read_text(encoding="utf-8")):
            if span in REFERENCE_IGNORES or " " in span:
                continue

            call = CALL_RE.match(span)
            name = call.group(1) if call else span
            if (call or name in required) and "." not in name:
                if name not in known_bare:
                    findings.append(
                        Finding(
                            "references",
                            f"{rel}:{lineno}",
                            f"documented symbol `{name}` is not defined in the package",
                        )
                    )
                continue

            if not DOTTED_RE.match(span):
                continue
            root = span.split(".")[0]
            if root == "code_steward":
                dotted = span
            elif root in modules:
                dotted = f"code_steward.{span}"
            else:
                continue
            if not _resolve(dotted):
                findings.append(
                    Finding("references", f"{rel}:{lineno}", f"`{span}` does not resolve")
                )
    return findings


def _auxiliary_python_files() -> list[Path]:
    """Return documented Python outside the installed package."""
    roots = (REPO_ROOT / "benchmarks", REPO_ROOT / "scripts")
    return sorted(
        path
        for root in roots
        if root.is_dir()
        for path in root.rglob("*.py")
        if "fixture_repo" not in path.parts
    )


def _known_bare_symbols() -> set[str]:
    names: set[str] = set()
    for path in [*iter_package_files(), *_auxiliary_python_files()]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                names.add(node.name)
    return names


# --- reporting --------------------------------------------------------


def render_coverage(report: CoverageReport) -> str:
    """Render the coverage table and the active ratchet."""
    baseline = load_baseline()
    floor = float(baseline.get("overall_percent", 0.0))
    lines = [
        "Docstring coverage for src/code_steward",
        "",
        f"{'module':<32}{'documented':>12}{'total':>8}{'percent':>10}",
    ]
    for name, (documented, total) in report.by_module().items():
        percent = 100.0 * documented / total if total else 100.0
        lines.append(f"{name:<32}{documented:>12}{total:>8}{percent:>9.1f}%")
    lines.append("")
    lines.append(f"{'OVERALL':<32}{report.documented:>12}{report.total:>8}{report.percent:>9.2f}%")
    lines.append(f"ratchet: {floor:.2f}%")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the documentation check."""
    parser = argparse.ArgumentParser(
        prog="docs_check",
        description="Check Code Steward documentation against the codebase.",
    )
    parser.add_argument(
        "--only",
        choices=("coverage", "commands", "references"),
        action="append",
        default=[],
        help="run only the named check; repeatable",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="rewrite the docstring coverage ratchet and exit",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="skip the few commands that are actually executed",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the requested documentation checks."""
    args = build_parser().parse_args(argv)
    selected = set(args.only) or {"coverage", "commands", "references"}

    report = measure_coverage()
    if args.update_baseline:
        write_baseline(report)
        print(f"wrote {BASELINE_PATH.relative_to(REPO_ROOT)} at {report.percent:.2f}%")
        return 0

    findings: list[Finding] = []
    if "coverage" in selected:
        findings.extend(check_coverage(report))
    if "commands" in selected:
        findings.extend(check_commands())
        if not args.no_execute:
            findings.extend(run_executed_commands())
    if "references" in selected:
        findings.extend(check_references())

    if args.json:
        print(
            json.dumps(
                {
                    "coverage": {
                        "overall_percent": report.percent,
                        "documented": report.documented,
                        "total": report.total,
                        "ratchet": float(load_baseline().get("overall_percent", 0.0)),
                        "modules": {
                            name: {"documented": documented, "total": total}
                            for name, (documented, total) in report.by_module().items()
                        },
                    },
                    "findings": [
                        {
                            "check": finding.check,
                            "location": finding.location,
                            "message": finding.message,
                        }
                        for finding in findings
                    ],
                },
                indent=2,
            )
        )
    else:
        if "coverage" in selected:
            print(render_coverage(report))
            print()
        for finding in findings:
            print(finding.render())
        print(f"\n{len(findings)} documentation problem(s)")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
