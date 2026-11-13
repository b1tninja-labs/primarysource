"""The usb.ids parser and ref spelling over an invented file, then over hostile input."""

from __future__ import annotations

import pytest
from usbids_fixture import SAMPLE

from primarysource.errors import LibError
from primarysource.usbids.parse import Limits, format_ref, parse, parse_ref


def test_every_section_and_level_is_parsed_with_its_header() -> None:
    ids = parse(SAMPLE)
    assert (ids.version, ids.date) == ("2099.01.02", "2099-01-02 03:04:05")
    assert ids.problem_count == 0 and ids.latin1_lines == 0
    assert ids.counts() == {
        "vendor": 3, "device": 3, "interface": 1, "class": 3, "subclass": 1, "protocol": 2, "at": 1, "hid": 1,
        "item": 1, "bias": 1, "phy": 1, "usage page": 2, "usage": 3, "language": 1, "dialect": 1, "hcc": 1, "vt": 1,
    }  # fmt: skip
    interface = ids.get("vendor", ("0001", "0003", "01"))
    assert interface is not None and interface.name == "Control interface" and interface.level_name == "interface"
    assert interface.ref == "usbids:0001:0003:01"
    protocol = ids.get("class", ("09", "00", "02"))
    assert protocol is not None and protocol.name == "TT per port" and protocol.line == 22


def test_ids_are_lowercased_and_names_are_trimmed_of_a_doubled_space() -> None:
    ids = parse(SAMPLE)
    assert ids.get("vendor", ("0b0b",)) is not None
    mini = ids.get("vendor", ("0001", "0003"))
    assert mini is not None and mini.name == "Frobnicator Mini"


def test_children_belong_to_the_last_parent_in_file_order() -> None:
    ids = parse(SAMPLE)
    gizmo = ids.get("vendor", ("0001",))
    assert gizmo is not None
    assert [k.name for k in ids.kids(gizmo)] == ["Frobnicator 2000", "Frobnicator Mini"]
    sub = ids.get("class", ("09", "00"))
    assert sub is not None and [k.key[-1] for k in ids.kids(sub)] == ["00", "02"]
    # the same id under two vendors is two entries
    assert ids.get("vendor", ("0a0a", "0001")) is not None and ids.get("vendor", ("0001", "0002")) is not None


def test_hid_country_codes_are_decimal() -> None:
    assert parse(b"HCC 09  German\n").problem_count == 0
    assert parse(b"HCC 0a  German\n").problem_count == 1


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("\t0002  orphan\n", "no parent"),
        ("0001  Vendor\n\t\t01  skipped a level\n", "no parent"),
        ("0001  Vendor\n\t\t\t01  too deep\n", "not allowed"),
        ("XX 01  unknown tag\n", "unknown section tag"),
        ("AT 0201  Mic\n\t01  child of a flat table\n", "no level 1"),
        ("12345  five digits\n", "not a valid vendor id"),
        ("zzzz  not hex\n", "not a valid vendor id"),
        ("0001 one space\n", "not '<id>  <name>'"),
        ("0001  \n", "not '<id>  <name>'"),
        ("0001  bell\x07\n", "control character"),
        ("  0001  space indented\n", "not '<id>  <name>'"),
        ("\tC 09  tag on a child\n", "not allowed"),
        ("0001  " + "x" * 600 + "\n", "over 512"),
        ("0001  A\n0001  B\n", "duplicate usbids:0001"),
        ("C 09  Hub\n\t00  U\n\t00  again\n", "duplicate usbids:class/09/00"),
    ],
)
def test_a_line_that_cannot_be_placed_is_a_problem_not_an_entry(text: str, reason: str) -> None:
    ids = parse(text.encode())
    assert ids.problem_count >= 1 and reason in ids.problems[0].reason


def test_a_duplicate_keeps_the_first_entry_and_orphans_its_children() -> None:
    ids = parse(b"0001  First\n0001  Second\n\t0002  child of the duplicate\n")
    assert ids.get("vendor", ("0001",)).name == "First"  # type: ignore[union-attr]
    assert ids.get("vendor", ("0001", "0002")) is None
    assert [p.reason for p in ids.problems] == ["duplicate usbids:0001", "indented line with no parent"]


def test_hostile_bytes_are_refused_or_confined() -> None:
    with pytest.raises(LibError, match="NUL"):
        parse(b"0001  a\x00b\n")
    with pytest.raises(LibError, match="bytes, over the 10 limit"):
        parse(b"0001  Vendor\n", Limits(data_bytes=10))
    with pytest.raises(LibError, match="over 3 lines"):
        parse(b"#\n" * 5, Limits(lines=3))
    with pytest.raises(LibError, match="over 2 entries"):
        parse(b"0001  a\n0002  b\n0003  c\n", Limits(entries=2))
    ids = parse(b"junk\n" * 50, Limits(problems=5))
    assert ids.problem_count == 50 and len(ids.problems) == 5 and not ids.entries


def test_a_latin1_line_is_read_and_counted_not_refused() -> None:
    ids = parse(b"0001  V\n\t0002  Acute \xb4 accent\n\t0003  Utf8 \xc2\xae\n")
    assert ids.latin1_lines == 1 and ids.problem_count == 0
    assert ids.get("vendor", ("0001", "0002")).name == "Acute \xb4 accent"  # type: ignore[union-attr]
    assert ids.get("vendor", ("0001", "0003")).name == "Utf8 ®"  # type: ignore[union-attr]


def test_a_bom_crlf_and_trailing_space_are_tolerated() -> None:
    ids = parse(b"\xef\xbb\xbf# Version: 1\r\n0001  Vendor \r\n\t0002  Dev\t\r\n")
    assert ids.version == "1" and ids.problem_count == 0
    assert ids.get("vendor", ("0001",)).name == "Vendor"  # type: ignore[union-attr]


def test_a_directive_looking_comment_inside_the_body_is_not_a_version() -> None:
    ids = parse(b"# Version: 1\n0001  V\n# Version: 2\n")
    assert ids.version == "1"


def test_a_file_that_is_not_usb_ids_parses_to_nothing_with_problems() -> None:
    ids = parse(b"<html><body>404</body></html>\n")
    assert not ids.entries and ids.problem_count == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("usbids:1d6b", ("vendor", ("1d6b",))),
        ("USBIDS:1D6B:0002", ("vendor", ("1d6b", "0002"))),
        ("1d6b:0002", ("vendor", ("1d6b", "0002"))),
        ("usbids:0001:0003:01", ("vendor", ("0001", "0003", "01"))),
        ("usbids:class/09", ("class", ("09",))),
        ("usbids:class/09/00/02", ("class", ("09", "00", "02"))),
        (" usbids:hut/01/006 ", ("hut", ("01", "006"))),
        ("usbids:lang/0409/01", ("lang", ("0409", "01"))),
        ("usbids:hcc/09", ("hcc", ("09",))),
    ],
)
def test_refs_parse_and_format_round_trip(text: str, expected: tuple[str, tuple[str, ...]]) -> None:
    assert parse_ref(text) == expected
    assert parse_ref(format_ref(*expected)) == expected


@pytest.mark.parametrize(
    "text",
    [
        "", "usbids:", "usbids:1d6", "usbids:1d6b:", "usbids:1d6b:0002:0:0", "usbids:g000", "usbids:class",
        "usbids:class/", "usbids:class/09/00/02/01", "usbids:class/xyz", "usbids:vendor/1d6b", "usbids:nope/01",
        "usbids:class/../09", "usbids:class/09/../../etc", "usbids:hcc/0a", "usbids:at/01", "usbids:١d6b",
        "x" * 100, "usbids:class/09;rm", "usbids:%31d6b",
    ],
)  # fmt: skip
def test_a_string_that_names_nothing_is_refused_with_a_hint(text: str) -> None:
    with pytest.raises(LibError) as caught:
        parse_ref(text)
    assert caught.value.hint or "too long" in caught.value.message


def test_the_collection_grammar_is_the_real_parser() -> None:
    from primarysource.usbids import COLLECTION

    grammar = COLLECTION.grammar
    for text in ("usbids:1d6b", "usbids:1d6b:0002", "usbids:class/09/00/02", "usbids:hut/01/002"):
        assert grammar.format(grammar.parse(text)) == text
    assert grammar.format(grammar.parse("1D6B:0002")) == "usbids:1d6b:0002"
    with pytest.raises(LibError):
        grammar.parse("usbids:zz")
    with pytest.raises(LibError):
        grammar.parse("usbids§1d6b")
