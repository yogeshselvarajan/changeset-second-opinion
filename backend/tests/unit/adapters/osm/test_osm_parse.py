from __future__ import annotations

import pytest

from cso.adapters.osm import (
    ElementCapExceededError,
    ParseError,
    TooLargeError,
    XmlSafetyError,
    parse_osm_change,
)
from cso.domain.enums import ChangeAction, OsmType

HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n'


def osc(*blocks: str) -> str:
    return f'{HEADER}<osmChange version="0.6">{"".join(blocks)}</osmChange>'


def way(osm_id: int, version: int, *tags: tuple[str, str], visible: bool = True) -> str:
    tag_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags)
    return (
        f'<way id="{osm_id}" version="{version}" visible="{str(visible).lower()}" '
        f'changeset="9" timestamp="2026-03-02T14:02:00Z" user="mapper_A" uid="7">'
        f'<nd ref="1"/><nd ref="2"/>{tag_xml}</way>'
    )


def test_parses_all_actions_and_fields() -> None:
    doc = osc(
        '<create><node id="5" version="1" lat="1.5" lon="2.5" changeset="9"/></create>',
        f"<modify>{way(10, 4, ('highway', 'residential'), ('name', 'A'))}</modify>",
        '<delete><relation id="20" version="7" visible="false">'
        '<member type="way" ref="10" role="outer"/></relation></delete>',
    )
    parsed = parse_osm_change(doc)
    assert parsed.raw_element_count == 3
    assert parsed.action_counts == {
        ChangeAction.CREATE: 1,
        ChangeAction.MODIFY: 1,
        ChangeAction.DELETE: 1,
    }
    node, modified, deleted = (g.last for g in parsed.elements)
    assert (node.lat, node.lon, node.osm_type) == (1.5, 2.5, OsmType.NODE)
    assert modified.tags == {"highway": "residential", "name": "A"}
    assert modified.nodes == (1, 2) and modified.uid == 7 and modified.user == "mapper_A"
    assert modified.timestamp is not None and modified.timestamp.tzinfo is not None
    assert deleted.visible is False and deleted.tags == {}
    assert deleted.members[0].role == "outer" and deleted.members[0].ref_type is OsmType.WAY


def test_prior_version_is_version_minus_one_and_creations_have_none() -> None:
    parsed = parse_osm_change(
        osc(
            '<create><node id="5" version="1" lat="1" lon="1"/></create>',
            f"<modify>{way(10, 4)}</modify>",
        )
    )
    created, modified = parsed.elements
    assert created.before_version is None
    assert (modified.before_version, modified.after_version) == (3, 4)


def test_same_element_edited_twice_uses_first_minus_one_and_last_version() -> None:
    doc = osc(
        f"<modify>{way(10, 5, ('name', 'mid'))}</modify>",
        f"<modify>{way(10, 4, ('name', 'first'))}</modify>",
        f"<modify>{way(10, 6, ('name', 'last'))}</modify>",
    )
    parsed = parse_osm_change(doc)
    assert len(parsed.elements) == 1 and parsed.raw_element_count == 3
    grouped = parsed.elements[0]
    assert grouped.before_version == 3  # earliest v - 1, whatever the document order
    assert grouped.first.version == 4 and grouped.last.version == 6
    assert grouped.last.tags["name"] == "last"
    assert grouped.key == (OsmType.WAY, 10)


def test_created_then_deleted_in_one_changeset_reports_delete_without_prior() -> None:
    doc = osc(
        '<create><node id="5" version="1" lat="1" lon="1"/></create>',
        '<delete><node id="5" version="2" visible="false"/></delete>',
    )
    grouped = parse_osm_change(doc).elements[0]
    assert grouped.action is ChangeAction.DELETE and grouped.before_version is None


def test_same_id_different_types_stay_separate_and_order_is_document_order() -> None:
    doc = osc(
        '<modify><node id="1" version="2" lat="1" lon="1"/>',
        f"{way(1, 2)}</modify>",
        '<delete><node id="3" version="9" visible="false"/></delete>',
    )
    keys = [g.key for g in parse_osm_change(doc).elements]
    assert keys == [(OsmType.NODE, 1), (OsmType.WAY, 1), (OsmType.NODE, 3)]


def test_bytes_input_is_accepted() -> None:
    assert parse_osm_change(osc(f"<modify>{way(1, 2)}</modify>").encode()).raw_element_count == 1


def test_empty_changeset_parses_to_nothing() -> None:
    parsed = parse_osm_change(osc())
    assert parsed.elements == () and parsed.raw_element_count == 0


# ------------------------------------------------------------------ safety


BILLION_LAUGHS = (
    HEADER
    + '<!DOCTYPE lolz [<!ENTITY lol "lol">'
    + '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
    + '<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
    + '<!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">]>'
    + '<osmChange version="0.6"><modify><node id="1" version="2" lat="1" lon="1">'
    + '<tag k="name" v="&lol4;"/></node></modify></osmChange>'
)


@pytest.mark.parametrize(
    "doc",
    [
        BILLION_LAUGHS,
        HEADER + '<!DOCTYPE osmChange [<!ENTITY x "y">]><osmChange version="0.6"/>',
        HEADER + '<!DOCTYPE osmChange SYSTEM "http://evil.example/x.dtd"><osmChange/>',
        HEADER
        + '<!DOCTYPE osmChange [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        + '<osmChange><modify><node id="1" version="2"><tag k="a" v="&xxe;"/></node></modify>'
        + "</osmChange>",
    ],
    ids=["billion-laughs", "internal-entity", "external-dtd", "xxe"],
)
def test_dtd_and_entities_are_rejected_with_a_typed_error(doc: str) -> None:
    with pytest.raises(XmlSafetyError):
        parse_osm_change(doc)
    with pytest.raises(XmlSafetyError):
        parse_osm_change(doc.encode())


def test_oversized_document_is_rejected_before_parsing() -> None:
    doc = osc(f"<modify>{way(1, 2)}</modify>")
    with pytest.raises(TooLargeError) as info:
        parse_osm_change(doc, max_bytes=100)
    assert info.value.limit == 100 and not isinstance(info.value, ElementCapExceededError)


def test_default_byte_cap_is_ten_megabytes() -> None:
    padding = "x" * (10 * 1024 * 1024 + 1)
    with pytest.raises(TooLargeError):
        parse_osm_change(osc(f"<!-- {padding} -->"))


def test_element_cap_is_enforced_with_a_typed_error() -> None:
    doc = osc("<modify>" + "".join(way(i, 2) for i in range(1, 8)) + "</modify>")
    with pytest.raises(ElementCapExceededError) as info:
        parse_osm_change(doc, max_elements=5)
    assert info.value.limit == 5
    assert isinstance(info.value, TooLargeError)
    assert parse_osm_change(doc, max_elements=7).raw_element_count == 7


def test_default_element_cap_is_5000() -> None:
    nodes = "".join(f'<node id="{i}" version="2" lat="1" lon="1"/>' for i in range(1, 5002))
    with pytest.raises(ElementCapExceededError) as info:
        parse_osm_change(osc(f"<modify>{nodes}</modify>"))
    assert info.value.limit == 5000
    ok = "".join(f'<node id="{i}" version="2" lat="1" lon="1"/>' for i in range(1, 5001))
    assert parse_osm_change(osc(f"<modify>{ok}</modify>")).raw_element_count == 5000


@pytest.mark.parametrize(
    "doc",
    [
        "not xml at all",
        HEADER + "<osmChange><modify><node id='1'",
        HEADER + "<osm><node id='1' version='1'/></osm>",
        osc("<replace/>"),
        osc('<modify><node version="2"/></modify>'),
        osc('<modify><node id="x" version="2"/></modify>'),
        osc('<modify><node id="1" version="0"/></modify>'),
        osc('<modify><node id="1" version="2" timestamp="yesterday"/></modify>'),
        osc('<modify><way id="1" version="2"><tag v="no-key"/></way></modify>'),
        osc(
            '<modify><relation id="1" version="2"><member type="blob" ref="1"/></relation></modify>'
        ),
        osc('<modify><node id="1" version="2" lat="north"/></modify>'),
    ],
)
def test_malformed_documents_are_parse_errors(doc: str) -> None:
    with pytest.raises(ParseError):
        parse_osm_change(doc)
