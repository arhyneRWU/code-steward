from benchmarks.retrieval.run import index_fixture_repo, load_cases
from code_steward.search import search_units
from experiments.retrieval_diversity import (
    SIMILARITY_THRESHOLD,
    metadata_similarity,
    mmr_select,
    run_comparison,
    similarity_cap,
)


def _unit_map():
    units, _ = index_fixture_repo()
    return {unit.unit_id: unit for unit in units}


def test_wrapper_metadata_similarity_is_detectable_without_gold_labels():
    units = _unit_map()
    wrappers = [
        units["imports.resolve-species"],
        units["api.resolve-species"],
        units["cli.resolve-species"],
    ]
    taxonomy = units["taxonomy.normalize"]

    for index, left in enumerate(wrappers):
        for right in wrappers[index + 1 :]:
            assert metadata_similarity(left, right) >= SIMILARITY_THRESHOLD
        assert metadata_similarity(left, taxonomy) < SIMILARITY_THRESHOLD


def test_similarity_cap_compresses_redundant_wrapper_packet():
    units, _ = index_fixture_repo()
    ranked = search_units(units, "resolve species label", len(units), ["str"], "str")
    selected = similarity_cap(ranked, 6)
    selected_ids = {result.unit.unit_id for result in selected}
    wrapper_ids = {
        "imports.resolve-species",
        "api.resolve-species",
        "cli.resolve-species",
    }

    assert len(selected_ids & wrapper_ids) == 1
    assert "taxonomy.normalize" in selected_ids
    assert len(selected) < 6


def test_mmr_keeps_requested_packet_size_when_pool_is_large_enough():
    units, _ = index_fixture_repo()
    ranked = search_units(units, "resolve species label", len(units), ["str"], "str")
    selected = mmr_select(ranked, 6)

    assert len(selected) == 6
    assert len({result.unit.unit_id for result in selected}) == 6


def test_experiment_uses_frozen_benchmark_cases():
    comparison = run_comparison()
    expected_count = len(load_cases())

    assert comparison["strategies"]["baseline"]["summary"]["case_count"] == expected_count
    assert set(comparison["strategies"]) == {"baseline", "similarity_cap", "mmr"}


def test_similarity_cap_preserves_recall_while_reducing_redundancy():
    comparison = run_comparison()["strategies"]
    baseline = comparison["baseline"]["summary"]
    capped = comparison["similarity_cap"]["summary"]

    assert capped["hit_rate_at_k"] == baseline["hit_rate_at_k"]
    assert capped["macro_recall_at_k"] == baseline["macro_recall_at_k"]
    assert capped["known_redundancy_rate"] < baseline["known_redundancy_rate"]
    assert capped["mean_candidate_count"] < baseline["mean_candidate_count"]
