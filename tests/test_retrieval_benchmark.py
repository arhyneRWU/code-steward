from benchmarks.retrieval.run import index_fixture_repo, load_cases, run_benchmark, validate_cases


def test_retrieval_benchmark_gold_ids_resolve() -> None:
    units, _ = index_fixture_repo()
    cases = load_cases()

    validate_cases(cases, {unit.unit_id for unit in units})


def test_retrieval_benchmark_includes_redundancy_cases() -> None:
    cases = load_cases()

    assert any(case.get("redundancy_groups") for case in cases)


def test_retrieval_benchmark_report_has_valid_metrics() -> None:
    report = run_benchmark()
    summary = report["summary"]

    assert report["strategy"] == "current-search-baseline"
    assert summary["case_count"] == len(load_cases())
    assert 0.0 <= summary["hit_rate_at_k"] <= 1.0
    assert 0.0 <= summary["macro_recall_at_k"] <= 1.0
    assert 0.0 <= summary["mrr"] <= 1.0
    assert 0.0 <= summary["known_trap_rate"] <= 1.0
    assert 0.0 <= summary["known_redundancy_rate"] <= 1.0
    assert 0.0 <= summary["duplicate_candidate_rate"] <= 1.0
    assert summary["mean_packet_chars"] > 0
    assert summary["mean_packet_bytes"] > 0


def test_current_baseline_does_not_repeat_candidate_ids() -> None:
    report = run_benchmark()

    for case in report["cases"]:
        assert len(case["candidates"]) == len(set(case["candidates"]))
        assert case["duplicate_candidates"] == 0
