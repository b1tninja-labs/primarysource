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


def test_both_collections_share_the_ieee_extra_in_their_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    targets = registry._targets()
    assert targets["posix"].install == targets["ieee802"].install == 'pip install "primarysource[ieee]"'
    monkeypatch.setitem(sys.modules, "primarysource.ieee", None)  # the subpackage cannot be imported
    with pytest.raises(LibError, match="not installed") as caught:
        registry.load("ieee802", targets)
    assert caught.value.hint == 'pip install "primarysource[ieee]"'


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
