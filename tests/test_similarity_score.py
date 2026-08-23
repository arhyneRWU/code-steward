"""Check the similarity scorer, including what it refuses to do.

Two of these are anti-inflation tests. A benchmark harness that scores
an unlabelled pair as a hit, or that reports a number when the arm
returned nothing, inflates its own result. Both have to fail loudly
instead.
"""

from __future__ import annotations

import json

import pytest

from benchmarks.similarity.generators import ScoredPair
from benchmarks.similarity.score import ArmScore, Labels, load_labels, score_arm
from tests.test_similarity_generators import BODY, _unit


def _labels() -> Labels:
    labels = Labels()
    labels.by_pair = {
        ("fixture", "a", "b"): "same-behaviour",
        ("fixture", "a", "c"): "overlapping",
        ("fixture", "b", "c"): "unrelated",
    }
    labels.pooled_positives = {"fixture": 2}
    return labels


def _sources():
    return {name: _unit(name, BODY.format(name=name)) for name in ("a", "b", "c", "d")}


def test_positives_and_precision_are_counted_from_the_labels():
    score = score_arm(
        "arm",
        "fixture",
        [ScoredPair("a", "b", 1.0), ScoredPair("b", "c", 0.5)],
        _labels(),
        _sources(),
    )
    assert score.returned == 2
    assert score.labelled == 2
    assert score.positives == 1
    assert score.precision == pytest.approx(0.5)


def test_label_lookup_is_order_independent():
    score = score_arm("arm", "fixture", [ScoredPair("b", "a", 1.0)], _labels(), _sources())
    assert score.positives == 1


def test_an_unlabelled_pair_is_counted_and_never_scored_as_a_hit():
    """An arm cannot earn credit for a pair nobody judged."""
    score = score_arm("arm", "fixture", [ScoredPair("a", "d", 1.0)], _labels(), _sources())
    assert score.unlabelled == 1
    assert score.labelled == 0
    assert score.positives == 0
    # Pessimistic must treat the unjudged pair as noise, optimistic as
    # a hit. A single number here would be a claim the data cannot make.
    assert score.precision_pessimistic == pytest.approx(0.0)
    assert score.precision_optimistic == pytest.approx(1.0)


def test_an_empty_arm_scores_zero_rather_than_dividing_by_zero():
    """A crash that reads as a win is the bug this guards against."""
    score = score_arm("arm", "fixture", [], _labels(), _sources())
    assert score.precision == 0.0
    assert score.recall == 0.0
    assert score.f1 == 0.0
    assert score.precision_optimistic == 0.0


def test_recall_is_measured_against_the_pool_positives():
    score = score_arm(
        "arm",
        "fixture",
        [ScoredPair("a", "b", 1.0), ScoredPair("a", "c", 0.9)],
        _labels(),
        _sources(),
    )
    assert score.pool_positives == 2
    assert score.recall == pytest.approx(1.0)


def test_conflicting_labels_are_rejected(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(
        json.dumps(
            {
                "pairs": [
                    {
                        "pair_id": "x",
                        "corpus": "fixture",
                        "left": "a",
                        "right": "b",
                        "stratum": "pooled",
                        "label": "same-behaviour",
                    },
                    {
                        "pair_id": "x",
                        "corpus": "fixture",
                        "left": "b",
                        "right": "a",
                        "stratum": "pooled",
                        "label": "unrelated",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="conflicting"):
        load_labels(path)


def test_the_committed_labels_load_and_carry_a_probe_base_rate():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    labels = load_labels(root / "benchmarks" / "similarity" / "reuse_pair_labels.json")
    assert labels.pooled_positives
    assert labels.probe_positives
    for _corpus, (positive, total) in labels.probe_positives.items():
        assert total > 0
        assert positive <= total


def test_arm_score_serialises_every_reported_figure():
    payload = ArmScore(arm="a", corpus="c", returned=1, labelled=1, positives=1).to_dict()
    for field in ("precision", "recall_in_pool", "f1", "unlabelled", "bytes_returned"):
        assert field in payload


def test_the_depth_analysis_marks_uninterpretable_rows():
    """Past the pool depth, most returned pairs are unlabelled.

    Reading the committed ranking deeper produces a flattering
    precision over a shrinking labelled subset. The report has to say
    which rows mean something, or the table invites the same mistake
    that made `body-rapidfuzz` unreportable.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "benchmarks" / "similarity" / "depth.json").read_text(encoding="utf-8")
    )
    rows = {row["depth"]: row for row in payload["depth_curve"]}
    pool_depth = payload["pool_depth"]

    for depth, row in rows.items():
        assert row["interpretable"] is (depth <= pool_depth)
        if row["interpretable"]:
            assert row["unlabelled_share"] == 0.0
            assert row["precision_over_labelled"] == row["precision_pessimistic"]
        else:
            # The gap between the two is the whole warning.
            assert row["precision_over_labelled"] > row["precision_pessimistic"]


def test_the_detection_floor_is_reported_with_its_sample_size():
    """A count of zero is only readable next to what was checked."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "benchmarks" / "similarity" / "depth.json").read_text(encoding="utf-8")
    )
    floor = payload["detection_floor"]
    assert floor["positives_checked"] > 0
    assert 0 <= floor["invisible_at_any_depth"] <= floor["positives_checked"]
