"""The core hardened XML reader (`cl.reader_xml_hardened`) on hostile and ordinary input. Every vector is invented
here; the iana and bbf wrappers keep their own tests in `test_iana_xml_model.py` and `test_bbf.py`."""

from __future__ import annotations

import re
import socket
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.readers import xml as xmlsafe
from primarysource.readers.xml import (
    XmlForbidden,
    XmlMalformed,
    XmlRefused,
    XmlTooDeep,
    XmlTooLarge,
    localname,
    parse,
)

BIG = 1_000_000

LAUGHS = (
    b'<?xml version="1.0"?><!DOCTYPE z [<!ENTITY a "aaaaaaaaaa">'
    b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><z>&c;</z>'
)
PARAMETER = b'<!DOCTYPE z [<!ENTITY % p SYSTEM "http://127.0.0.1:9/p.dtd"> %p;]><z/>'


def test_an_ordinary_document_keeps_text_tails_and_attributes() -> None:
    root = parse(b'<?xml version="1.0" encoding="UTF-8"?><a x="1">hi<b>t</b>tail<c/></a>', BIG)
    assert (root.tag, root.get("x"), root.text) == ("a", "1", "hi")
    assert [c.tag for c in root] == ["b", "c"] and root[0].text == "t" and root[0].tail == "tail"
    assert parse(b"<x>&lt;&amp;&gt;&#65;</x>", BIG).text == "<&>A"
    assert parse(b"\xef\xbb\xbf<a>\xc3\xa9</a>", BIG).text == "é"  # a UTF-8 byte-order mark is fine


@pytest.mark.parametrize(
    "hostile",
    [
        LAUGHS,
        PARAMETER,
        b"<!DOCTYPE z><z/>",
        b"<! DOCTYPE z><z/>",
        b"<!doctype z []><z/>",
        b'<z><!-- <!ENTITY a "x"> --></z>',  # stricter than expat: a declaration's text is refused anywhere
        b"<z><![CDATA[<!ELEMENT z ANY>]]></z>",
    ],
)
def test_any_declaration_is_forbidden(hostile: bytes) -> None:
    with pytest.raises(XmlForbidden, match="document type declarations"):
        parse(hostile, BIG)


def test_a_declaration_hidden_by_a_wide_encoding_is_named_as_a_declaration() -> None:
    for codec in ("utf-16", "utf-16-le", "utf-32"):
        hidden = '<!DOCTYPE z [<!ENTITY e "x">]><z>&e;</z>'.encode(codec)
        with pytest.raises(XmlForbidden, match="document type declarations"):
            parse(hidden, BIG)
    with pytest.raises(XmlForbidden, match="only UTF-8"):
        parse("<z/>".encode("utf-16"), BIG)
    with pytest.raises(XmlForbidden, match="only UTF-8"):
        parse(b'<?xml version="1.0" encoding="ISO-8859-1"?><z/>', BIG)


def test_an_external_entity_opens_no_file_and_no_socket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("NOT FOR THE PARSER", encoding="utf-8")
    opened: list[object] = []
    monkeypatch.setattr(socket.socket, "connect", lambda _self, address: opened.append(address))
    for target in (secret.as_uri(), "http://127.0.0.1:9/x"):
        with pytest.raises(XmlForbidden):
            parse(f'<!DOCTYPE x [<!ENTITY e SYSTEM "{target}">]><x>&e;</x>'.encode(), BIG)
    assert opened == []


def test_the_expat_handlers_refuse_even_without_the_byte_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scan before parsing is one layer; the handlers are the other, and each holds alone."""
    monkeypatch.setattr("primarysource.readers.xml._DECLARATION", re.compile(rb"(?!)"))
    for hostile in (LAUGHS, PARAMETER, b"<!DOCTYPE z><z/>"):
        with pytest.raises(XmlForbidden, match="document type declarations"):
            parse(hostile, BIG)


def test_processing_instructions_are_refused_unless_the_caller_drops_them() -> None:
    for raw in (b'<?xml-stylesheet href="x.xsl"?><x/>', b"<x><?php evil ?></x>"):
        with pytest.raises(XmlForbidden, match="processing instructions"):
            parse(raw, BIG)
    assert parse(b"<x><?pi data?>t</x>", BIG, ignore_processing_instructions=True).text == "t"


@pytest.mark.parametrize("raw", [b"", b"<r>", b"<r></s>", b"not xml", b"<r/><r/>", b"<r>&nope;</r>"])
def test_empty_truncated_and_malformed_input_is_refused(raw: bytes) -> None:
    with pytest.raises(XmlMalformed):
        parse(raw, BIG)


def test_the_size_bound_is_inclusive_and_checked_before_any_parser_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    assert parse(b"<a/>", 4).tag == "a"

    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a parser was created")

    monkeypatch.setattr("primarysource.readers.xml.expat.ParserCreate", explode)
    with pytest.raises(XmlTooLarge, match="exceeds the limit"):
        parse(b"<a/>", 3)


def test_bounds_on_depth_elements_attributes_and_text() -> None:
    parse(b"<a>" * 32 + b"</a>" * 32, BIG)
    with pytest.raises(XmlTooDeep, match="nesting deeper than 32"):
        parse(b"<a>" * 33 + b"</a>" * 33, BIG)
    doc = b"<r>" + b"<e/>" * 10 + b"</r>"
    assert len(parse(doc, BIG, max_elements=11)) == 10
    with pytest.raises(XmlTooLarge, match="more than 10 elements"):
        parse(doc, BIG, max_elements=10)
    many = b" ".join(b'a%d="1"' % i for i in range(17))
    with pytest.raises(XmlTooLarge, match="attributes"):
        parse(b"<e " + many + b"/>", BIG)
    with pytest.raises(XmlTooLarge, match="attribute value"):
        parse(b'<e a="' + b"x" * 4097 + b'"/>', BIG)
    with pytest.raises(XmlTooLarge, match="text longer"):
        parse(b"<e>" + b"x" * 101 + b"</e>", BIG, max_text=100)
    with pytest.raises(XmlTooLarge, match="text longer"):
        parse(b"<e><f/>" + b"x" * 101 + b"</e>", BIG, max_text=100)  # a tail is text too


def test_names_split_on_the_namespace_uri_or_stay_raw_when_asked() -> None:
    doc = b'<r xmlns="urn:invented:one" xmlns:p="urn:invented:two" p:k="v"><p:x/><y xmlns=""/></r>'
    root = parse(doc, BIG)
    assert localname(root.tag) == ("urn:invented:one", "r")
    assert root.get("{urn:invented:two}k") == "v"
    assert [localname(c.tag) for c in root] == [("urn:invented:two", "x"), ("", "y")]
    with pytest.raises(XmlMalformed):
        parse(b'<p:r q:k="1"/>', BIG)  # an undeclared prefix is not well formed under namespaces
    raw = parse(b'<p:r q:k="1"/>', BIG, namespaces=False)
    assert raw.tag == "p:r" and raw.get("q:k") == "1"


def test_a_refusal_is_a_lib_error_with_a_hint_the_caller_can_set() -> None:
    with pytest.raises(LibError) as caught:
        parse(LAUGHS, BIG)
    assert isinstance(caught.value, XmlRefused) and caught.value.hint == xmlsafe.DEFAULT_HINT
    assert caught.value.message.startswith("XML refused: ") and caught.value.reason in caught.value.message
    with pytest.raises(XmlRefused) as named:
        parse(b"", BIG, hint="import it again")
    assert named.value.hint == "import it again"


def test_input_that_is_not_bytes_or_a_negative_limit_is_a_programming_error() -> None:
    with pytest.raises(TypeError):
        parse("<a/>", BIG)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="negative"):
        parse(b"<a/>", -1)
