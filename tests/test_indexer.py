from pathlib import Path

from code_steward.indexer import index_python_file


def test_ast_and_region_index(tmp_path: Path):
    source = Path(__file__).parent / "fixtures" / "sample_app.py"
    target = tmp_path / "app.py"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    units, endpoints = index_python_file(tmp_path, target)
    ids = {unit.unit_id for unit in units}

    assert "app::normalize_taxon_name" in ids
    assert "taxonomy.normalize" in ids
    assert any(endpoint.method == "POST" and endpoint.route == "/organisms" for endpoint in endpoints)

    function = next(unit for unit in units if unit.unit_id == "app::normalize_taxon_name")
    assert function.returns == "Output"
    assert {parameter["name"] for parameter in function.parameters} == {"name", "source"}
