"""The reviewer scorer must not flatter an arm.

Every case here is a way the score could be inflated: crediting a
REUSE that names the wrong unit, crediting a positive whose duplicate
never reached the packet, or quietly dropping a judgement that never
came back.
"""

from __future__ import annotations

import json

from benchmarks.verdict.agent_score import load_answers, score

POSITIVE = {
    "task_id": "pos-0001-packet",
    "case_id": "pos:0001",
    "arm": "packet",
    "corpus": "django",
    "kind": "reuse-available",
    "expected_label": "C2",
}
NEGATIVE = {
    "task_id": "neg-0001-packet",
    "case_id": "neg:0001",
    "arm": "packet",
    "corpus": "django",
    "kind": "no-reuse-available",
    "expected_label": "",
}


def _answer(verdict: str, candidate: str = "", task_id: str = POSITIVE["task_id"]):
    return {task_id: {"id": task_id, "verdict": verdict, "candidate": candidate}}


def test_naming_the_labelled_duplicate_is_the_only_positive_credit():
    tally, _ = score([POSITIVE], _answer("REUSE", "C2"))
    assert tally["packet"]["positive_correct"] == 1


def test_naming_a_different_unit_earns_nothing():
    tally, _ = score([POSITIVE], _answer("REUSE", "C5"))
    assert tally["packet"].get("positive_correct", 0) == 0
    assert tally["packet"]["positive_wrong_unit"] == 1


def test_extend_counts_the_same_as_reuse():
    tally, _ = score([POSITIVE], _answer("EXTEND", "C2"))
    assert tally["packet"]["positive_correct"] == 1


def test_a_duplicate_that_never_reached_the_packet_is_a_loss():
    """The arm failed, not the reviewer. It must still score zero."""
    unreachable = {**POSITIVE, "expected_label": ""}
    tally, _ = score([unreachable], _answer("NEW"))
    assert tally["packet"].get("positive_correct", 0) == 0
    assert tally["packet"]["positive_unreachable"] == 1


def test_new_is_the_only_correct_answer_on_a_negative():
    correct, _ = score([NEGATIVE], _answer("NEW", task_id=NEGATIVE["task_id"]))
    assert correct["packet"]["negative_correct"] == 1
    talked, _ = score([NEGATIVE], _answer("REUSE", "C1", NEGATIVE["task_id"]))
    assert talked["packet"]["negative_talked_into_reuse"] == 1


def test_a_missing_judgement_is_counted_not_dropped():
    _, missing = score([POSITIVE, NEGATIVE], _answer("REUSE", "C2"))
    assert missing == 1


def test_an_unparsable_verdict_is_counted_not_credited():
    tally, _ = score([POSITIVE], _answer("MAYBE", "C2"))
    assert tally["packet"]["unparsable"] == 1
    assert tally["packet"].get("positive_correct", 0) == 0


def test_answers_load_from_every_file_in_the_directory(tmp_path):
    for index in range(3):
        (tmp_path / f"answer-{index:02d}.json").write_text(
            json.dumps({"answers": [{"id": f"t{index}", "verdict": "NEW", "candidate": ""}]}),
            encoding="utf-8",
        )
    assert sorted(load_answers(tmp_path)) == ["t0", "t1", "t2"]
