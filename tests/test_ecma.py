"""ecma: the importer and the refs and tools, over an invented bookmarked PDF."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from cursor_check import follow_list, follow_read
from pdffixture import standard

from primarysource import cli, registry
from primarysource.c2sp._fetch import sha256
from primarysource.ecma import ECMA, library
from primarysource.ecma.catalogue import Catalogue, Edition, Terms, parse_catalogue
from primarysource.ecma.catalogue import catalogue as packaged_catalogue
from primarysource.ecma.importer import import_edition, read_record
from primarysource.errors import LibError

pytest.importorskip("pypdf")

URL = "https://ecma-international.org/wp-content/uploads/ECMA-999_1st_edition.pdf"
PDF, IDS = standard()


@pytest.fixture(autouse=True)
def _pypdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.ecma._pdf.shutil.which", lambda _name: None)


def cat(data: bytes = PDF, url: str = URL) -> Catalogue:
    edition = Edition(
        "999",
        1,
        "ECMA-999",
        "Invented standard",
        "1st edition, January 2026",
        "https://example.invalid/999",
        url,
        len(data),
        sha256(data),
    )
    return Catalogue(
        Terms("Ecma text copyright policy", "volume", "https://example.invalid/t", "2026-11-12", "invented"),
        (edition,),
    )


def fetch(data: bytes = PDF):  # type: ignore[no-untyped-def]
    return lambda url, max_bytes: data


@pytest.fixture
def home(tmp_path: Path) -> Path:
    import_edition(tmp_path / "ecma", "999", cat=cat(), transport=fetch())
    return tmp_path / "ecma"


# --- the catalogue and the importer ----------------------------------------------------------------------------


def test_the_packaged_catalogue_pins_ecma_427() -> None:
    edition = packaged_catalogue().edition("427")
    assert (edition.designation, edition.edition, edition.size) == ("ECMA-427", 1, 2320437)
    assert edition.sha256 == "037180df99e7d7c26d910dc3adb3fa07c4fb787cc4bd29e43634de3802313825"
    assert packaged_catalogue().terms.placement == "volume"
    assert edition.source_url.startswith("https://ecma-international.org/")
    with pytest.raises(LibError, match="no Ecma standard 428"):
        packaged_catalogue().edition("428")
    with pytest.raises(ValueError, match="malformed"):
        raw = {"terms": {"licence": "l", "placement": "volume", "terms_url": "u", "terms_read": "d", "summary": "s"}}
        parse_catalogue(
            {
                **raw,
                "editions": [
                    {
                        "number": "x",
                        "edition": 1,
                        "designation": "d",
                        "title": "t",
                        "edition_name": "e",
                        "page_url": "p",
                        "source_url": "s",
                        "size": 1,
                        "sha256": "0" * 64,
                    }
                ],
            }
        )


def test_import_stores_the_pdf_its_extraction_and_a_record(tmp_path: Path) -> None:
    result = import_edition(tmp_path, "999", cat=cat(), transport=fetch())
    assert (result.key, result.sections, result.requests) == ("999-1", 7, 1)
    assert (tmp_path / "999-1.pdf").read_bytes() == PDF and not list(tmp_path.glob("*.part"))
    stored = json.loads((tmp_path / "999-1.json").read_text(encoding="utf-8"))
    assert (
        stored["designation"] == "ECMA-999"
        and stored["edition"] == "1st edition, January 2026"
        and stored["title"] == "Invented standard"
    )
    assert read_record(tmp_path)["editions"]["999-1"]["sha256"] == sha256(PDF)


def test_import_refuses_a_wrong_digest_a_non_pdf_and_a_foreign_host(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="does not match the pinned"):
        import_edition(tmp_path, "999", cat=cat(), transport=fetch(PDF + b"\n"))
    html = b"<html>an error page</html>"
    with pytest.raises(LibError, match="not a PDF"):
        import_edition(tmp_path, "999", cat=cat(html), transport=fetch(html))
    with pytest.raises(LibError, match="refusing"):
        import_edition(tmp_path, "999", cat=cat(url="https://evil.invalid/x.pdf"), transport=fetch())
    assert not list(tmp_path.glob("999-1*"))


def test_import_from_a_file_and_a_pdf_that_does_not_read_leaves_nothing(tmp_path: Path) -> None:
    mine = tmp_path / "mine.pdf"
    mine.write_bytes(PDF)
    result = import_edition(tmp_path / "a", "999", file=mine, cat=cat())
    assert result.requests == 0 and (tmp_path / "a" / "999-1.json").is_file()
    junk = b"%PDF-1.4 truncated"
    with pytest.raises(LibError, match="could not read the PDF"):
        import_edition(tmp_path / "b", "999", cat=cat(junk), transport=fetch(junk))
    assert not list((tmp_path / "b").glob("999-1*"))
    with pytest.raises(LibError, match="cannot read"):
        import_edition(tmp_path / "c", "999", file=tmp_path / "missing.pdf", cat=cat())


# --- refs and tools --------------------------------------------------------------------------------------------


def test_refs_accept_the_prefix_the_designation_and_an_edition() -> None:
    assert library.parse_ref("ecma:427§5.3¶2").doc == "427"
    assert library.parse_ref("ECMA-427@1§A").section == "A"
    assert library.parse_ref("427").section is None
    assert library.parse_ref("427§contributing-to-this-specification").section == "contributing-to-this-specification"
    for bad in ("", "ecma:", "427:1-3", "427#x", "§5.3", "abc§1"):
        with pytest.raises(LibError):
            library.parse_ref(bad)


def test_read_a_clause_a_sentence_and_a_page(home: Path) -> None:
    text = library.read("ecma:999§2", home=home)
    assert text.startswith(
        "A gasket is a seal.\nA sprocket is a toothed wheel.\n§2.1 Gasket\nA gasket MUST be round.\n§2.2 Sprocket\n"
    )
    assert (
        "cite: Ecma International, ECMA-999, Invented standard, 1st edition, January 2026, §2 Terms. https://example.invalid/999"
        in text
    )
    assert "unit: sentence" in text and "span: sha256:" in text
    assert library.read("ECMA-999@1§2¶2", home=home).startswith("A sprocket is a toothed wheel.\n")
    assert library.read("999§A", home=home).startswith("The registry lists flanges.")
    assert library.read("999§bibliography¶2", home=home).startswith("So is everything here.")
    paged = library.read("999§2", max_tokens=1, home=home)
    assert "next: ecma:999@1§2¶2" in paged
    assert library.read("ecma:999@1§2¶2", max_tokens=1, home=home).startswith("A sprocket is a toothed wheel.")
    whole = library.read("999", max_tokens=5000, home=home)
    assert whole.startswith("§1 Scope\n") and "§bibliography Bibliography\nRFC 9999 is invented." in whole


def test_a_read_cursor_is_a_ref_that_read_accepts_back(home: Path) -> None:
    for ref in ("999§2", "ecma:999", "999§2¶2"):
        whole = library.read(ref, max_tokens=5000, home=home).rsplit("\n\ncite: ", 1)[0]
        bodies, refs = follow_read(lambda r: library.read(r, max_tokens=1, home=home), ref)
        assert len(refs) > 1 and "\n".join(bodies) == whole
    hits = library.search("a", limit=100, home=home).rstrip("\n").split("\n")
    assert follow_list(lambda start: library.search("a", limit=2, start=start, home=home)) == hits


def test_unknown_things_fail_with_a_remedy(home: Path, tmp_path: Path) -> None:
    with pytest.raises(LibError) as raised:
        library.read("999§2.11", home=home)
    assert "did you mean: 2.1" in raised.value.hint
    with pytest.raises(LibError, match="span has"):
        library.read("999§2¶99", home=home)
    with pytest.raises(LibError, match="ECMA-427 is not imported") as missing:
        library.read("427§5.3", home=home)
    assert missing.value.action == "primarysource ecma import 427"
    assert missing.value.hint == "ecma_docs lists the catalogue"
    with pytest.raises(LibError, match="ECMA-999@2 is not imported"):
        library.read("999@2§1", home=home)
    with pytest.raises(LibError, match="not imported"):
        library.read("999", home=tmp_path / "empty")


def test_an_edited_pdf_or_extraction_is_detected(home: Path) -> None:
    (home / "999-1.pdf").write_bytes(PDF + b"\n")
    with pytest.raises(LibError, match="does not match its recorded sha256"):
        library.read("999§1", home=home)
    (home / "999-1.pdf").write_bytes(PDF)
    (home / "999-1.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(LibError, match="cannot read the import"):
        library.read("999§1", home=home)
    (home / "999-1.json").write_text('{"pages": 1}', encoding="utf-8")
    with pytest.raises(LibError, match="malformed"):
        library.read("999§1", home=home)


def test_outline_search_cite_and_docs(home: Path) -> None:
    outline = library.outline("999", home=home)
    assert outline.splitlines()[0].startswith(
        "ECMA-999 Invented standard, 1st edition, January 2026  [999@1, 5 pages]"
    )
    assert "  2.1 Gasket  ecma:999@1§2.1  (p. 2)" in outline
    hits = library.search("sprocket teeth", home=home)
    assert hits.startswith("ecma:999@1§2.2¶1: A sprocket SHOULD have teeth.")
    assert "relaxed: only some" in library.search("sprocket zzzz", home=home)
    assert library.search("zzzz", home=home) == "no matches\n"
    cited = library.cite("ecma:999§2.1¶1", home=home)
    from primarysource.model import span_hash

    assert f"span: {span_hash('A gasket MUST be round.')}" in cited
    assert "ECMA-999, Invented standard, 1st edition, January 2026, §2.1 Gasket ¶1." in cited
    listing = library.docs(home=home)
    assert "not imported  ECMA-427@1" in listing and "placement volume" in listing


# --- the command and the server --------------------------------------------------------------------------------


@pytest.fixture
def registered(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(home.parent))
    return home


def test_the_command_runs_through_the_core_cli(registered: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["ecma", "read", "999§2.1¶1"]) == 0
    assert capsys.readouterr().out.startswith("A gasket MUST be round.")
    for args in (["outline", "999"], ["search", "gasket"], ["cite", "999§3"], ["docs"]):
        assert cli.main(["ecma", *args]) == 0
    capsys.readouterr()
    assert cli.main(["ecma", "read", "999§9.9"]) == 1
    assert "hint:" in capsys.readouterr().err


def test_the_collection_object_declares_prefix_unit_and_grammar() -> None:
    assert (ECMA.name, ECMA.prefix, ECMA.unit.value) == ("ecma", "ecma_", "sentence")
    assert ECMA.grammar.parse("ECMA-427@1§5.3¶2").section == "5.3"


def test_the_server_exposes_prefixed_tools(registered: Path) -> None:
    pytest.importorskip("mcp")
    from mcp.server.mcpserver.exceptions import ToolError

    server = registry.attribute(ECMA, ECMA.server, "server")
    assert [t.name for t in asyncio.run(server.list_tools())] == [
        "ecma_read",
        "ecma_search",
        "ecma_outline",
        "ecma_cite",
        "ecma_docs",
    ]
    assert "A gasket MUST be round." in str(asyncio.run(server.call_tool("ecma_read", {"ref": "999§2.1¶1"})))
    with pytest.raises(ToolError, match="hint: did you mean"):
        asyncio.run(server.call_tool("ecma_read", {"ref": "999§2.11"}))


def test_the_collection_grammar_is_the_real_parser() -> None:
    grammar = ECMA.grammar
    ref = grammar.parse("ecma:427§5.3¶2")
    assert grammar.parse(grammar.format(ref)) == ref
    with pytest.raises(LibError):
        grammar.parse("427#x")
