"""Guard the pins and the sampling rule of the similarity corpora.

A benchmark whose corpus can drift is not a benchmark. These tests
fail if a commit SHA changes, if the sampling rule stops being a rule,
or if the committed labels stop matching the schema they were written
under.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.similarity.corpus import (
    CORPORA,
    CORPORA_BY_NAME,
    corpus_roots,
    hash_order,
)
from benchmarks.similarity.pool import LABELS

LABEL_FILE = Path(__file__).resolve().parents[1] / "benchmarks" / "similarity"
LABEL_PATH = LABEL_FILE / "reuse_pair_labels.json"

# The pins the published numbers were measured at. Changing a corpus
# invalidates every figure in docs/similarity.md, so this test exists
# to make that impossible to do quietly.
EXPECTED_PINS = {
    "home-assistant": "759e4658f40b3ccb671d418b8a0ed95224bf4561",
    "airflow": "3adbbe1c58e4532df1964cb7794805e763816ee8",
    "django": "fe0a859f537d4238cf49fca39073513206f83122",
}


def test_every_corpus_is_pinned_to_a_full_sha():
    for corpus in CORPORA:
        assert len(corpus.commit) == 40
        assert set(corpus.commit) <= set("0123456789abcdef")


def test_pins_have_not_drifted():
    assert {corpus.name: corpus.commit for corpus in CORPORA} == EXPECTED_PINS


def test_fetch_script_pins_match_the_corpus_module():
    script = (LABEL_FILE.parents[1] / "scripts" / "fetch_similarity_corpora.sh").read_text(
        encoding="utf-8"
    )
    for corpus in CORPORA:
        assert corpus.commit in script, f"{corpus.name} pin missing from the fetch script"


def test_hash_order_is_stable_and_not_alphabetical():
    names = ["alpha", "beta", "gamma", "delta"]
    assert hash_order(names) == hash_order(list(reversed(names)))
    assert hash_order(names) != sorted(names)


def test_django_is_the_hard_negative_corpus():
    assert CORPORA_BY_NAME["django"].role == "hard-negative"


def test_labels_hold_no_source_text():
    payload = json.loads(LABEL_PATH.read_text(encoding="utf-8"))
    allowed = {"pair_id", "corpus", "left", "right", "stratum", "label"}
    for row in payload["pairs"]:
        assert set(row) == allowed, f"unexpected key in {row['pair_id']}"


def test_every_label_is_in_the_vocabulary():
    payload = json.loads(LABEL_PATH.read_text(encoding="utf-8"))
    for row in payload["pairs"]:
        assert row["label"] in LABELS


def test_label_file_declares_the_blind_protocol():
    payload = json.loads(LABEL_PATH.read_text(encoding="utf-8"))
    assert payload["protocol"] == "blind"
    assert payload["pair_count"] == len(payload["pairs"])


def test_both_strata_are_present():
    payload = json.loads(LABEL_PATH.read_text(encoding="utf-8"))
    strata = {row["stratum"] for row in payload["pairs"]}
    assert strata == {"pooled", "probe"}


@pytest.mark.parametrize("corpus", [corpus.name for corpus in CORPORA])
def test_every_corpus_contributes_labelled_pairs(corpus):
    payload = json.loads(LABEL_PATH.read_text(encoding="utf-8"))
    assert any(row["corpus"] == corpus for row in payload["pairs"])


def test_the_held_out_slice_cannot_overlap_the_gold_sample(tmp_path):
    """Disjointness is the whole basis for choosing a floor there.

    ``_sample_dirs`` sorts alphabetically before returning, so
    slicing its output would hand back alphabetically-late members
    of a larger hash-order prefix -- an overlap, not a held-out set.
    This pins the hash-order slicing that avoids it.
    """
    from benchmarks.similarity.corpus import Corpus, held_out_roots

    parent = tmp_path / "homeassistant" / "components"
    parent.mkdir(parents=True)
    for index in range(40):
        integration = parent / f"thing{index:02d}"
        integration.mkdir()
        for module in range(3):
            (integration / f"m{module}.py").write_text("x = 1\n", encoding="utf-8")

    corpus = Corpus(name="home-assistant", url="", commit="", role="", scope="", sample_size=10)
    gold = {path.name for path in corpus_roots(corpus, tmp_path)}
    held = {path.name for path in held_out_roots(corpus, tmp_path, 10)}

    assert len(gold) == 10
    assert len(held) == 10
    assert not gold & held


def test_a_corpus_with_no_disjoint_slice_yields_nothing(tmp_path):
    """Django takes the whole subtree, so it has no held-out slice."""
    from benchmarks.similarity.corpus import CORPORA_BY_NAME, held_out_roots

    assert held_out_roots(CORPORA_BY_NAME["django"], tmp_path, 10) == []
