"""Anti-inflation and pinning guards for every benchmark harness.

Four disciplines, each with a test that fails if the discipline
lapses. They were adopted after reading Graph Code Review's evaluation
harness, which had shipped two bugs where a thrown exception scored as
a win. This project had no equivalent guard at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from benchmarks.guards import (
    DegenerateBenchmark,
    Exclusions,
    assert_reports_exclusions,
    checked_rate,
)

ROOT = Path(__file__).resolve().parents[1]


# --- discipline 1: no metric invented from an empty run ------------


def test_a_rate_over_nothing_raises_instead_of_scoring_zero():
    """Returning nothing must not read as returning nothing bad."""
    with pytest.raises(DegenerateBenchmark, match="known_trap_rate"):
        checked_rate(0, 0, metric="known_trap_rate")


def test_a_rate_with_a_denominator_is_ordinary_division():
    assert checked_rate(1, 4, metric="known_trap_rate") == pytest.approx(0.25)


def test_both_harnesses_route_their_shrinking_metrics_through_the_guard():
    """The guard is worthless if a harness stops calling it."""
    guarded = ("known_trap_rate", "known_redundancy_rate", "duplicate_candidate_rate")
    for module in ("benchmarks/retrieval/run.py", "benchmarks/real_repo/retrieval_baseline.py"):
        source = (ROOT / module).read_text(encoding="utf-8")
        for metric in guarded:
            pattern = rf'"{metric}": checked_rate\('
            assert re.search(pattern, source), f"{module} computes {metric} without the guard"


def test_the_frozen_benchmark_still_reports_a_rate():
    """A live run, so source inspection alone cannot satisfy it."""
    from benchmarks.retrieval.run import run_benchmark

    summary = run_benchmark()["summary"]
    assert 0.0 <= summary["known_trap_rate"] <= 1.0


# --- discipline 2: excluded rows counted, never dropped ------------


def test_exclusions_count_every_reason_and_bound_the_examples():
    dropped = Exclusions(example_limit=2)
    for index in range(5):
        dropped.record("below-min-lines", f"unit-{index}")
    dropped.record("unparseable-file:SyntaxError", "a.py")
    assert dropped.total == 6
    assert dropped.reasons["below-min-lines"] == 5
    assert len(dropped.examples["below-min-lines"]) == 2


def test_a_report_without_an_exclusion_block_is_rejected():
    """Absent and zero differ. Absent means nobody counted."""
    with pytest.raises(DegenerateBenchmark, match="excluded"):
        assert_reports_exclusions({"summary": {}})
    assert_reports_exclusions({"summary": {}, "excluded": Exclusions().to_dict()})


def test_the_frozen_benchmark_emits_its_exclusion_block():
    from benchmarks.retrieval.run import run_benchmark

    assert_reports_exclusions(run_benchmark())


def test_the_similarity_loader_records_what_it_skips(tmp_path):
    """A corpus loader must not quietly shrink its own population."""
    from benchmarks.similarity.units import load_units

    good = tmp_path / "good.py"
    good.write_text(
        "def big(values):\n"
        "    total = 0\n"
        "    for value in values:\n"
        "        total += value * 2\n"
        "    return total\n",
        encoding="utf-8",
    )
    tiny = tmp_path / "tiny.py"
    tiny.write_text("def small():\n    return 1\n", encoding="utf-8")
    broken = tmp_path / "broken.py"
    broken.write_text("def oops(:\n", encoding="utf-8")

    dropped = Exclusions()
    units = load_units("fixture", tmp_path, [good, tiny, broken], dropped)
    assert [unit.unit.name for unit in units] == ["big"]
    assert dropped.total >= 2
    assert any(reason.startswith("unparseable-file") for reason in dropped.reasons)
    assert "below-min-lines" in dropped.reasons


# --- discipline 3: pins enforced, not merely documented ------------


def test_the_requests_pin_is_a_full_sha():
    payload = json.loads(
        (ROOT / "benchmarks" / "real_repo" / "requests.json").read_text(encoding="utf-8")
    )
    assert re.fullmatch(r"[0-9a-f]{40}", payload["commit"])


def test_the_requests_pin_matches_the_sha_the_readme_quotes():
    """A README figure measured at another commit is a false figure."""
    payload = json.loads(
        (ROOT / "benchmarks" / "real_repo" / "requests.json").read_text(encoding="utf-8")
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    quoted = set(re.findall(r"`([0-9a-f]{7,40})`", readme))
    assert any(payload["commit"].startswith(value) for value in quoted), (
        "README quotes no commit that the requests pin starts with"
    )


# --- discipline 4: calibration present and self-consistent ---------


def test_the_committed_calibration_covers_every_published_population():
    payload = json.loads(
        (ROOT / "benchmarks" / "token_calibration.json").read_text(encoding="utf-8")
    )
    populations = {entry["population"] for entry in payload["populations"]}
    assert {"home-assistant", "airflow", "django", "frozen-benchmark-packets"} <= populations
    for entry in payload["populations"]:
        assert entry["total_tokens"] > 0
        assert entry["bytes_per_token"] > 0


def test_the_calibration_publishes_per_population_error_not_just_a_mean():
    """A flattering average would hide the worst population."""
    payload = json.loads(
        (ROOT / "benchmarks" / "token_calibration.json").read_text(encoding="utf-8")
    )
    errors = {
        entry["population"]: entry["relative_error_of_assumption"]
        for entry in payload["populations"]
    }
    assert len(errors) == len(payload["populations"])
    assert any(abs(value) > 0.05 for value in errors.values()), (
        "a calibration with no population above 5% error is not worth publishing"
    )


def test_the_calibration_matches_a_live_tiktoken_count():
    """Skipped without the optional dependency, enforced with it."""
    pytest.importorskip("tiktoken")
    from benchmarks.tokens import calibrate

    result = calibrate("probe", ["def f(x):\n    return x + 1\n"])
    assert result.total_tokens > 0
    assert result.bytes_per_token > 1.0


# --- discipline 5: every harness entry point runs ------------------


def test_every_benchmark_module_imports():
    """CI ran these as scripts and one stopped importing. Guard it.

    ``benchmarks`` is a package, so a module that imports a sibling
    only resolves under ``python -m``. Running the same file as a
    script puts its own directory on the path instead of the repository
    root, and the import fails at load time -- after CI has already
    spent several minutes cloning the upstream repository.
    """
    import importlib

    modules = [
        "benchmarks.guards",
        "benchmarks.tokens",
        "benchmarks.retrieval.run",
        "benchmarks.retrieval.matrix",
        "benchmarks.real_repo.validate",
        "benchmarks.real_repo.retrieval_baseline",
        "benchmarks.real_repo.calls_reachability",
        "benchmarks.real_repo.calls_rerank",
        "benchmarks.real_repo.grep_baseline",
        "benchmarks.real_repo.precision",
        "benchmarks.real_repo.label_sheet",
        "benchmarks.similarity.make_pairs",
        "benchmarks.similarity.score",
        "benchmarks.similarity.floor",
        "benchmarks.similarity.alarm",
        "benchmarks.check_history",
        "benchmarks.trace_bundle",
        "benchmarks.verdict.bundle_prompts",
        "benchmarks.verdict.bundle_score",
        "benchmarks.verdict.draft_prompts",
        "benchmarks.verdict.draft_score",
        "benchmarks.verdict.run",
        "benchmarks.verdict.agent_prompts",
        "benchmarks.verdict.agent_score",
    ]
    for name in modules:
        assert importlib.import_module(name) is not None


def test_no_caller_invokes_a_benchmark_as_a_bare_script():
    """A bare path invocation is the failure this test exists for."""
    callers = [
        ROOT / "Makefile",
        ROOT / ".github" / "workflows" / "real-repo-validation.yml",
        ROOT / ".github" / "workflows" / "ci.yml",
    ]
    for path in callers:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        offenders = re.findall(r"\S*python\S*\)?\s+benchmarks/\S+\.py", text)
        assert not offenders, f"{path.name} runs a benchmark as a script: {offenders}"


def test_the_corpus_loader_uses_the_product_definition_of_a_function():
    """A benchmark that filters differently measures a different tool.

    `benchmarks/similarity/units.py` kept its own copy of
    `FUNCTION_KINDS`, and the two diverged: the product's was fixed to
    include `async_function` while the benchmark's was not, so the
    published alarm rates were still computed on a population that
    excluded every `async def` -- 43.4% of Home Assistant.
    """
    from benchmarks.similarity import units as corpus_units
    from code_steward.similarity import FUNCTION_KINDS

    assert corpus_units.FUNCTION_KINDS is FUNCTION_KINDS


def test_every_committed_similarity_report_carries_its_exclusions():
    """A dropped row that appears nowhere is a smaller, cleaner corpus.

    `guards.py` states the rule in its own module docstring, and
    `alarm.json` broke it: the loader recorded every drop through the
    `Exclusions` machinery and no caller passed one in, so the counts
    were built and discarded. That is how 43% of Home Assistant could
    be excluded from a published alarm rate without it showing
    anywhere in the artifact.
    """
    for name in ("alarm.json",):
        payload = json.loads(
            (ROOT / "benchmarks" / "similarity" / name).read_text(encoding="utf-8")
        )
        assert_reports_exclusions(payload)
