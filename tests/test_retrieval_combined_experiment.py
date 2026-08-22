from benchmarks.retrieval.run import index_fixture_repo, load_cases
from code_steward.search import search_units
from experiments.retrieval_combined import (
    SIMILARITY_THRESHOLD,
    expand_query,
    metadata_similarity,
    run_comparison,
    similarity_cap,
)


def _unit_map():
    units, _ = index_fixture_repo()
    return {unit.unit_id: unit for unit in units}


def test_combined_aliases_cover_programming_and_abbreviation_cases() -> None:
    save_variants = {variant.query for variant in expand_query("save settings")}
    repo_variants = {variant.query for variant in expand_query("inventory repo files")}

    assert "persist settings" in save_variants
    assert "catalog repo files" in repo_variants
    assert "inventory repository files" in repo_variants


def test_combined_experiment_does_not_add_broad_concept_aliases() -> None:
    variants = {variant.query for variant in expand_query("save settings")}

    assert "save preferences" not in variants
    assert "save configuration" not in variants


def test_wrapper_similarity_is_detectable_from_indexed_metadata() -> None:
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


def test_similarity_cap_removes_wrapper_redundancy() -> None:
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


def test_comparison_uses_only_frozen_benchmark_cases() -> None:
    comparison = run_comparison()
    expected_count = len(load_cases())

    assert set(comparison["strategies"]) == {
        "baseline",
        "alias_expansion",
        "similarity_cap",
        "alias_expansion_similarity_cap",
    }
    for strategy in comparison["strategies"].values():
        assert strategy["summary"]["case_count"] == expected_count


def test_combined_pipeline_improves_recall_without_adding_traps() -> None:
    comparison = run_comparison()["strategies"]
    baseline = comparison["baseline"]["summary"]
    combined = comparison["alias_expansion_similarity_cap"]["summary"]

    assert combined["hit_rate_at_k"] > baseline["hit_rate_at_k"]
    assert combined["macro_recall_at_k"] > baseline["macro_recall_at_k"]
    assert combined["mrr"] > baseline["mrr"]
    assert combined["known_traps_returned"] == baseline["known_traps_returned"]


def test_combined_pipeline_reduces_redundancy_and_packet_size() -> None:
    comparison = run_comparison()["strategies"]
    baseline = comparison["baseline"]["summary"]
    combined = comparison["alias_expansion_similarity_cap"]["summary"]

    assert combined["known_redundant_candidates"] == 0
    assert combined["known_redundancy_rate"] < baseline["known_redundancy_rate"]
    assert combined["mean_candidate_count"] < baseline["mean_candidate_count"]
    assert combined["mean_packet_chars"] < baseline["mean_packet_chars"]
    assert combined["mean_packet_bytes"] < baseline["mean_packet_bytes"]
