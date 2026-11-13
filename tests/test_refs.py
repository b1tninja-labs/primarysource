from __future__ import annotations

import pytest

from primarysource.errors import LibError
from primarysource.refs import Ref, RefGrammar

RFC = RefGrammar(r"(?:RFC|BCP|STD)\d+")
ITU = RefGrammar(r"[A-Z]\.\d+(?:#[\d-]+)?")
ZIM = RefGrammar(r"[a-z0-9_.-]+", section_pattern=r"[^\s#¶]+")


@pytest.mark.parametrize(
    ("grammar", "text", "expected"),
    [
        (RFC, "RFC9000", Ref(doc="RFC9000")),
        (RFC, "RFC9000§9.6", Ref(doc="RFC9000", section="9.6")),
        (RFC, "RFC9000§9.6¶2", Ref(doc="RFC9000", section="9.6", para=2)),
        (RFC, "RFC9000::9.6", Ref(doc="RFC9000", section="9.6")),
        (RFC, " RFC9000 § 9.6 ¶ 2 ", Ref(doc="RFC9000", section="9.6", para=2)),
        (RFC, "RFC9000#table-2", Ref(doc="RFC9000", anchor="table-2")),
        (RFC, "RFC9000:2964-2979", Ref(doc="RFC9000", lines=(2964, 2979))),
        (RFC, "§9.6", Ref(section="9.6")),
        (RFC, "RFC9000§A.1", Ref(doc="RFC9000", section="A.1")),
        (ITU, "X.690§11.6¶2", Ref(doc="X.690", section="11.6", para=2)),
        (ITU, "X.690#2008-11§8.1", Ref(doc="X.690#2008-11", section="8.1")),
        (
            ZIM,
            "devdocs_en_flask§blueprints/index#why-blueprints¶3",
            Ref(doc="devdocs_en_flask", section="blueprints/index", anchor="why-blueprints", para=3),
        ),
    ],
)
def test_the_three_existing_ref_spellings_parse(grammar: RefGrammar, text: str, expected: Ref) -> None:
    assert grammar.parse(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "nonsense here",
        "RFC9000§",
        "RFC9000¶2",
        "RFC9000§9.6:1-2",
        "RFC9000:9-3",
        "RFC9000:0-3",
        "RFC9000§9.6¶0",
    ],
)
def test_a_string_that_is_not_a_ref_is_refused_with_a_hint(text: str) -> None:
    with pytest.raises(LibError) as raised:
        RFC.parse(text)
    assert raised.value.hint


@pytest.mark.parametrize(
    "text", ["RFC9000", "RFC9000§9.6", "RFC9000§9.6¶2", "RFC9000#table-2", "RFC9000:2964-2979", "§9.6"]
)
def test_format_is_the_inverse_of_parse_for_canonical_spellings(text: str) -> None:
    assert RefGrammar.format(RFC.parse(text)) == text


def test_the_ascii_spelling_formats_to_the_canonical_one() -> None:
    assert RefGrammar.format(RFC.parse("RFC9000 :: 9.6")) == "RFC9000§9.6"
