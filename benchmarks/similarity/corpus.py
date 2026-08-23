"""Pinned public corpora for the reuse-similarity gold set.

Three repositories, three roles. Home Assistant supplies integrations
written to a shared template and is expected to carry most positive
pairs. Airflow supplies providers whose hooks and operators were
copied between vendors over years, which is duplication that
accumulated rather than duplication a template produced. Django is the
hard-negative corpus: old, small, and reviewed to death, so the right
answer for most of its functions is that nothing else does this. A
benchmark without a corpus where the answer is usually "nothing"
cannot tell a reuse detector from a nearest-neighbour lookup.

Every corpus is public and pinned to a full commit SHA. That is a
reproducibility requirement before it is a privacy one: a gold set
behind a private repository cannot be rebuilt by a reader, cannot run
in CI, and would hold this project to a lower standard than the one it
applies to other people's benchmarks.

Subtree selection is by stated rule, never by hand. Picking the
integrations that look duplicated would decide the result before the
measurement ran, so the members of each sample are drawn in hash order
of their directory name -- a stable, arbitrary, and reproducible
ordering that no one chose.

The sample sizes are calibrated, not arbitrary. Forty integrations in
hash order yield 316 comparable units, against 3,957 from Django. A
gold set drawn from that mix would be four fifths hard negatives and
could not supply the positive side of 150 pairs. The two duplication
corpora were grown -- 200 integrations, 30 providers -- until all
three sat within the same order of magnitude. Growing them was the
correct fix rather than trimming Django, because Django is the only
corpus that can catch an arm which returns whatever looks most alike.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# Test trees are excluded from every corpus. Test modules repeat
# themselves by design -- fixtures, parametrised cases, and per-vendor
# copies of the same assertion -- so including them would raise the
# positive rate without saying anything about production reuse.
TEST_DIR_NAMES = frozenset({"tests", "test", "testing", "conftest"})


@dataclass(slots=True, frozen=True)
class Corpus:
    """One pinned repository subtree and the rule that selected it."""

    name: str
    url: str
    commit: str
    role: str
    scope: str
    sample_size: int


CORPORA: tuple[Corpus, ...] = (
    Corpus(
        name="home-assistant",
        url="https://github.com/home-assistant/core",
        commit="759e4658f40b3ccb671d418b8a0ed95224bf4561",
        role="template-duplication",
        scope="homeassistant/components/<integration>",
        sample_size=200,
    ),
    Corpus(
        name="airflow",
        url="https://github.com/apache/airflow",
        commit="3adbbe1c58e4532df1964cb7794805e763816ee8",
        role="organic-duplication",
        scope="providers/<provider>/src",
        sample_size=30,
    ),
    Corpus(
        name="django",
        url="https://github.com/django/django",
        commit="fe0a859f537d4238cf49fca39073513206f83122",
        role="hard-negative",
        scope="django",
        sample_size=0,
    ),
)

CORPORA_BY_NAME = {corpus.name: corpus for corpus in CORPORA}


def hash_order(names: Iterable[str]) -> list[str]:
    """Order names by a hash of the name, not by anything meaningful.

    Alphabetical order is not neutral: it clusters vendors whose
    integrations share a prefix. A digest of the name spreads them and
    reproduces byte for byte on any machine.
    """
    return sorted(names, key=lambda name: hashlib.sha256(name.encode()).hexdigest())


def _python_files(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*.py"))
        if not any(part in TEST_DIR_NAMES for part in path.parts)
    ]


def _sample_dirs(parent: Path, minimum_files: int, size: int, subdir: str = "") -> list[Path]:
    """Take ``size`` directories in hash order, skipping stubs."""
    eligible = []
    for child in sorted(parent.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        scoped = child / subdir if subdir else child
        if not scoped.is_dir():
            continue
        if len(_python_files(scoped)) < minimum_files:
            continue
        eligible.append(child.name)
    chosen = hash_order(eligible)[:size]
    return [(parent / name / subdir if subdir else parent / name) for name in sorted(chosen)]


def _eligible_dirs(parent: Path, minimum_files: int, subdir: str = "") -> list[str]:
    """Name every directory under ``parent`` big enough to sample."""
    eligible = []
    for child in sorted(parent.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        scoped = child / subdir if subdir else child
        if not scoped.is_dir():
            continue
        if len(_python_files(scoped)) < minimum_files:
            continue
        eligible.append(child.name)
    return eligible


def _held_out_slice(parent: Path, minimum_files: int, taken: int, size: int, subdir: str = ""):
    """Take the hash-order slice immediately after the gold sample.

    The slicing happens in hash order, before the alphabetical sort
    that ``_sample_dirs`` applies to its result. Slicing the sorted
    output instead would return alphabetically-late members of a
    larger hash-order prefix, which overlaps the gold sample rather
    than avoiding it.
    """
    ordered = hash_order(_eligible_dirs(parent, minimum_files, subdir))
    chosen = ordered[taken : taken + size]
    return [(parent / name / subdir if subdir else parent / name) for name in sorted(chosen)]


def held_out_roots(corpus: Corpus, checkout: Path, size: int) -> list[Path]:
    """Resolve directories the gold sample provably never touched.

    The gold set took the first ``corpus.sample_size`` directories in
    hash order. This takes the next ``size``. Disjointness is a
    property of the slice rather than a claim in a docstring, which
    matters because a threshold chosen on this sample must not have
    been chosen on the labelled one.

    Django has no held-out slice: its rule selects the whole subtree,
    so no disjoint slice exists and the caller gets nothing back.
    """
    if corpus.name == "home-assistant":
        parent = checkout / "homeassistant" / "components"
        return _held_out_slice(parent, 3, corpus.sample_size, size)
    if corpus.name == "airflow":
        parent = checkout / "providers"
        return _held_out_slice(parent, 10, corpus.sample_size, size, subdir="src")
    return []


def held_out_files(corpus: Corpus, checkout: Path, size: int) -> list[Path]:
    """List every non-test Python file in a corpus's held-out slice."""
    files: list[Path] = []
    for root in held_out_roots(corpus, checkout, size):
        files.extend(_python_files(root))
    return sorted(set(files))


def corpus_roots(corpus: Corpus, checkout: Path) -> list[Path]:
    """Resolve a corpus to the directories its sample rule selects."""
    if corpus.name == "home-assistant":
        # Three modules is the floor for an integration that carries
        # real logic rather than a manifest and a config flow stub.
        return _sample_dirs(checkout / "homeassistant" / "components", 3, corpus.sample_size)
    if corpus.name == "airflow":
        # Providers range from one operator to several hundred files;
        # ten modules keeps the sample to providers with a surface.
        return _sample_dirs(checkout / "providers", 10, corpus.sample_size, subdir="src")
    if corpus.name == "django":
        return [checkout / "django"]
    raise ValueError(f"No scope rule for corpus {corpus.name!r}")


def corpus_files(corpus: Corpus, checkout: Path) -> list[Path]:
    """List every non-test Python file inside a corpus sample."""
    files: list[Path] = []
    for root in corpus_roots(corpus, checkout):
        files.extend(_python_files(root))
    return sorted(set(files))
