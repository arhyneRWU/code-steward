from benchmarks.retrieval.run import index_fixture_repo, load_cases
from code_steward.retrieval import expand_query, rank_units, retrieve_units
from code_steward.search import search_units


def _known_redundant(candidate_ids: list[str], groups: list[list[str]]) -> int:
    selected = set(candidate_ids)
    return sum(max(0, len(selected & set(group)) - 1) for group in groups)


def test_expand_query_keeps_narrow_alias_scope() -> None:
    save_variants = {variant.query for variant in expand_query("save settings")}
    repo_variants = {variant.query for variant in expand_query("inventory repo files")}

    assert "persist settings" in save_variants
    assert "inventory repository files" in repo_variants
    assert "save preferences" not in save_variants
    assert "save configuration" not in save_variants


def test_rank_units_recovers_save_settings_vocabulary_mismatch() -> None:
    units, _ = index_fixture_repo()
    results = rank_units(units, "save settings", 5)

    assert "preferences.persist" in {result.unit.unit_id for result in results}


def test_retrieve_units_removes_redundant_wrappers() -> None:
    units, _ = index_fixture_repo()
    results = retrieve_units(units, "resolve species label", 6, ["str"], "str")
    selected = {result.unit.unit_id for result in results}
    wrappers = {
        "imports.resolve-species",
        "api.resolve-species",
        "cli.resolve-species",
    }

    assert len(selected & wrappers) == 1
    assert "taxonomy.normalize" in selected
    assert len(results) < 6


def test_production_pipeline_preserves_combined_benchmark_gain() -> None:
    units, _ = index_fixture_repo()
    cases = load_cases()
    baseline_traps = 0
    production_traps = 0
    production_hits = 0
    production_redundant = 0

    for case in cases:
        limit = case.get("limit", 5)
        input_types = case.get("input_types", [])
        return_type = case.get("return_type", "")
        relevant = set(case["relevant"])
        traps = set(case.get("traps", []))

        baseline = search_units(units, case["query"], limit, input_types, return_type)
        production = retrieve_units(units, case["query"], limit, input_types, return_type)
        baseline_ids = [result.unit.unit_id for result in baseline]
        production_ids = [result.unit.unit_id for result in production]

        baseline_traps += sum(unit_id in traps for unit_id in baseline_ids)
        production_traps += sum(unit_id in traps for unit_id in production_ids)
        production_hits += bool(relevant & set(production_ids))
        production_redundant += _known_redundant(
            production_ids,
            case.get("redundancy_groups", []),
        )

    assert production_hits == len(cases)
    assert production_traps == baseline_traps
    assert production_redundant == 0


def test_non_positive_limits_return_no_candidates() -> None:
    units, _ = index_fixture_repo()

    assert rank_units(units, "save settings", 0) == []
    assert retrieve_units(units, "save settings", -1) == []
