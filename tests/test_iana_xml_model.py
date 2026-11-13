"""The hardened XML reader on hostile input, and the model over invented registry XML."""

from __future__ import annotations

import pytest
from iana_fixture import NAME, widgets

from primarysource.errors import LibError
from primarysource.iana import xmlsafe
from primarysource.iana.model import from_tree, matches, number_of, numeric_range

LIMIT = 1_000_000


def parse(text: str | bytes, **kwargs: int) -> object:
    raw = text.encode("utf-8") if isinstance(text, str) else text
    return xmlsafe.parse(raw, LIMIT, **kwargs)


BILLION = (
    '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
    "<r>&b;&b;&b;</r>"
)
EXTERNAL = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>'
DOCTYPE_ONLY = '<!DOCTYPE registry SYSTEM "http://127.0.0.1:9/evil.dtd"><registry/>'


@pytest.mark.parametrize("hostile", [BILLION, EXTERNAL, DOCTYPE_ONLY])
def test_a_document_type_declaration_is_refused_before_any_entity_exists(hostile: str) -> None:
    with pytest.raises(xmlsafe.XmlRefused, match="document type declarations"):
        parse(hostile)


def test_an_undefined_entity_is_not_well_formed_so_it_is_refused() -> None:
    with pytest.raises(xmlsafe.XmlRefused, match="not well-formed"):
        parse("<r>&nope;</r>")


def test_encodings_other_than_utf8_are_refused() -> None:
    with pytest.raises(xmlsafe.XmlRefused, match="only UTF-8"):
        parse('<?xml version="1.0" encoding="ISO-8859-1"?><r/>')
    with pytest.raises(xmlsafe.XmlRefused, match="UTF-16"):
        parse("<r/>".encode("utf-16"))


@pytest.mark.parametrize("raw", [b"", b"<r>", b"<r></s>", b"not xml", b"<r/><r/>"])
def test_empty_truncated_and_malformed_input_is_refused(raw: bytes) -> None:
    with pytest.raises(xmlsafe.XmlRefused):
        parse(raw)


def test_limits_on_size_depth_elements_attributes_and_text() -> None:
    with pytest.raises(xmlsafe.XmlRefused, match="exceeds the limit"):
        xmlsafe.parse(b"<r>" + b"x" * 50 + b"</r>", 10)
    with pytest.raises(xmlsafe.XmlRefused, match="nesting deeper"):
        parse("<a>" * 40 + "</a>" * 40)
    with pytest.raises(xmlsafe.XmlRefused, match="more than 5 elements"):
        parse("<r>" + "<e/>" * 10 + "</r>", max_elements=5)
    with pytest.raises(xmlsafe.XmlRefused, match="attributes"):
        parse('<r a="1" b="2" c="3"/>', max_attributes=2)
    with pytest.raises(xmlsafe.XmlRefused, match="attribute value"):
        parse('<r a="' + "x" * 100 + '"/>', max_attribute_length=50)
    with pytest.raises(xmlsafe.XmlRefused, match="text longer"):
        parse("<r>" + "x" * 100 + "</r>", max_text=50)


def test_processing_instructions_are_dropped_because_iana_files_open_with_two() -> None:
    root = xmlsafe.parse(widgets(), LIMIT)
    assert root.tag == "{http://www.iana.org/assignments}registry"
    assert from_tree(root, NAME).name == NAME


def test_a_refusal_is_a_lib_error_that_names_a_remedy() -> None:
    with pytest.raises(LibError) as caught:
        parse(BILLION)
    assert caught.value.hint


def test_the_model_flattens_nested_registries_in_file_order_with_parents() -> None:
    file = from_tree(xmlsafe.parse(widgets(), LIMIT), NAME)
    assert [r.id for r in file.registries] == [NAME, f"{NAME}-1", f"{NAME}-2", f"{NAME}-sub"]
    assert file.registry(f"{NAME}-sub") is not None and file.registry(f"{NAME}-sub").parent == f"{NAME}-2"  # type: ignore[union-attr]
    assert file.updated == "2031-02-03" and file.title == "Widget Protocol Parameters"
    assert [r.id for r in file.children(f"{NAME}-2")] == [f"{NAME}-sub"]


def test_rows_keep_their_columns_citations_and_dates() -> None:
    file = from_tree(xmlsafe.parse(widgets(), LIMIT), NAME)
    messages = file.registry(f"{NAME}-1")
    assert messages is not None
    hello = messages.records[1]
    assert hello.ordinal == 2 and hello.key == "1" and hello.date == "2030-01-02"
    assert hello.fields == (("value", "1"), ("name", "HELLO"), ("description", "says hello to a gadget"))
    assert [x.ref for x in hello.xrefs if x.kind == "rfc"] == ["RFC9901§4.2"]
    assert [x.label for x in hello.xrefs] == ["RFC9901, Section 4.2", "Ada Example"]
    frob = messages.records[2]
    assert frob.updated == "2031-02-03"
    assert [x.label for x in frob.xrefs] == ["RFC9901", "draft-example-widget-frob-03", "RFC errata 4242"]
    assert "refs: RFC9901, draft-example-widget-frob-03, RFC errata 4242" in frob.text()


def test_inline_citations_in_notes_and_columns_are_spelled_out() -> None:
    file = from_tree(xmlsafe.parse(widgets(), LIMIT), NAME)
    messages = file.registry(f"{NAME}-1")
    assert messages is not None
    assert messages.notes == ("Values above 200 follow [RFC9902, Section 3.1] and are hardware specific.",)
    assert messages.records[4].field("description") == "see [RFC9902] for the format"
    assert messages.rules == ("Standards Action",) and messages.experts == ("Ada Example",)
    assert messages.ranges[0].value == "0-9" and messages.ranges[0].hex == "0x00-0x09"


def test_a_row_without_a_value_column_is_keyed_by_its_first_column_and_nested_xrefs_count() -> None:
    file = from_tree(xmlsafe.parse(widgets(), LIMIT), NAME)
    flags = file.registry(f"{NAME}-2")
    sub = file.registry(f"{NAME}-sub")
    assert flags is not None and sub is not None
    assert flags.records[0].key == "bit 3" and flags.records[0].xrefs[0].rfc == "BCP14"
    assert sub.records[0].field("reference") == "[RFC9903]"
    assert [x.rfc for x in sub.records[0].xrefs] == ["RFC9903"]


def test_a_tree_that_is_not_a_registry_or_the_wrong_one_is_refused() -> None:
    with pytest.raises(LibError, match="not an IANA <registry>"):
        from_tree(xmlsafe.parse(b"<html/>", LIMIT))
    with pytest.raises(LibError, match="not 'other-name'"):
        from_tree(xmlsafe.parse(widgets(), LIMIT), "other-name")


def test_numbers_ranges_and_hex_match_by_value() -> None:
    assert numeric_range("6-255") == (6, 255) and numeric_range("0x0010") == (16, 16)
    assert numeric_range("0x0000-0x007F") == (0, 127) and numeric_range("010") == (10, 10)
    assert numeric_range("*") is None and numeric_range("9-3") is None and numeric_range("1.2") is None
    assert number_of("0xC8") == 200 and number_of("5-6") is None
    file = from_tree(xmlsafe.parse(widgets(), LIMIT), NAME)
    records = file.registry(f"{NAME}-1").records  # type: ignore[union-attr]
    assert [r.key for r in records if matches(r, "150")] == ["11-199"]
    assert [r.key for r in records if matches(r, "200")] == ["0xC8"]
    assert [r.key for r in records if matches(r, "0xc8")] == ["0xC8"]
    assert [r.key for r in records if matches(r, "10")] == ["010"]
    assert [r.key for r in records if matches(r, "reserved")] == []
    assert [r.key for r in records if matches(r, "0xc8".upper())] == ["0xC8"]
