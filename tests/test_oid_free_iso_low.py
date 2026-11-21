"""Arcs from the low-numbered free ISO extracts. Fixtures are invented, not a standard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.free_iso_low import children, covered
from primarysource.oid.tree import Node

_DOCS = (
    "75@2006",
    "79@2026",
    "2382-4@1999",
    "2382-7@2000",
    "2382-15@1999",
    "2382-16@1996",
    "2382-19@1989",
    "2382-36@2019",
    "2382-37@2022",
    "2382@2015",
    "5055@2021",
    "5140@2024",
    "5218@2022",
    "5230@2020",
    "5394@2024",
    "5962@2021",
)

_ASSIGNED = """
gasket OBJECT IDENTIFIER ::= { iso(1) sprocket(4) }
EXAMPLE: gasket OBJECT IDENTIFIER ::= { iso(1) sprocket(8) }
for example 9.9.9
"""

_MENTION = """
See ITU-T X.1524.
gasket(4) sprocket(8)
for example 1.2.3
"""


def _extract(directory: Path, doc: str, section_id: str, text: str) -> None:
    payload = {"doc": doc, "sections": [{"id": section_id, "text": text}]}
    name = doc.replace("@", "_") + ".json"
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def test_an_assignment_becomes_a_node(tmp_path: Path) -> None:
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    _extract(extracted, "75@2006", "page-3", _ASSIGNED)
    assert covered(extracted) == ("75@2006",)
    assert children(extracted) == (
        Node(
            oid="1.4",
            parent="1",
            names=("gasket", "sprocket"),
            unicode_labels=("4",),
            cite="iso:75@2006§page-3",
        ),
    )


def test_a_bibliographic_itu_t_mention_assigns_nothing(tmp_path: Path) -> None:
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    _extract(extracted, "5055@2021", "page-3", _MENTION)
    assert children(extracted) == ()


def test_a_missing_extract_directory_is_an_error(tmp_path: Path) -> None:
    missing = tmp_path / "extracted"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action
    with pytest.raises(LibError, match="not found"):
        covered(missing)


def test_a_missing_file_is_omitted(tmp_path: Path) -> None:
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    assert covered(extracted) == ()
    assert children(extracted) == ()


def test_covered_includes_the_imported_documents() -> None:
    first = collection_home("iso") / "extracted" / "75_2006.json"
    if not first.is_file():
        pytest.skip("ISO extract 75@2006 is not present")
    found = covered()
    for doc in _DOCS:
        assert doc in found
    assert children() == ()
