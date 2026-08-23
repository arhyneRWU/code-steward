from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.real_repo.precision import load_labels, score_arm

CASES = [
    {"id": "c1", "candidates": ["u1", "u2", "u3", "u4"]},
    {"id": "c2", "candidates": ["u5", "u6"]},
]

LABELS = {
    ("c1", "u1"): "relevant",
    ("c1", "u2"): "plausible",
    ("c1", "u3"): "irrelevant",
    ("c1", "u4"): "irrelevant",
    ("c2", "u5"): "relevant",
    ("c2", "u6"): "relevant",
}


def _write(path: Path, entries: list[dict[str, str]]) -> Path:
    path.write_text(json.dumps({"labels": entries}), encoding="utf-8")
    return path


def test_score_arm_reports_strict_and_lenient_precision() -> None:
    report = score_arm(CASES, LABELS, "arm")
    summary = report["summary"]

    # 3 relevant of 6 scored; 4 of 6 once plausible counts.
    assert summary["precision_strict"] == pytest.approx(0.5)
    assert summary["precision_lenient"] == pytest.approx(4 / 6)
    assert summary["noise_rate"] == pytest.approx(2 / 6)


def test_macro_average_does_not_let_one_long_packet_dominate() -> None:
    summary = score_arm(CASES, LABELS, "arm")["summary"]

    # Micro precision is 0.5. Macro is the mean of 0.25 and 1.0.
    assert summary["macro_precision_strict"] == pytest.approx(0.625)
    assert summary["macro_noise_rate"] == pytest.approx(0.25)


def test_score_arm_refuses_to_score_an_unlabeled_candidate() -> None:
    cases = [{"id": "c1", "candidates": ["u1", "unlabeled"]}]

    with pytest.raises(ValueError, match="have no label"):
        score_arm(cases, LABELS, "arm")


def test_load_labels_merges_disjoint_files(tmp_path: Path) -> None:
    first = _write(tmp_path / "a.json", [{"case_id": "c1", "unit_id": "u1", "label": "relevant"}])
    second = _write(
        tmp_path / "b.json", [{"case_id": "c1", "unit_id": "u2", "label": "irrelevant"}]
    )

    labels = load_labels([first, second])

    assert labels == {("c1", "u1"): "relevant", ("c1", "u2"): "irrelevant"}


def test_load_labels_rejects_a_conflict_instead_of_picking_one(tmp_path: Path) -> None:
    first = _write(tmp_path / "a.json", [{"case_id": "c1", "unit_id": "u1", "label": "relevant"}])
    second = _write(
        tmp_path / "b.json", [{"case_id": "c1", "unit_id": "u1", "label": "irrelevant"}]
    )

    with pytest.raises(ValueError, match="Conflicting labels"):
        load_labels([first, second])


def test_load_labels_accepts_an_agreeing_duplicate(tmp_path: Path) -> None:
    entry = [{"case_id": "c1", "unit_id": "u1", "label": "relevant"}]
    first = _write(tmp_path / "a.json", entry)
    second = _write(tmp_path / "b.json", entry)

    assert load_labels([first, second]) == {("c1", "u1"): "relevant"}


def test_load_labels_rejects_an_unknown_label(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.json", [{"case_id": "c1", "unit_id": "u1", "label": "maybe"}])

    with pytest.raises(ValueError, match="unknown label"):
        load_labels([path])


def test_stored_label_file_covers_every_benchmark_case() -> None:
    """The committed labels must stay in step with the case set."""
    root = Path(__file__).resolve().parents[1] / "benchmarks" / "real_repo"
    labels = json.loads((root / "requests_candidate_labels.json").read_text(encoding="utf-8"))
    cases = json.loads((root / "requests_retrieval.json").read_text(encoding="utf-8"))

    labeled_cases = {entry["case_id"] for entry in labels["entries"]}

    assert labeled_cases == {case["id"] for case in cases}
    assert labels["count"] == len(labels["entries"])


def test_stored_labels_reproduce_the_gold_key() -> None:
    """Blind labels disagreeing with the gold key invalidate both."""
    root = Path(__file__).resolve().parents[1] / "benchmarks" / "real_repo"
    labels = json.loads((root / "requests_candidate_labels.json").read_text(encoding="utf-8"))
    cases = json.loads((root / "requests_retrieval.json").read_text(encoding="utf-8"))

    by_key = {(entry["case_id"], entry["unit_id"]): entry["label"] for entry in labels["entries"]}

    for case in cases:
        for gold in case["relevant"]:
            assert by_key[(case["id"], gold)] == "relevant", (case["id"], gold)
