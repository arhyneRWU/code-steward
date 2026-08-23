"""Corpus variants for the retrieval validity matrix.

Benchmark v1 (``benchmarks/retrieval/run.py``) is frozen. This module
builds *additional* corpora from the same fixture sources so the
benchmark can measure the conditions v1 cannot see:

``documentation``
    The v1 fixture documents 18 of its 20 units. A real ``src/`` tree
    documents a small minority, so ``purpose`` usually falls back to
    the identifier. The ``undocumented`` variant is produced by
    stripping docstrings with :func:`strip_docstrings`.

``scale``
    The v1 fixture holds 20 units, so a ``limit`` of 5-6 is a 25-30%
    window over the whole corpus and a rank-7 result cannot even
    exist. A real repository gives roughly a 4% window. The ``scaled``
    variant appends deterministically generated competitors so the
    window is realistic.

Variants are generated at run time into a temporary tree rather than
vendored as a second checked-in fixture. A vendored copy would have to
be re-edited by hand every time the v1 fixture changed, and the two
trees would silently drift apart -- at which point the ablation stops
being an ablation, because the corpora differ in more than the one axis
under test. Generating guarantees the only difference is the axis.
"""

from __future__ import annotations

import ast
import shutil
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE_ROOT = HERE / "fixture_repo"

_DOCSTRING_OWNERS = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def strip_docstrings(source: str) -> str:
    """Return ``source`` with every docstring removed.

    Module, class, and function docstrings all go. A declaration whose
    body is nothing but a docstring keeps a ``pass`` so the result
    still parses. Only lines inside a body are removed, so
    ``# code-steward:`` unit tags, which sit above a declaration, keep
    their anchoring.
    """
    tree = ast.parse(source)
    lines = source.splitlines()
    dropped: set[int] = set()
    replaced: dict[int, str] = {}

    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_OWNERS) or not node.body:
            continue
        first = node.body[0]
        if not isinstance(first, ast.Expr):
            continue
        if not isinstance(first.value, ast.Constant) or not isinstance(first.value.value, str):
            continue

        start = first.lineno
        end = first.end_lineno or first.lineno
        dropped.update(range(start, end + 1))
        if len(node.body) == 1 and not isinstance(node, ast.Module):
            line = lines[start - 1]
            indent = line[: len(line) - len(line.lstrip())]
            replaced[start] = f"{indent}pass"

    kept: list[str] = []
    for lineno, line in enumerate(lines, 1):
        if lineno in replaced:
            kept.append(replaced[lineno])
        elif lineno not in dropped:
            kept.append(line)
    return "\n".join(kept) + "\n"


# --- generated competitors --------------------------------------------

# Eight unrelated business domains crossed with eight operations. These
# are never gold and never traps: they exist only to occupy corpus slots
# so ``limit / units`` lands near a real repository's window.
_DOMAINS: tuple[tuple[str, str, str], ...] = (
    ("invoices", "invoice", "invoice"),
    ("shipments", "shipment", "shipment"),
    ("warehouse", "pallet", "pallet"),
    ("tickets", "ticket", "support ticket"),
    ("subscriptions", "subscription", "subscription"),
    ("payroll", "payslip", "payslip"),
    ("auditing", "audit_entry", "audit entry"),
    ("notifications", "notification", "notification"),
)

_OPERATIONS: tuple[tuple[str, str, str, str], ...] = (
    ("issue", "identifier: str", "str", "Issue a new {noun} and return its identifier."),
    ("void", "identifier: str", "bool", "Void an existing {noun} so it no longer applies."),
    (
        "reconcile",
        "left: str, right: str",
        "bool",
        "Reconcile two {noun} records against each other.",
    ),
    ("export", "destination: str", "list[str]", "Export {noun} rows to an external destination."),
    ("archive", "identifier: str", "bool", "Archive a completed {noun} out of the active set."),
    (
        "summarize",
        "period: str",
        "dict[str, str]",
        "Summarize {noun} activity across a reporting period.",
    ),
    ("dispatch", "identifier: str", "bool", "Dispatch a {noun} to its downstream consumer."),
    ("adjust", "identifier: str, delta: int", "int", "Adjust the recorded quantity on a {noun}."),
)

_RETURN_LITERALS = {
    "str": '""',
    "bool": "True",
    "int": "0",
    "list[str]": "[]",
    "dict[str, str]": "{}",
}

# One saturating namespace: near-identical thin wrappers that all
# delegate to the same shared normalization. These *are* plausible
# competitors for the species cases, which is the point -- a corpus that
# only grew by adding unrelated code would raise the unit count without
# making retrieval harder.
_SATURATING_CHANNELS: tuple[str, ...] = (
    "web",
    "mobile",
    "batch",
    "ftp",
    "etl",
    "partner",
    "kiosk",
    "retail",
    "wholesale",
    "hatchery",
    "aquarium",
    "museum",
    "research",
    "quarantine",
    "transfer",
    "donation",
    "rescue",
    "breeder",
    "exhibit",
    "nursery",
    "holding",
    "receiving",
    "dockside",
    "field",
)


def _generated_domain_source(module: str, slug: str, noun: str, documented: bool) -> str:
    blocks: list[str] = []
    for operation, params, returns, doc in _OPERATIONS:
        body = f'    """{doc.format(noun=noun)}"""\n' if documented else ""
        blocks.append(
            f"# code-steward: unit {module}.{operation}\n"
            f"def {operation}_{slug}({params}) -> {returns}:\n"
            f"{body}"
            f"    return {_RETURN_LITERALS[returns]}\n"
        )
    return "\n\n".join(blocks)


def _generated_saturating_source(documented: bool) -> str:
    blocks = ["from taxonomy import normalize_taxon_name\n"]
    for channel in _SATURATING_CHANNELS:
        body = (
            f'    """Resolve a {channel} species label with shared taxonomy."""\n'
            if documented
            else ""
        )
        blocks.append(
            f"# code-steward: unit {channel}.resolve-species\n"
            f"def resolve_{channel}_species(label: str) -> str:\n"
            f"{body}"
            f"    return normalize_taxon_name(label)\n"
        )
    return "\n\n".join(blocks)


def generated_unit_ids() -> set[str]:
    """Return every unit ID introduced by the ``scaled`` corpus."""
    ids = {
        f"{module}.{operation}" for module, _, _ in _DOMAINS for operation, _, _, _ in _OPERATIONS
    }
    ids.update(f"{channel}.resolve-species" for channel in _SATURATING_CHANNELS)
    return ids


# --- corpus assembly --------------------------------------------------


@dataclass(frozen=True, slots=True)
class CorpusVariant:
    """One point on the documentation x scale grid."""

    documented: bool
    scaled: bool

    @property
    def documentation(self) -> str:
        return "documented" if self.documented else "undocumented"

    @property
    def scale(self) -> str:
        return "scaled" if self.scaled else "core"

    @property
    def key(self) -> str:
        return f"{self.documentation}/{self.scale}"


def build_corpus(variant: CorpusVariant, destination: Path) -> Path:
    """Materialize ``variant`` under ``destination``.

    Returns the root of the generated tree.
    """
    root = destination / variant.documentation / variant.scale
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    for path in sorted(FIXTURE_ROOT.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if not variant.documented:
            source = strip_docstrings(source)
        (root / path.name).write_text(source, encoding="utf-8")

    if variant.scaled:
        for module, slug, noun in _DOMAINS:
            (root / f"{module}.py").write_text(
                _generated_domain_source(module, slug, noun, variant.documented),
                encoding="utf-8",
            )
        (root / "saturating.py").write_text(
            _generated_saturating_source(variant.documented),
            encoding="utf-8",
        )

    return root


ALL_VARIANTS: tuple[CorpusVariant, ...] = (
    CorpusVariant(documented=True, scaled=False),
    CorpusVariant(documented=False, scaled=False),
    CorpusVariant(documented=True, scaled=True),
    CorpusVariant(documented=False, scaled=True),
)
