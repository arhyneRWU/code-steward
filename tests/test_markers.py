import pytest

from code_steward.markers import parse_regions_text


def test_parse_region_metadata():
    text = """# <code-unit:x.y>\n# @purpose Do a thing.\n# @concepts alpha, beta\npass\n# </code-unit:x.y>\n"""
    region = parse_regions_text(text)[0]

    assert region.unit_id == "x.y"
    assert region.first("purpose") == "Do a thing."
    assert region.csv("concepts") == ["alpha", "beta"]


def test_mismatched_region_tags_fail():
    text = """# <code-unit:x.y>\npass\n# </code-unit:x.z>\n"""
    with pytest.raises(ValueError, match="Mismatched code-unit tags"):
        parse_regions_text(text)
