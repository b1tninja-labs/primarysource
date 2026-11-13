"""cavp store, importer pins, tools, command line and MCP surface, over invented vectors."""

from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import zipfile
from pathlib import Path

import pytest
from cursor_check import follow_list, follow_read

from primarysource import cli, registry
from primarysource.cavp import COLLECTION, importer, tools
from primarysource.cavp.model import Store, sha256_bytes
from primarysource.errors import LibError

RSP = (
    '# "SigVer" information\n\n[P-256,SHA-256]\n\nMsg = AA\nQx = 01\nResult = F (3 - S changed)\n\n'
    "Msg = bb\nQx = 02\nResult = P\n\n[P-384,SHA-384]\n\nMsg = cc\nQx = 03\nResult = P\n"
)
PROMPT = {
    "algorithm": "ECDSA",
    "mode": "sigVer",
    "revision": "1.0",
    "testGroups": [{"tgId": 1, "curve": "P-256", "tests": [{"tcId": 1, "message": "AB12"}]}],
}
EXPECTED = {"testGroups": [{"tgId": 1, "tests": [{"tcId": 1, "testPassed": False}]}]}


def _zip(name: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, data)
    return buf.getvalue()


def _sources(artifact: bytes, prompt: bytes, expected: bytes) -> tuple[importer.Source, importer.Source]:
    cavp = importer.Source(
        "cavp/test/SigVer.rsp", "cavp", "ECDSA", "https://x/z.zip", sha256_bytes(artifact), "d/SigVer.rsp"
    )
    acvp = importer.Source(
        "acvp/ECDSA-SigVer-1.0", "acvp", "ECDSA", "https://x/prompt.json", sha256_bytes(prompt),
        expected_url="https://x/expected.json", expected_sha256=sha256_bytes(expected),
    )  # fmt: skip
    return cavp, acvp


@pytest.fixture
def store(tmp_path: Path) -> Store:
    archive = _zip("d/SigVer.rsp", RSP.encode())
    prompt, expected = json.dumps(PROMPT).encode(), json.dumps(EXPECTED).encode()
    cavp, acvp = _sources(archive, prompt, expected)
    s = Store(tmp_path / "store")
    (tmp_path / "z.zip").write_bytes(archive)
    (tmp_path / "p.json").write_bytes(prompt)
    (tmp_path / "e.json").write_bytes(expected)
    importer.import_files(s, cavp, tmp_path / "z.zip")
    importer.import_files(s, acvp, tmp_path / "p.json", tmp_path / "e.json")
    return s


def test_import_records_counts_and_both_digests(store: Store) -> None:
    entries = {e.id: e for e in store.entries()}
    assert (entries["cavp/test/SigVer.rsp"].groups, entries["cavp/test/SigVer.rsp"].cases) == (2, 3)
    loaded = store.load("cavp/test/SigVer.rsp")
    assert loaded.member_sha256 == sha256_bytes(RSP.encode()) != loaded.sha256


def test_a_wrong_or_missing_pin_is_refused(tmp_path: Path) -> None:
    archive = _zip("d/SigVer.rsp", RSP.encode())
    cavp, _ = _sources(archive, b"", b"")
    bad = dataclasses.replace(cavp, sha256="0" * 64)
    with pytest.raises(LibError, match="is not the pinned"):
        importer.build(bad, archive)
    unpinned = dataclasses.replace(cavp, sha256="")
    with pytest.raises(LibError, match="no sha256 pinned"):
        importer.build(unpinned, archive)
    _, acvp = _sources(b"", b"p", b"e")
    with pytest.raises(LibError, match="expectedResults file is needed"):
        importer.build(acvp, b"p")


def test_fetch_downloads_checks_and_stores_without_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _zip("d/SigVer.rsp", RSP.encode())
    cavp, _ = _sources(archive, b"", b"")
    seen: list[str] = []

    def opener(request: object, timeout: float) -> io.BytesIO:
        seen.append(getattr(request, "full_url", ""))
        return io.BytesIO(archive)

    entry = importer.fetch(Store(tmp_path), cavp, opener)
    assert seen == ["https://x/z.zip"] and entry.cases == 3
    with pytest.raises(LibError, match="only https"):
        importer.download("http://x/y")
    monkeypatch.setattr(importer, "MAX_SOURCE_BYTES", 2)
    with pytest.raises(LibError, match="larger than"):
        importer.download("https://x/y", opener)


def test_shipped_vectors_toml_pins_every_entry() -> None:
    found = importer.load_sources()
    assert {s.id for s in found} >= {"cavp/ecdsa/SigVer.rsp", "cavp/rsa/SigVer15_186-3.rsp", "acvp/ECDSA-SigVer-1.0"}
    for s in found:
        assert len(s.sha256) == 64 and s.url.startswith("https://")
        assert s.kind != "acvp" or (
            "/ACVP-Server/" in s.url and len(s.url.split("/ACVP-Server/")[1].split("/")[0]) == 40
        )


def test_toml_errors_name_the_file(tmp_path: Path) -> None:
    path = tmp_path / "v.toml"
    path.write_text(
        '[[vector]]\nid = "cavp/a/b.rsp"\nkind = "cavp"\nalgorithm = "A"\nurl = "u"\nsha256 = "s"\nbogus = 1\n'
    )
    with pytest.raises(LibError, match="unknown field"):
        importer.load_sources(path)


def test_read_a_case_in_full_with_cite_and_span(store: Store) -> None:
    out = tools.read(store, "nist:cavp/test/SigVer.rsp#[P-256,SHA-256]/1")
    assert out.startswith(
        "nist:cavp/test/SigVer.rsp#[P-256,SHA-256]/1\nMsg = AA\nQx = 01\nResult = F (3 - S changed)\n"
    )
    assert "cite: NIST CAVP ECDSA SigVer, group P-256,SHA-256, case 1; https://x/z.zip; sha256:" in out
    assert "span: sha256:" in out
    acvp = tools.read(store, "nist:acvp/ECDSA-SigVer-1.0#1/1")
    assert "message = AB12\nexpected.testPassed = false" in acvp


def test_read_a_set_and_a_group_and_page_them(store: Store) -> None:
    assert "nist:cavp/test/SigVer.rsp#[P-384,SHA-384]: 1 cases" in tools.read(store, "nist:cavp/test/SigVer.rsp")
    group = tools.read(store, "nist:cavp/test/SigVer.rsp#[P-256,SHA-256]", max_tokens=1)
    assert group.count("#[P-256,SHA-256]/") == 1 and "next: nist:cavp/test/SigVer.rsp#[P-256,SHA-256]¶2" in group
    assert "#[P-256,SHA-256]/2" in tools.read(store, "nist:cavp/test/SigVer.rsp#[P-256,SHA-256]¶2")
    for ref in ("nist:cavp/test/SigVer.rsp", "nist:cavp/test/SigVer.rsp#[P-256,SHA-256]"):
        whole = tools.read(store, ref).split("\n\ncite: ")[0]
        bodies, refs = follow_read(lambda r: tools.read(store, r, max_tokens=1), ref)
        assert len(refs) > 1 and "\n".join(bodies) == whole
    with pytest.raises(LibError, match="read whole"):
        tools.read(store, "nist:cavp/test/SigVer.rsp#[P-256,SHA-256]/1¶2")


def test_groups_and_find_page_by_a_zero_based_start(store: Store) -> None:
    every = tools.groups(store, "nist:cavp/test/SigVer.rsp").split("\n\ncite: ")[0].split("\n")
    assert len(every) > 1 and "next: start=1" in tools.groups(store, "nist:cavp/test/SigVer.rsp", max_tokens=1)
    assert follow_list(lambda start: tools.groups(store, "nist:cavp/test/SigVer.rsp", start, max_tokens=1)) == every
    with pytest.raises(LibError, match="0-based"):
        tools.groups(store, "nist:cavp/test/SigVer.rsp", -1)


def test_find_compares_hex_without_case_and_says_when_nothing_matches(store: Store) -> None:
    hit = tools.find(store, "nist:cavp/test/SigVer.rsp", "Msg", "0xAA")
    assert "#[P-256,SHA-256]/1: AA" in hit and hit.count("/1:") == 1
    assert "#1/1: AB12" in tools.find(store, "nist:acvp/ECDSA-SigVer-1.0", "message", "ab12")
    assert "#1/1: false" in tools.find(store, "nist:acvp/ECDSA-SigVer-1.0", "expected.testPassed", "false")
    assert tools.find(store, "nist:cavp/test/SigVer.rsp", "Msg", "zz").startswith("no case in")
    assert "cc" in tools.find(store, "nist:cavp/test/SigVer.rsp", "Msg", "cc", group="P-384,SHA-384")


def test_sets_filters_and_cite_carries_the_credit_line(store: Store) -> None:
    assert tools.sets(store, "acvp").splitlines() == [
        "nist:acvp/ECDSA-SigVer-1.0: ECDSA sigVer rev 1.0, 1 groups, 1 cases"
    ]
    assert tools.sets(store, "nothing").startswith("no vector set matches")
    cited = tools.cite(store, "nist:cavp/test/SigVer.rsp#[P-384,SHA-384]/1")
    assert "17 U.S.C. 105" in cited and "case 1" in cited


def test_errors_name_the_remedy(store: Store, tmp_path: Path) -> None:
    with pytest.raises(LibError, match="no vector set 'cavp/x/y.rsp'"):
        tools.read(store, "nist:cavp/x/y.rsp")
    with pytest.raises(LibError, match="no group 'nope'.*P-256,SHA-256"):
        tools.read(store, "nist:cavp/test/SigVer.rsp#[nope]")
    with pytest.raises(LibError, match="no case '9'"):
        tools.read(store, "nist:cavp/test/SigVer.rsp#[P-384,SHA-384]/9")
    with pytest.raises(LibError) as empty:
        tools.sets(Store(tmp_path / "empty"))
    assert empty.value.action == "primarysource cavp fetch"


def _home_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path / "home"))
    archive = _zip("d/SigVer.rsp", RSP.encode())
    cavp, _ = _sources(archive, b"", b"")
    (tmp_path / "z.zip").write_bytes(archive)
    s = Store(tmp_path / "home" / "cavp")
    importer.import_files(s, cavp, tmp_path / "z.zip")
    return s


def test_the_cavp_command_reads_the_store_in_the_collection_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _home_store(tmp_path, monkeypatch)
    from primarysource.cavp.cli import main

    assert main(["sets"]) == 0
    assert "nist:cavp/test/SigVer.rsp: ECDSA SigVer, 2 groups, 3 cases" in capsys.readouterr().out
    assert main(["read", "nist:cavp/test/SigVer.rsp#[P-384,SHA-384]/1"]) == 0
    assert "Msg = cc" in capsys.readouterr().out
    assert main(["find", "nist:cavp/test/SigVer.rsp", "Msg", "BB"]) == 0
    assert "#[P-256,SHA-256]/2" in capsys.readouterr().out
    assert main(["pin", str(tmp_path / "z.zip")]) == 0
    assert len(capsys.readouterr().out.strip()) == 64
    assert main(["read", "nist:cavp/test/SigVer.rsp#[nope]"]) == 1
    assert "hint: cavp_groups('nist:" in capsys.readouterr().err
    assert main(["import", "cavp/not/listed.rsp", str(tmp_path / "z.zip")]) == 1
    assert "not in vectors.toml" in capsys.readouterr().err


def test_the_collection_is_prefixed_and_loadable_by_target() -> None:
    target = registry._Target("primarysource.cavp:COLLECTION", "")  # noqa: SLF001
    assert registry.load("cavp", {"cavp": target}) is COLLECTION
    assert COLLECTION.prefix == "cavp_"
    assert COLLECTION.grammar.parse("cavp/ecdsa/SigVer.rsp").doc == "cavp/ecdsa/SigVer.rsp"
    assert cli.main(["collections"]) == 0


def test_server_tools_are_prefixed_read_only_and_errors_name_the_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    _home_store(tmp_path, monkeypatch)
    server = registry.attribute(COLLECTION, COLLECTION.server, "server")
    listed = asyncio.run(server.list_tools())
    assert [t.name for t in listed] == ["cavp_sets", "cavp_groups", "cavp_read", "cavp_find", "cavp_cite"]
    assert all(t.annotations is not None and t.annotations.read_only_hint for t in listed)
    ok = asyncio.run(server.call_tool("cavp_read", {"ref": "nist:cavp/test/SigVer.rsp#[P-384,SHA-384]/1"}))
    assert "Msg = cc" in str(ok)
    with pytest.raises(Exception, match="no vector set") as failed:
        asyncio.run(server.call_tool("cavp_read", {"ref": "nist:cavp/x/y.rsp"}))
    assert "hint: cavp_sets lists what is imported" in str(failed.value)
