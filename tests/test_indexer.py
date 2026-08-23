from pathlib import Path

import pytest

from code_steward.indexer import index_python_file


def _index_text(tmp_path: Path, text: str):
    target = tmp_path / "app.py"
    target.write_text(text, encoding="utf-8")
    return index_python_file(tmp_path, target)


def test_ast_aliases_and_conceptual_region(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "sample_app.py"
    target = tmp_path / "app.py"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    units, endpoints = index_python_file(tmp_path, target)
    ids = {unit.unit_id for unit in units}

    assert "taxonomy.normalize" in ids
    assert "taxonomy.validation" in ids
    assert "organisms.create" in ids
    assert "app::normalize_taxon_name" not in ids
    assert "app::create_organism" not in ids

    endpoint = next(
        endpoint
        for endpoint in endpoints
        if endpoint.method == "POST" and endpoint.route == "/organisms"
    )
    assert endpoint.unit_id == "organisms.create"

    function = next(unit for unit in units if unit.unit_id == "taxonomy.normalize")
    assert function.qualname == "normalize_taxon_name"
    assert function.returns == "Output"
    assert {parameter["name"] for parameter in function.parameters} == {"name", "source"}


def test_decorated_unit_starts_at_first_decorator(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "sample_app.py"
    target = tmp_path / "app.py"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    lines = target.read_text(encoding="utf-8").splitlines()

    units, _ = index_python_file(tmp_path, target)
    unit = next(unit for unit in units if unit.unit_id == "organisms.create")

    assert lines[unit.start_line - 1].startswith("@router.post")
    assert "code-steward: unit" not in "\n".join(lines[unit.start_line - 1 : unit.end_line])


def test_aliases_attach_to_class_method_and_nested_function(tmp_path: Path) -> None:
    text = (
        "# code-steward: unit taxonomy.normalizer\n"
        "class Normalizer:\n"
        "    # code-steward: unit taxonomy.normalizer.normalize\n"
        "    def normalize(self, name: str) -> str:\n"
        "        # code-steward: unit taxonomy.normalizer.clean\n"
        "        def clean(value: str) -> str:\n"
        "            return value.strip()\n"
        "        return clean(name)\n"
    )

    units, _ = _index_text(tmp_path, text)
    by_id = {unit.unit_id: unit for unit in units}

    assert by_id["taxonomy.normalizer"].qualname == "Normalizer"
    assert by_id["taxonomy.normalizer.normalize"].qualname == "Normalizer.normalize"
    assert by_id["taxonomy.normalizer.clean"].qualname == "Normalizer.normalize.clean"


def test_alias_attaches_to_async_function(tmp_path: Path) -> None:
    text = "# code-steward: unit jobs.refresh\nasync def refresh() -> None:\n    return None\n"

    units, _ = _index_text(tmp_path, text)
    unit = next(unit for unit in units if unit.unit_id == "jobs.refresh")

    assert unit.kind == "async_function"
    assert unit.qualname == "refresh"


def test_typing_overload_stubs_are_not_indexed(tmp_path: Path) -> None:
    text = (
        "from typing import overload\n"
        "\n"
        "@overload\n"
        "def encode(value: None) -> None: ...\n"
        "@overload\n"
        "def encode(value: str) -> str: ...\n"
        "def encode(value: str | None) -> str | None:\n"
        "    return value\n"
    )

    units, _ = _index_text(tmp_path, text)
    matches = [unit for unit in units if unit.unit_id == "app::encode"]

    assert len(matches) == 1
    assert matches[0].signature == "encode(value: str | None) -> str | None"


def test_qualified_typing_overload_async_stub_is_not_indexed(tmp_path: Path) -> None:
    text = (
        "import typing\n"
        "\n"
        "@typing.overload\n"
        "async def fetch(value: None) -> None: ...\n"
        "async def fetch(value: str | None) -> str | None:\n"
        "    return value\n"
    )

    units, _ = _index_text(tmp_path, text)
    matches = [unit for unit in units if unit.unit_id == "app::fetch"]

    assert len(matches) == 1
    assert matches[0].kind == "async_function"


def test_unattached_unit_alias_fails(tmp_path: Path) -> None:
    text = """# code-steward: unit taxonomy.normalize\n\ndef normalize():\n    pass\n"""

    with pytest.raises(ValueError, match="must immediately precede"):
        _index_text(tmp_path, text)


def test_alias_indentation_must_match_declaration(tmp_path: Path) -> None:
    text = (
        "class Normalizer:\n"
        "# code-steward: unit taxonomy.normalize\n"
        "    def normalize(self):\n"
        "        pass\n"
    )

    with pytest.raises(ValueError, match="declaration indentation"):
        _index_text(tmp_path, text)


def test_duplicate_semantic_ids_fail(tmp_path: Path) -> None:
    text = (
        "# code-steward: unit shared.normalize\n"
        "def first():\n"
        "    pass\n"
        "\n"
        "# code-steward: unit shared.normalize\n"
        "def second():\n"
        "    pass\n"
    )

    with pytest.raises(ValueError, match="Duplicate Code Steward unit ID"):
        _index_text(tmp_path, text)


def test_alias_and_region_cannot_share_an_id(tmp_path: Path) -> None:
    text = (
        "# code-steward: unit shared.validation\n"
        "def validate():\n"
        "    pass\n"
        "\n"
        "# code-steward: begin shared.validation\n"
        "value = 1\n"
        "# code-steward: end shared.validation\n"
    )

    with pytest.raises(ValueError, match="Duplicate Code Steward unit ID"):
        _index_text(tmp_path, text)
