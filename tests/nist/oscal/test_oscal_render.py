"""OSCAL rendering and indexing against a small synthetic catalogue (not a NIST file)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from primarysource.nist.ingest import oscal
from primarysource.nist.ingest.index import read_index
from primarysource.nist.ingest.oscal import OscalError, OscalSource
from primarysource.nist.models import Section
from primarysource.nist.server.corpus import load_corpus
from primarysource.nist.server.tools import cite, read

NS = "http://csrc.nist.gov/ns/oscal/1.0"

CATALOG = f"""<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="{NS}" uuid="00000000-0000-4000-8000-000000000000">
  <metadata>
    <title>Synthetic
      Catalogue   One</title>
    <last-modified>2025-03-04T10:00:00Z</last-modified>
    <version>1.0</version>
    <prop name="publication-status" value="Final"/>
  </metadata>
  <group id="xx">
    <title>Family</title>
    <part name="overview"><p>Group prose that belongs to no control.</p></part>
    <control id="xx-1">
      <title>First   control</title>
      <param id="xx-1_prm1"><label>a time period</label></param>
      <param id="xx-1_prm2"><select how-many="one"><choice>remove</choice><choice>disable</choice></select></param>
      <part name="statement">
        <p>Review every <insert type="param" id-ref="xx-1_prm1"/> and <insert type="param" id-ref="xx-1_prm2"/>.</p>
        <part name="item">
          <prop name="label" value="a."/>
          <p>Define the <q>scope</q>;</p>
          <part name="item">
            <prop name="label" value="1."/>
            <p>nested item</p>
          </part>
        </part>
      </part>
      <part name="guidance"><p>Guidance
        text.</p></part>
      <control id="xx-1.1">
        <title>Enhancement</title>
        <part name="statement"><p>Enhancement text.</p></part>
      </control>
    </control>
    <control id="xx-2">
      <title>Second control</title>
      <part name="statement"><p>Second text.</p></part>
    </control>
  </group>
  <group id="yy">
    <title>Other family</title>
    <group id="yy-sub">
      <title>Subgroup</title>
      <control id="yy-1"><title>Deep control</title><part name="statement"><p>Deep text.</p></part></control>
    </group>
  </group>
</catalog>
"""


def render() -> tuple[list[str], dict[str, Section]]:
    text, sections = oscal.render_catalog(oscal.parse_catalog(CATALOG.encode()))
    assert text.endswith("\n")
    return text.split("\n")[:-1], {s.id: s for s in sections}


def body(lines: list[str], section: Section) -> list[str]:
    return lines[section.start_line - 1 : section.end_line]


def test_one_section_per_control_in_document_order() -> None:
    _, sections = render()
    assert list(sections) == ["xx-1", "xx-1.1", "xx-2", "yy-1"]


def test_id_is_kept_verbatim_and_heading_is_the_normalised_title() -> None:
    lines, sections = render()
    assert sections["xx-1"].heading == "First control"
    assert sections["xx-1.1"].heading == "Enhancement"
    assert lines[sections["xx-1"].start_line - 1] == "xx-1 First control"
    assert lines[sections["xx-1.1"].start_line - 1] == "xx-1.1 Enhancement"


def test_nested_control_is_its_own_section_and_not_inside_the_parent() -> None:
    lines, sections = render()
    parent, child = sections["xx-1"], sections["xx-1.1"]
    assert parent.end_line < child.start_line
    assert "Enhancement text." not in "\n".join(body(lines, parent))
    assert body(lines, child) == ["xx-1.1 Enhancement", "Enhancement text."]


def test_part_prose_items_labels_and_indentation() -> None:
    lines, sections = render()
    assert body(lines, sections["xx-1"]) == [
        "xx-1 First control",
        "Review every [a time period] and [one: remove | disable].",
        '  a. Define the "scope";',
        "    1. nested item",
        "Guidance:",
        "  Guidance text.",
    ]


def test_sections_are_contiguous_ranges_that_do_not_overlap() -> None:
    lines, sections = render()
    ordered = sorted(sections.values(), key=lambda s: s.start_line)
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        assert earlier.end_line < later.start_line
        assert lines[earlier.end_line] == ""
    assert ordered[-1].end_line == len(lines) - 1


def test_controls_inside_nested_groups_are_found() -> None:
    _, sections = render()
    assert "yy-1" in sections


def test_group_prose_is_not_attributed_to_a_control() -> None:
    lines, _ = render()
    assert "Group prose" not in "\n".join(lines)


def test_wrong_namespace_is_rejected() -> None:
    plain = CATALOG.replace(f'xmlns="{NS}"', "")
    with pytest.raises(OscalError, match="catalog"):
        oscal.render_catalog(oscal.parse_catalog(plain.encode()))


def test_duplicate_control_id_is_rejected() -> None:
    dup = CATALOG.replace('id="xx-2"', 'id="xx-1"')
    with pytest.raises(OscalError, match="duplicate"):
        oscal.render_catalog(oscal.parse_catalog(dup.encode()))


def test_dtd_is_refused() -> None:
    with pytest.raises(OscalError, match="DTD"):
        oscal.parse_catalog(b'<!DOCTYPE x [<!ENTITY a "b">]><x/>')


def test_metadata_title_date_and_status() -> None:
    root = oscal.parse_catalog(CATALOG.encode())
    assert oscal.catalog_metadata(root) == (
        "Synthetic Catalogue One",
        "2025-03",
        "final",
    )
    bare = CATALOG.replace('<prop name="publication-status" value="Final"/>', "")
    assert (
        oscal.catalog_metadata(oscal.parse_catalog(bare.encode()))[2] == "unspecified"
    )


def source(data: bytes, **over: str) -> OscalSource:
    fields = {
        "doc_id": "syn-oscal",
        "url": oscal.ALLOWED_HOST_PREFIX + "c" * 40 + "/x.xml",
        "number": "SYN 1 (OSCAL)",
        "title": "Synthetic Catalogue One",
        "date": "2025-03",
        "status": "final",
        "commit": "c" * 40,
        "blob": oscal.git_blob_sha(data),
    }
    fields.update(over)
    return OscalSource(**fields)


def test_build_document_writes_xml_text_and_matching_index_entry(
    tmp_path: Path,
) -> None:
    data = CATALOG.encode()
    document = oscal.build_document(source(data), tmp_path, data)
    assert (tmp_path / "syn-oscal.xml").read_bytes() == data
    assert document.text_file == "syn-oscal.txt"
    assert document.sha256 == hashlib.sha256(data).hexdigest()
    assert document.number == "SYN 1 (OSCAL)"
    lines = (tmp_path / "syn-oscal.txt").read_text(encoding="utf-8").split("\n")
    first = document.sections[0]
    assert lines[first.start_line - 1] == "xx-1 First control"


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"blob": "0" * 40}, "blob sha"),
        ({"title": "Other"}, "title"),
        ({"date": "2024-01"}, "date"),
        ({"status": "withdrawn"}, "status"),
    ],
)
def test_build_document_refuses_a_file_that_differs_from_its_pin(
    tmp_path: Path, over: dict[str, str], message: str
) -> None:
    data = CATALOG.encode()
    with pytest.raises(OscalError, match=message):
        oscal.build_document(source(data, **over), tmp_path, data)
    assert not (tmp_path / "syn-oscal.txt").exists()


def test_merge_keeps_existing_entries_untouched_and_replaces_by_doc_id(
    tmp_path: Path,
) -> None:
    data = CATALOG.encode()
    pdf = {
        "doc_id": "pdf-1",
        "number": "N",
        "title": "T",
        "date": "2024-01",
        "status": "final",
        "url": "https://example.test/a.pdf",
        "sha256": "a" * 64,
        "text_file": "pdf-1.txt",
        "sections": [{"id": "1", "heading": "H", "start_line": 1, "end_line": 2}],
    }
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"schema": 1, "documents": [pdf]}), encoding="utf-8")
    document = oscal.build_document(source(data), tmp_path, data)
    oscal.merge_into_index(index, [document])
    oscal.merge_into_index(index, [document])
    documents = read_index(index)
    assert [d.doc_id for d in documents] == ["pdf-1", "syn-oscal"]
    assert json.loads(index.read_text(encoding="utf-8"))["documents"][0] == pdf


def test_merge_refuses_to_overwrite_an_unreadable_index(tmp_path: Path) -> None:
    index = tmp_path / "index.json"
    index.write_text("{not json", encoding="utf-8")
    with pytest.raises(OscalError):
        oscal.merge_into_index(index, [])
    assert index.read_text(encoding="utf-8") == "{not json"


def test_run_from_file_indexes_and_the_server_can_cite_a_control(
    tmp_path: Path,
) -> None:
    data = CATALOG.encode()
    entry = source(data)
    (tmp_path / "sources.toml").write_text(
        "[[oscal]]\n"
        + "".join(f'{k} = "{getattr(entry, k)}"\n' for k in oscal._REQUIRED),
        encoding="utf-8",
    )
    catalog_file = tmp_path / "in.xml"
    catalog_file.write_bytes(data)
    assert oscal.run(tmp_path, {"syn-oscal": catalog_file}, []) == 0
    corpus = load_corpus(tmp_path / "corpus")
    assert (
        cite(corpus, "syn-oscal", "xx-1.1").splitlines()[0] == "SYN 1 (OSCAL) §xx-1.1"
    )
    assert "Enhancement text." in read(corpus, "syn-oscal", "xx-1.1")


def test_sources_parser_rejects_unpinned_or_foreign_urls() -> None:
    good = (
        '[[oscal]]\ndoc_id = "a-oscal"\nnumber = "n"\ntitle = "t"\ndate = "2025-01"\n'
        f'status = "final"\ncommit = "{"c" * 40}"\nblob = "{"b" * 40}"\n'
    )
    url = oscal.ALLOWED_HOST_PREFIX + "c" * 40 + "/x.xml"
    assert len(oscal.parse_oscal_sources(good + f'url = "{url}"\n')) == 1
    with pytest.raises(OscalError, match="under"):
        oscal.parse_oscal_sources(good + 'url = "https://example.test/x.xml"\n')
    prefix = oscal.ALLOWED_HOST_PREFIX
    with pytest.raises(OscalError, match="pinned"):
        oscal.parse_oscal_sources(good + f'url = "{prefix}main/x.xml"\n')
    with pytest.raises(OscalError, match="doc_id"):
        oscal.parse_oscal_sources(good.replace("a-oscal", "a-pdf") + f'url = "{url}"\n')
