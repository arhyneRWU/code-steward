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


def test_unit_tag_inside_string_literal_is_not_an_alias() -> None:
    text = "\n".join(
        [
            "FIXTURE = '''",
            "# code-steward: unit taxonomy.normalize",
            "def normalize():",
            "    pass",
            "'''",
            "",
        ]
    )

    markers = parse_markers_text(text)

    assert markers.aliases == ()
    assert markers.regions == ()
    assert markers.control_lines == frozenset()


def test_region_tags_inside_string_literal_are_ignored() -> None:
    text = "\n".join(
        [
            "FIXTURE = '''",
            "# code-steward: begin taxonomy.validation",
            "pass",
            "# code-steward: end taxonomy.validation",
            "'''",
            "",
        ]
    )

    markers = parse_markers_text(text)

    assert markers.regions == ()
    assert markers.aliases == ()


def test_in_string_end_tag_does_not_corrupt_the_region_stack() -> None:
    text = "\n".join(
        [
            "# code-steward: begin taxonomy.validation",
            "FIXTURE = '''",
            "# code-steward: end taxonomy.validation",
            "'''",
            "# code-steward: end taxonomy.validation",
            "",
        ]
    )

    markers = parse_markers_text(text)

    assert len(markers.regions) == 1
    region = markers.regions[0]
    assert region.unit_id == "taxonomy.validation"
    assert region.marker_start_line == 1
    assert region.marker_end_line == 5
    assert region.start_line == 2
    assert region.end_line == 4


def test_in_string_begin_tag_does_not_raise_unclosed() -> None:
    text = "\n".join(
        [
            "FIXTURE = '''",
            "# code-steward: begin taxonomy.validation",
            "'''",
            "",
        ]
    )

    assert parse_markers_text(text).regions == ()


def test_trailing_comment_tag_is_not_a_tag() -> None:
    text = "\n".join(
        [
            "x = 1  # code-steward: unit taxonomy.normalize",
            "def normalize():",
            "    pass",
            "",
        ]
    )

    assert parse_markers_text(text).aliases == ()


def test_indented_real_tags_still_parse() -> None:
    text = "\n".join(
        [
            "class Taxonomy:",
            "    # code-steward: unit taxonomy.normalize",
            "    def normalize(self):",
            "        pass",
            "",
            "    # code-steward: begin taxonomy.validation",
            "    def validate(self):",
            "        pass",
            "    # code-steward: end taxonomy.validation",
            "",
        ]
    )

    markers = parse_markers_text(text)
    alias = markers.aliases[0]
    region = markers.regions[0]

    assert alias.unit_id == "taxonomy.normalize"
    assert alias.line == 2
    assert alias.indent == "    "
    assert region.indent == "    "
    assert region.marker_start_line == 6
    assert region.marker_end_line == 9
    assert markers.control_lines == frozenset({2, 6, 9})
