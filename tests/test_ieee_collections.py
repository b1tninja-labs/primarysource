"""The posix and ieee802 collections: registration, ref grammars, the catalogue, and the no-corpus tripwire."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from primarysource import registry
from primarysource.errors import LibError
from primarysource.ieee import IEEE802, POSIX
from primarysource.ieee.catalogue import IEEE802_TERMS, POSIX_2024, POSIX_TERMS, parse
from primarysource.model import Unit
from primarysource.refs import Ref

PACKAGE = Path(__file__).resolve().parents[1] / "primarysource" / "ieee"


def test_both_collections_load_by_name_from_the_builtin_table() -> None:
    assert {"posix", "ieee802"} <= set(registry.available())
    assert registry.load("posix") is POSIX and POSIX.prefix == "posix_" and POSIX.unit is Unit.BLOCK
    assert registry.load("ieee802") is IEEE802 and IEEE802.prefix == "ieee802_" and IEEE802.unit is Unit.SENTENCE


def test_posix_has_its_own_extra_and_ieee802_keeps_ieee_in_the_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    targets = registry._targets()
    assert targets["posix"].install == 'pip install "primarysource[posix]"'
    assert targets["ieee802"].install == 'pip install "primarysource[ieee]"'
    monkeypatch.setitem(sys.modules, "primarysource.ieee", None)  # the subpackage cannot be imported
    for name, hint in (("posix", "[posix]"), ("ieee802", "[ieee]")):
        with pytest.raises(LibError, match="not installed") as caught:
            registry.load(name, targets)
        assert caught.value.hint == f'pip install "primarysource{hint}"'


def test_the_posix_extra_needs_no_dependency_and_ieee_still_carries_pypdf() -> None:
    import tomllib

    extras = tomllib.loads((PACKAGE.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]
    assert extras["posix"] == [] and extras["ieee"] == ["pypdf>=5"]


def test_both_collections_load_without_pypdf() -> None:
    """In a fresh interpreter where `pypdf` cannot be imported: describing ieee802 needs no pypdf, and posix
    never does; only importing a PDF needs it."""
    code = (
        "import sys; sys.modules['pypdf'] = None\n"
        "from primarysource import registry\n"
        "print(registry.load('posix').name, registry.load('ieee802').name)"
    )
    done = subprocess.run(  # noqa: S603 - our own interpreter and a fixed program
        [sys.executable, "-c", code], cwd=PACKAGE.parents[1], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["posix", "ieee802"]


@pytest.mark.parametrize(
    ("text", "ref"),
    [
        ("posix-2024§functions/open", Ref("posix-2024", "functions/open")),
        ("posix-2024§functions/open#tag_17_372_03", Ref("posix-2024", "functions/open", None, "tag_17_372_03")),
        ("posix-2024§utilities/pax#tag_20_94_04¶3", Ref("posix-2024", "utilities/pax", 3, "tag_20_94_04")),
        ("posix-2024§basedefs/stdio.h", Ref("posix-2024", "basedefs/stdio.h")),
        ("posix-2024§basedefs/V1_chap03#tag_03_01¶1", Ref("posix-2024", "basedefs/V1_chap03", 1, "tag_03_01")),
        ("posix-2024§utilities/[", Ref("posix-2024", "utilities/[")),
        ("posix-2024§xbd", Ref("posix-2024", "xbd")),
    ],
)
def test_posix_refs_round_trip(text: str, ref: Ref) -> None:
    assert POSIX.grammar.parse(text) == ref
    assert POSIX.grammar.format(ref) == text
    assert POSIX.grammar.parse(text.replace("§", "::")) == ref


@pytest.mark.parametrize(
    ("text", "ref"),
    [
        ("802.1Q-2022§5.4", Ref("802.1Q-2022", "5.4")),
        ("802.3-2022§30.2.2¶4", Ref("802.3-2022", "30.2.2", 4)),
        ("802.1AB-2016§A.1", Ref("802.1AB-2016", "A.1")),
        ("802.15.4-2020§6", Ref("802.15.4-2020", "6")),
        ("802.3bz-2016§126", Ref("802.3bz-2016", "126")),
    ],
)
def test_ieee802_refs_round_trip(text: str, ref: Ref) -> None:
    assert IEEE802.grammar.parse(text) == ref
    assert IEEE802.grammar.format(ref) == text


@pytest.mark.parametrize("text", ["posix§functions/open", "posix-2024§Functions/open", "posix-2024§functions/a b"])
def test_malformed_posix_refs_are_refused(text: str) -> None:
    with pytest.raises(LibError):
        POSIX.grammar.parse(text)


@pytest.mark.parametrize("text", ["802.1Q§5.4", "IEEE802.1Q-2022§5", "802.1Q-22§5"])
def test_malformed_ieee802_refs_are_refused(text: str) -> None:
    with pytest.raises(LibError):
        IEEE802.grammar.parse(text)


def test_the_posix_pin_is_the_measured_archive() -> None:
    assert POSIX_2024.archive == "susv5.tgz" and POSIX_2024.size == 4_962_222
    assert POSIX_2024.sha256 == "11c7ee3e98febe3d58d03a02885d0fab9a3564d06a9b02742d9d138ae341a957"
    assert POSIX_2024.designations[:2] == ("IEEE Std 1003.1-2024", "The Open Group Base Specifications Issue 8")
    assert POSIX_2024.designations == (
        "IEEE Std 1003.1-2024",
        "The Open Group Base Specifications Issue 8",
        "ISO/IEC/IEEE 9945:2026",
    )
    assert POSIX_2024.title.startswith("IEEE/Open Group Standard") and POSIX_2024.title.endswith("Issue 8")
    assert POSIX_2024.edition_date == "2024-06-14"
    assert POSIX_TERMS.placement == IEEE802_TERMS.placement == "volume"


def test_a_malformed_catalogue_is_refused() -> None:
    good = json.loads((PACKAGE / "catalogue.json").read_text(encoding="utf-8"))
    good["collections"]["posix"]["placement"] = "layer-ish"
    with pytest.raises(ValueError, match="placement"):
        parse(json.dumps(good))
    good["collections"]["posix"]["placement"] = "volume"
    good["collections"]["posix"]["editions"][0]["sha256"] = "ABC"
    with pytest.raises(ValueError, match="sha256"):
        parse(json.dumps(good))


# --- tripwire: no corpus text in the tree -----------------------------------------------------------------------

CODE_LIMIT = 96_000
DATA_LIMIT = 16_000
NOTICE = "IEEE and The Open " + "Group, All Rights Reserved"  # split so this file does not match itself


def test_the_ieee_package_holds_code_and_a_small_catalogue_only() -> None:
    for path in PACKAGE.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix == ".py":
            assert path.stat().st_size <= CODE_LIMIT, f"{path.name} is suspiciously large for code"
        else:
            assert path.name == "catalogue.json", f"{path.name}: only code and the catalogue belong here"
            assert path.stat().st_size <= DATA_LIMIT, "the catalogue holds metadata, not text"


def test_no_file_in_the_tree_carries_the_standard_s_notice() -> None:
    root = PACKAGE.parents[1]
    for folder in ("primarysource", "tests", "tools", "docs"):
        for path in (root / folder).rglob("*"):
            if path.is_file() and path.suffix in {".py", ".json", ".md", ".html", ".txt"}:
                assert NOTICE not in path.read_text(encoding="utf-8", errors="replace"), path


def test_the_posix_family_is_metadata_and_agrees_with_the_edition() -> None:
    from primarysource.ieee.catalogue import POSIX_FAMILY

    by_name = {e.designation: e for e in POSIX_FAMILY}
    assert len(by_name) == len(POSIX_FAMILY) == 17
    current = by_name[POSIX_2024.designations[0]]
    assert current.status == "Active Standard" and current.published == POSIX_2024.edition_date
    assert by_name["IEEE Std 1003.1-2017"].status == "Superseded Standard"
    assert by_name["IEEE Std 1003.13-2003"].status.startswith("Inactive-Reserved")
    assert all(e.url.startswith("https://standards.ieee.org/") and e.read for e in POSIX_FAMILY)


def test_the_1003_1_chain_is_stated_both_ways() -> None:
    from primarysource.ieee.catalogue import family_entry

    chain = ["2024", "2017", "2008", "2001", "1990"]
    for newer, older in zip(chain, chain[1:], strict=False):
        assert f"1003.1-{older}" in family_entry(f"IEEE Std 1003.1-{newer}").supersedes
        assert f"1003.1-{newer}" in family_entry(f"IEEE Std 1003.1-{older}").superseded_by
    assert family_entry("IEEE Std 1003.1-2024").superseded_by == ()


def test_what_the_page_did_not_state_is_marked_not_filled() -> None:
    from primarysource.ieee.catalogue import POSIX_FAMILY, family_entry

    assert "superseded_by" in family_entry("IEEE Std 1003.13-2003").not_stated
    assert "published" in family_entry("IEEE Std 1003.5-1998").not_stated
    assert family_entry("IEEE Std 1003.5-1998").published is None
    oddity = family_entry("IEEE 9945-2-2003")
    assert oddity.title is None and "title" in oddity.not_stated
    for entry in POSIX_FAMILY:
        assert set(entry.not_stated) <= {"title", "published", "superseded_by", "supersedes", "revision_of"}
        for field in ("title", "published"):
            assert (getattr(entry, field) is None) == (field in entry.not_stated)


def test_family_metadata_carries_no_document_text_and_unknown_is_a_lib_error() -> None:
    from primarysource.ieee.catalogue import POSIX_FAMILY, family_entry

    assert all(len(e.notes) < 600 and len(e.title or "") < 250 for e in POSIX_FAMILY)
    assert family_entry("ieee std 1003.1-2008").published == "2008-12-01"
    with pytest.raises(LibError) as err:
        family_entry("IEEE Std 1003.99")
    assert "IEEE Std 1003.1-2024" in err.value.hint
