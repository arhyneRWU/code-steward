import pytest

from code_steward.markers import parse_markers_text


def test_parse_alias_and_conceptual_region() -> None:
    text = "\n".join(
        [
            "# code-steward: unit taxonomy.normalize",
            "def normalize():",
            "    pass",
            "",
            "# code-steward: begin taxonomy.validation",
            "def validate():",
            "    pass",
            "# code-steward: end taxonomy.validation",
            "",
        ]
    )

    markers = parse_markers_text(text)
    alias = markers.aliases[0]
    region = markers.regions[0]

    assert alias.unit_id == "taxonomy.normalize"
    assert alias.line == 1
    assert region.unit_id == "taxonomy.validation"
    assert region.start_line == 6
    assert region.end_line == 7
    assert region.marker_start_line == 5
    assert region.marker_end_line == 8


def test_mismatched_region_tags_fail() -> None:
    text = "# code-steward: begin taxonomy.validation\npass\n# code-steward: end taxonomy.other\n"

    with pytest.raises(ValueError, match="Mismatched Code Steward tags"):
        parse_markers_text(text)


def test_region_marker_indentation_must_match() -> None:
    text = (
        "    # code-steward: begin taxonomy.validation\n"
        "    pass\n"
        "# code-steward: end taxonomy.validation\n"
    )

    with pytest.raises(ValueError, match="region indentation"):
        parse_markers_text(text)
