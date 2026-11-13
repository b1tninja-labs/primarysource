"""CAVP .rsp and ACVP JSON parsing, refs and bounds, over invented vectors (none of NIST's data is in the tree)."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from primarysource.cavp import model, parse
from primarysource.cavp.model import format_ref, parse_ref
from primarysource.errors import LibError

SIGVER = """\
#  CAVS 11.0
#  "SigVer" information
#  Generated on never

[P-256,SHA-256]

Msg = aa
Qx = 01
Result = F (3 - S changed)

Msg = bb
Qx = 02
Result = P

[P-384,SHA-384]

Msg = cc
Qx = 03
Result = P
"""

RSA = """\
# "SigVer PKCS#1 Ver 1.5" information

[mod = 1024]

n = 1111

SHAAlg = SHA1
e = 03
Msg = aa
Result = F

SHAAlg = SHA256
e = 03
Msg = bb
Result = P

n = 2222

SHAAlg = SHA1
e = 05
Msg = cc
Result = P
"""


def rsp(text: str, **kw: str) -> model.VectorSet:
    args = {
        "set_id": "cavp/test/SigVer.rsp",
        "algorithm": "ECDSA",
        "source_url": "u",
        "sha256": "a",
        "member_sha256": "b",
    }
    return parse.parse_rsp(text.encode(), **(args | kw))


def test_rsp_groups_cases_header_and_mode() -> None:
    s = rsp(SIGVER)
    assert [g.label for g in s.groups] == ["P-256,SHA-256", "P-384,SHA-384"]
    assert [len(g.cases) for g in s.groups] == [2, 1]
    assert s.groups[0].cases[0].fields == {"Msg": "aa", "Qx": "01", "Result": "F (3 - S changed)"}
    assert [c.id for c in s.groups[0].cases] == ["1", "2"]
    assert s.mode == "SigVer"
    assert s.header[0] == "#  CAVS 11.0"
    assert s.groups[0].params == {"tokens": ["P-256", "SHA-256"]}


def test_rsp_modulus_block_is_context_merged_into_following_cases() -> None:
    g = rsp(RSA).groups[0]
    assert g.params == {"mod": "1024"}
    assert [(c.fields["n"], c.fields["Msg"]) for c in g.cases] == [("1111", "aa"), ("1111", "bb"), ("2222", "cc")]
    assert len(g.cases) == 3


def test_rsp_count_is_the_case_id_when_unique_else_position() -> None:
    unique = rsp("[x]\n\nCOUNT = 7\nK = a\n\nCOUNT = 9\nK = b\n")
    assert [c.id for c in unique.groups[0].cases] == ["7", "9"]
    repeated = rsp("[x]\n\nCOUNT = 0\nK = a\n\nCOUNT = 0\nK = b\n")
    assert [c.id for c in repeated.groups[0].cases] == ["1", "2"]


def test_rsp_repeated_key_starts_a_new_case_and_blank_lines_are_optional() -> None:
    assert [c.fields for c in rsp("[x]\nK = a\nV = 1\nK = b\nV = 2\n").groups[0].cases] == [
        {"K": "a", "V": "1"},
        {"K": "b", "V": "2"},
    ]


def test_rsp_consecutive_brackets_join_and_duplicate_labels_are_disambiguated() -> None:
    s = rsp("[ENCRYPT]\n[L = 1024, N = 160, SHA-1]\n\nK = a\n\n[ENCRYPT]\n[L = 1024, N = 160, SHA-1]\n\nK = b\n")
    assert [g.label for g in s.groups] == ["ENCRYPT,L = 1024, N = 160, SHA-1", "ENCRYPT,L = 1024, N = 160, SHA-1~2"]
    assert s.groups[0].params == {"L": "1024", "N": "160", "tokens": ["ENCRYPT", "SHA-1"]}


def test_rsp_cases_before_any_bracket_go_in_group_all() -> None:
    assert rsp("K = a\n").groups[0].label == "all"


def test_rsp_rejects_junk_with_a_line_number_and_empty_files() -> None:
    with pytest.raises(LibError, match="line 3"):
        rsp("[x]\nK = a\nthis is not a vector\n")
    with pytest.raises(LibError, match="no groups"):
        rsp("# only a comment\n")
    with pytest.raises(LibError, match="UTF-8"):
        parse.parse_rsp(
            b"\xff\xfe\x00", set_id="cavp/t/a.rsp", algorithm="A", source_url="", sha256="", member_sha256=""
        )


def test_rsp_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parse, "MAX_CASES", 2)
    with pytest.raises(LibError, match="more than 2 cases"):
        rsp("[x]\n\nK = 1\n\nK = 2\n\nK = 3\n")
    monkeypatch.setattr(parse, "MAX_LINE_BYTES", 10)
    with pytest.raises(LibError, match="over 10 characters"):
        rsp("[x]\nK = " + "a" * 20 + "\n")
    monkeypatch.setattr(parse, "MAX_FIELDS_PER_CASE", 1)
    with pytest.raises(LibError, match="more than 1 fields"):
        rsp("[x]\nA = 1\nB = 2\n")
    monkeypatch.setattr(parse, "MAX_GROUPS", 1)
    with pytest.raises(LibError, match="more than 1 groups"):
        rsp("[a]\nK = 1\n[b]\nK = 2\n")


def _zip(**files: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_zip_member_is_read_in_memory_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    archive = _zip(**{"a.rsp": b"hello"})
    assert parse.read_member(archive, "a.rsp") == b"hello"
    with pytest.raises(LibError, match="no member 'b.rsp'.*a.rsp"):
        parse.read_member(archive, "b.rsp")
    with pytest.raises(LibError, match="not a zip"):
        parse.read_member(b"nope", "a.rsp")
    monkeypatch.setattr(parse, "MAX_SOURCE_BYTES", 3)
    with pytest.raises(LibError, match="over the 3 byte cap"):
        parse.read_member(archive, "a.rsp")


PROMPT = {
    "vsId": 0,
    "algorithm": "ECDSA",
    "mode": "sigVer",
    "revision": "1.0",
    "testGroups": [
        {"tgId": 1, "curve": "P-256", "tests": [{"tcId": 1, "message": "AA"}, {"tcId": 2, "message": "BB"}]},
        {"tgId": 2, "curve": "P-384", "tests": [{"tcId": 3, "message": "CC"}]},
    ],
}
EXPECTED = {
    "vsId": 0,
    "testGroups": [
        {"tgId": 1, "tests": [{"tcId": 1, "testPassed": False}, {"tcId": 2, "testPassed": True}]},
        {"tgId": 2, "tests": [{"tcId": 3, "testPassed": True}]},
    ],
}


def acvp(prompt: object, expected: object | None = None) -> model.VectorSet:
    return parse.parse_acvp(
        json.dumps(prompt).encode(),
        None if expected is None else json.dumps(expected).encode(),
        set_id="acvp/ECDSA-SigVer-1.0",
        source_url="u",
        sha256="a",
        member_sha256="a",
    )


def test_acvp_joins_prompt_and_expected_by_group_and_case() -> None:
    s = acvp(PROMPT, EXPECTED)
    assert (s.algorithm, s.mode, s.revision) == ("ECDSA", "sigVer", "1.0")
    assert [g.label for g in s.groups] == ["1", "2"]
    assert s.groups[0].params == {"curve": "P-256"}
    case = s.groups[0].cases[1]
    assert (case.id, case.fields, case.expected) == ("2", {"message": "BB"}, {"testPassed": True})
    assert s.case_count == 3


def test_acvp_accepts_a_server_response_list_and_no_expected_file() -> None:
    s = acvp([{"acvVersion": "1.0"}, PROMPT])
    assert s.case_count == 3 and s.groups[0].cases[0].expected == {}


def test_acvp_refuses_mismatched_or_malformed_files() -> None:
    stray = {"testGroups": [{"tgId": 9, "tests": [{"tcId": 1, "testPassed": True}]}]}
    with pytest.raises(LibError, match="1 cases that prompt does not"):
        acvp(PROMPT, stray)
    with pytest.raises(LibError, match="no testGroups"):
        acvp({"vsId": 0})
    with pytest.raises(LibError, match="not valid JSON"):
        parse.parse_acvp(b"{", None, set_id="acvp/x", source_url="", sha256="", member_sha256="")


def test_refs_round_trip_and_reject_bad_ones() -> None:
    text = "nist:cavp/ecdsa/SigVer.rsp#[P-256,SHA-256]/3"
    ref = parse_ref(text)
    assert (ref.set_id, ref.group, ref.case) == ("cavp/ecdsa/SigVer.rsp", "P-256,SHA-256", "3")
    assert str(ref) == text
    assert parse_ref("cavp/ecdsa/SigVer.rsp").group is None
    assert str(parse_ref("nist:acvp/ECDSA-SigVer-1.0#1/3")) == "nist:acvp/ECDSA-SigVer-1.0#1/3"
    assert parse_ref("nist:cavp/rsa/a.rsp#[mod = 1024]").case is None
    for bad in (
        "nist:rfc/9000",
        "nist:cavp/x/../y",
        "nist:cavp/a/b.rsp#P-256",
        "nist:cavp/a/b.rsp#",
        "nist:cavp/a/b.rsp#[]",
    ):
        with pytest.raises(LibError):
            parse_ref(bad)
    with pytest.raises(LibError):
        format_ref("cavp/a/b.rsp", None, "3")


def test_the_collection_grammar_is_the_real_parser() -> None:
    from primarysource.cavp import COLLECTION

    grammar = COLLECTION.grammar
    for text in (
        "nist:cavp/ecdsa/SigVer.rsp",
        "nist:cavp/ecdsa/SigVer.rsp#[P-256,SHA-256]/3",
        "nist:acvp/ECDSA-SigVer-1.0#1/3",
    ):
        assert grammar.format(grammar.parse(text)) == text
    with pytest.raises(LibError):
        grammar.parse("not a ref")
