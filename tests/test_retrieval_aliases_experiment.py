from benchmarks.retrieval.run import run_benchmark
from experiments.retrieval_aliases import (
    ABBREVIATIONS,
    STRATEGIES,
    expand_query,
    run_comparison,
)


def test_abbreviation_expansion_is_literal_and_weighted() -> None:
    variants = expand_query("read app settings", (ABBREVIATIONS,))

    assert [(variant.query, variant.weight) for variant in variants] == [
        ("read application settings", 0.95)
    ]


def test_alias_experiment_preserves_the_frozen_baseline() -> None:
    comparison = run_comparison()
    baseline = comparison["strategies"]["baseline"]["summary"]
    benchmark = run_benchmark()["summary"]

    for metric in (
        "case_count",
        "hit_rate_at_k",
        "macro_recall_at_k",
        "mrr",
        "known_trap_rate",
        "known_redundancy_rate",
        "mean_packet_chars",
        "mean_packet_bytes",
    ):
        assert baseline[metric] == benchmark[metric]


def test_alias_experiment_reports_valid_metrics_without_quality_gates() -> None:
    comparison = run_comparison()

    assert set(comparison["strategies"]) == set(STRATEGIES)
    for strategy in comparison["strategies"].values():
        summary = strategy["summary"]
        assert summary["case_count"] == 12
        assert 0.0 <= summary["hit_rate_at_k"] <= 1.0
        assert 0.0 <= summary["macro_recall_at_k"] <= 1.0
        assert 0.0 <= summary["mrr"] <= 1.0
        assert 0.0 <= summary["known_trap_rate"] <= 1.0
        assert 0.0 <= summary["known_redundancy_rate"] <= 1.0
        assert summary["mean_packet_chars"] > 0
        assert summary["mean_packet_bytes"] > 0

        for case in strategy["cases"]:
            assert len(case["candidates"]) == len(set(case["candidates"]))
