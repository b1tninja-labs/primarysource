"""posix search on the core FTS5 index, over invented pages (see `ieee_posixfixture`)."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
from cursor_check import follow_list, split
from ieee_posixfixture import archive

from primarysource import cli
from primarysource.errors import LibError
from primarysource.ieee import posix, posix_index
from primarysource.ieee.catalogue import Edition
from primarysource.ieee.importer import INSTALL_RECORD, import_posix


@pytest.fixture
def installed(tmp_path: Path) -> tuple[Path, Edition]:
    path, pinned = archive(tmp_path)
    home = tmp_path / "home"
    import_posix(path, home=home, pinned=pinned)
    return home, pinned


@pytest.fixture
def indexed(installed: tuple[Path, Edition]) -> tuple[Path, Edition]:
    home, pinned = installed
    posix_index.build(edition=pinned, home=home)
    return installed


def _refs(text: str) -> list[str]:
    return re.findall(r"^(posix-2024§\S+)", text, flags=re.M)


def test_build_indexes_one_section_per_heading(indexed: tuple[Path, Edition]) -> None:
    home, pinned = indexed
    # frob 4 headings, the chapter 1 + 3 headings, `[` 1 heading
    assert posix_index.build(edition=pinned, home=home) == 4 + 4 + 1


def test_a_heading_match_outranks_a_body_match(indexed: tuple[Path, Edition]) -> None:
    home, pinned = indexed
    out = posix_index.search("twiddle", edition=pinned, home=home)
    first = _refs(out)[0]
    assert first.startswith("posix-2024§functions/frob#tag_99_01_02_01"), out  # heading "Twiddling in Detail"
    assert "#tag_99_01_01" in out and "#tag_99_01_02¶1" in out, "body matches follow, with their block"


def test_a_hit_is_a_ref_that_read_accepts(indexed: tuple[Path, Edition]) -> None:
    home, pinned = indexed
    out = posix_index.search("gaskets", edition=pinned, home=home)
    refs = _refs(out)
    assert "posix-2024§functions/frob#tag_99_01_02¶2" in refs
    for ref in refs:
        assert posix.read(ref, edition=pinned, home=home).strip()
    body, footer = split(out)
    assert footer["unit"] == "block" and "cite" not in footer


def test_a_section_does_not_own_its_subsections_text(indexed: tuple[Path, Edition]) -> None:
    home, pinned = indexed
    refs = _refs(posix_index.search("flanges", edition=pinned, home=home))
    assert [r.split("¶")[0] for r in refs] == ["posix-2024§functions/frob#tag_99_01_02_01"]


def test_paging_cursor_round_trip(indexed: tuple[Path, Edition]) -> None:
    home, pinned = indexed
    everything = _refs(posix_index.search("gasket", limit=50, edition=pinned, home=home))
    assert len(everything) >= 4
    rows = follow_list(lambda start: posix_index.search("gasket", limit=2, start=start, edition=pinned, home=home))
    assert _refs("\n".join(rows)) == everything
    past = posix_index.search("gasket", start=500, edition=pinned, home=home)
    assert "no more sections" in past and "next:" not in past


def test_no_hits_means_nothing_matched(indexed: tuple[Path, Edition]) -> None:
    home, pinned = indexed
    assert posix_index.search("zzyzx", edition=pinned, home=home).startswith("nothing matches 'zzyzx'")


def test_some_terms_only_is_said_to_be_relaxed(indexed: tuple[Path, Edition]) -> None:
    home, pinned = indexed
    _, footer = split(posix_index.search("sprocket zzyzx", edition=pinned, home=home))
    assert footer["relaxed"].startswith("no section holds every query word")


def test_a_query_with_fts_syntax_is_searched_as_words(indexed: tuple[Path, Edition]) -> None:
    home, pinned = indexed
    posix_index.search('NEAR( "gasket OR', edition=pinned, home=home)  # does not raise
    with pytest.raises(LibError, match="at least one word"):
        posix_index.search("  ", edition=pinned, home=home)


def test_a_missing_index_names_the_command(installed: tuple[Path, Edition]) -> None:
    home, pinned = installed
    with pytest.raises(LibError) as caught:
        posix_index.search("gasket", edition=pinned, home=home)
    assert caught.value.action == "primarysource posix index" and "not been indexed" in caught.value.message


def test_search_without_an_import_says_how_to_import(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="not imported"):
        posix_index.search("gasket", home=tmp_path)


def test_a_stale_index_is_refused_until_rebuilt(indexed: tuple[Path, Edition]) -> None:
    home, pinned = indexed
    record = home / "posix" / pinned.id / INSTALL_RECORD
    data = json.loads(record.read_text(encoding="utf-8"))
    data["imported"] = "2099-01-01T00:00:00+00:00"
    record.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(LibError) as caught:
        posix_index.search("gasket", edition=pinned, home=home)
    assert "stale" in caught.value.message and caught.value.action == "primarysource posix index"
    posix_index.build(edition=pinned, home=home)
    assert _refs(posix_index.search("gasket", edition=pinned, home=home))


def test_a_rebuild_replaces_the_index_whole(indexed: tuple[Path, Edition]) -> None:
    home, pinned = indexed
    before = posix_index.search("gasket", limit=50, edition=pinned, home=home)
    assert posix_index.build(edition=pinned, home=home) == 9
    assert posix_index.search("gasket", limit=50, edition=pinned, home=home) == before
    assert not list((home / "posix").glob(".*.tmp"))


def test_a_corrupt_index_names_the_command(indexed: tuple[Path, Edition]) -> None:
    home, pinned = indexed
    posix_index.index_path(pinned, home).write_bytes(b"not a database" * 100)
    with pytest.raises(LibError) as caught:
        posix_index.search("gasket", edition=pinned, home=home)
    assert caught.value.action == "primarysource posix index"


def test_the_command_and_the_tool_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, pinned = archive(tmp_path)
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path / "home"))
    import_posix(path, home=tmp_path / "home", pinned=pinned)
    assert cli.main(["posix", "search", "gasket"]) == 1, "not indexed yet"
    assert "action: primarysource posix index" in capsys.readouterr().err
    assert cli.main(["posix", "index"]) == 0
    assert "indexed 9 section(s)" in capsys.readouterr().out
    assert cli.main(["posix", "search", "gasket", "--limit", "1"]) == 0
    assert "next: start=1" in capsys.readouterr().out
    pytest.importorskip("mcp")
    from primarysource.ieee.server import posix_server

    result = asyncio.run(posix_server.call_tool("posix_search", {"query": "flanges"}))
    assert "posix-2024§functions/frob#tag_99_01_02_01¶1" in str(result)
