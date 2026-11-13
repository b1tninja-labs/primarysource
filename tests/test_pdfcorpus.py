from __future__ import annotations

import ast
import asyncio
import copy
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from primarysource import cli, pdfcorpus
from primarysource.errors import LibError
from primarysource.pdfcorpus import fts, tools
from primarysource.pdfcorpus.corpus import Corpus, CorpusError
from primarysource.pdfcorpus.corpus import load_corpus as _load
from primarysource.pdfcorpus.models import Document, Section
from primarysource.pdfcorpus.spec import CorpusSpec

FIXTURES = Path(__file__).parent / "pdfcorpus_fixtures" / "corpus"
SERVER_DIR = Path(pdfcorpus.__file__).parent
SPEC = CorpusSpec(
    name="synth",
    server_name="synthlib",
    env_var="SYNTHLIB_CORPUS",
    fetch_command="synthlib fetch",
    index_command="synthlib index",
    default_dir=lambda: Path("/nonexistent/synth"),
    instructions="Synthetic fixture corpus.",
    cite_example="SYNTH SP 000-1 §2.1",
)


def load_corpus(root: Path | None = None) -> Corpus:
    return _load(SPEC, root)


@pytest.fixture
def corpus() -> Corpus:
    return load_corpus(FIXTURES)


@pytest.fixture
def mutable_corpus(tmp_path: Path) -> Path:
    dst = tmp_path / "corpus"
    shutil.copytree(FIXTURES, dst)
    return dst


@pytest.fixture
def indexed(mutable_corpus: Path) -> Corpus:
    """The fixture corpus with its FTS5 search index built, as a fetch leaves it."""
    loaded = load_corpus(mutable_corpus)
    fts.build(loaded)
    return loaded


def _footer(text: str) -> dict[str, str]:
    """The `key: value` lines after the last blank line of a rendered result."""
    body, _, tail = text.rstrip("\n").rpartition("\n\n")
    lines = tail.splitlines() if body else []
    return dict(line.split(": ", 1) for line in lines if ": " in line and line.split(": ", 1)[0].isalpha())


def _write_index(root: Path, mutate: Callable[[dict[str, Any]], object]) -> None:
    data = json.loads((root / "index.json").read_text(encoding="utf-8"))
    mutate(data)
    (root / "index.json").write_text(json.dumps(data), encoding="utf-8")


# ---- loader -----------------------------------------------------------------


def test_load_valid(corpus: Corpus) -> None:
    assert [d.doc_id for d in corpus.documents] == ["synth-a", "synth-b"]
    assert corpus.documents[0].sections[2].id == "2.1"
    assert corpus.documents[0].sections[2].start_line == 10


def test_missing_corpus_points_at_fetch(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="not fetched yet") as ei:
        load_corpus(tmp_path)
    assert ei.value.action == "synthlib fetch"
    assert "synthlib fetch" not in ei.value.message


def test_env_var_selects_corpus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SYNTHLIB_CORPUS", str(tmp_path))
    with pytest.raises(CorpusError) as ei:
        load_corpus()
    assert str(tmp_path) in str(ei.value)


def test_invalid_json(mutable_corpus: Path) -> None:
    (mutable_corpus / "index.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CorpusError, match="not valid JSON"):
        load_corpus(mutable_corpus)


def test_wrong_schema_version(mutable_corpus: Path) -> None:
    _write_index(mutable_corpus, lambda d: d.update(schema=2))
    with pytest.raises(CorpusError, match="schema is 2"):
        load_corpus(mutable_corpus)


def test_missing_document_field(mutable_corpus: Path) -> None:
    _write_index(mutable_corpus, lambda d: d["documents"][0].pop("sha256"))
    with pytest.raises(CorpusError, match=r"documents\[0\].*sha256"):
        load_corpus(mutable_corpus)


def test_unknown_document_field(mutable_corpus: Path) -> None:
    _write_index(mutable_corpus, lambda d: d["documents"][1].update(extra="x"))
    with pytest.raises(CorpusError, match=r"documents\[1\].*unknown field.*extra"):
        load_corpus(mutable_corpus)


def test_bad_section_range(mutable_corpus: Path) -> None:
    _write_index(mutable_corpus, lambda d: d["documents"][0]["sections"][0].update(start_line=9))
    with pytest.raises(CorpusError, match="after end_line"):
        load_corpus(mutable_corpus)


def test_section_field_wrong_type(mutable_corpus: Path) -> None:
    _write_index(mutable_corpus, lambda d: d["documents"][0]["sections"][0].update(end_line="6"))
    with pytest.raises(CorpusError, match="end_line.*positive integer"):
        load_corpus(mutable_corpus)


def test_duplicate_doc_id(mutable_corpus: Path) -> None:
    _write_index(
        mutable_corpus,
        lambda d: d["documents"].append(copy.deepcopy(d["documents"][0])),
    )
    with pytest.raises(CorpusError, match="duplicate doc_id.*synth-a"):
        load_corpus(mutable_corpus)


def test_missing_text_file(mutable_corpus: Path) -> None:
    (mutable_corpus / "synth-a.txt").unlink()
    c = load_corpus(mutable_corpus)
    with pytest.raises(CorpusError, match="is missing") as ei:
        c.text_lines(c.documents[0])
    assert ei.value.action == "synthlib fetch"


def test_text_file_cannot_escape_corpus(mutable_corpus: Path) -> None:
    _write_index(mutable_corpus, lambda d: d["documents"][0].update(text_file="../index.json"))
    c = load_corpus(mutable_corpus)
    with pytest.raises(CorpusError, match="escapes"):
        c.text_lines(c.documents[0])


# ---- document and section resolution -----------------------------------------


@pytest.mark.parametrize("ref", ["synth-a", "SYNTH SP 000-1", "synth  sp 000-1"])
def test_doc_by_id_or_number(corpus: Corpus, ref: str) -> None:
    assert tools.resolve_doc(corpus, ref).doc_id == "synth-a"


def test_unknown_doc_is_error_listing_known(corpus: Corpus) -> None:
    with pytest.raises(tools.ToolError, match="unknown document.*synth-a, synth-b") as ei:
        tools.info(corpus, "nope")
    assert ei.value.hint == "synth_search('<words>')"


# ---- read ---------------------------------------------------------------------


def test_read_section_range_and_numbers(corpus: Corpus) -> None:
    out = tools.read(corpus, "synth-a", section="2.1")
    assert "(lines 10-13)" in out
    assert "10: 2.1 Round widgets" in out
    assert "11: Round widgets use quokka quokka quokka counters." in out
    assert "13: " in out
    assert "14:" not in out and " 9:" not in out
    assert _footer(out) == {"cite": "SYNTH SP 000-1 §2.1"}


def test_read_section_accepts_section_sign(corpus: Corpus) -> None:
    assert "(lines 3-5)" in tools.read(corpus, "synth-b", section="§1")


def test_read_lines(corpus: Corpus) -> None:
    out = tools.read(corpus, "synth-a", lines="4-5")
    assert out.splitlines()[1:3] == [
        "4: 1 Introduction",
        "5: This synthetic introduction mentions the zebra token once.",
    ]


@pytest.mark.parametrize(
    ("ref", "first_line"),
    [
        ("synth-a§2.1", "10: 2.1 Round widgets"),
        ("synth-a::2.1", "10: 2.1 Round widgets"),
        ("SYNTH-A§2.1", "10: 2.1 Round widgets"),
        ("synth-a:4-5", "4: 1 Introduction"),
    ],
)
def test_read_takes_a_ref_as_doc(corpus: Corpus, ref: str, first_line: str) -> None:
    assert tools.read(corpus, ref).splitlines()[1] == first_line


def test_a_ref_and_a_section_argument_are_not_both_taken(corpus: Corpus) -> None:
    with pytest.raises(tools.ToolError, match="already names"):
        tools.read(corpus, "synth-a§2.1", section="2.2")
    with pytest.raises(LibError, match="not a ref"):
        tools.read(corpus, "synth-a§2.1¶x")
    with pytest.raises(tools.ToolError, match="no ¶ or #"):
        tools.read(corpus, "synth-a§2.1¶2")


def test_read_unknown_section(corpus: Corpus) -> None:
    with pytest.raises(tools.ToolError, match="no section '9.9'") as ei:
        tools.read(corpus, "synth-a", section="9.9")
    assert ei.value.hint == "synth_outline('synth-a')"


def test_read_requires_a_section_or_lines(corpus: Corpus) -> None:
    with pytest.raises(tools.ToolError, match="a section or a line range") as ei:
        tools.read(corpus, "synth-a")
    assert "synth_outline('synth-a')" in ei.value.hint
    with pytest.raises(tools.ToolError, match="not both"):
        tools.read(corpus, "synth-a", section="1", lines="1-2")


@pytest.mark.parametrize("spec", ["abc", "5-2", "10-99", "0-3"])
def test_read_bad_lines(corpus: Corpus, spec: str) -> None:
    with pytest.raises(tools.ToolError):
        tools.read(corpus, "synth-a", lines=spec)


def test_a_read_stops_at_its_budget_and_next_is_a_ref_read_accepts(corpus: Corpus) -> None:
    out = tools.read(corpus, "synth-a", lines="1-15", max_tokens=20)
    footer = _footer(out)
    assert footer["next"].startswith("synth-a:") and footer["next"].endswith("-15")
    assert tools.GRAMMAR.parse(footer["next"]).lines is not None
    seen: list[str] = []
    ref = "synth-a:1-15"
    for _ in range(20):
        out = tools.read(corpus, ref, max_tokens=20)
        seen += out.split("\n\n")[0].splitlines()[1:]
        ref = _footer(out).get("next", "")
        if not ref:
            break
    assert [int(line.split(":")[0]) for line in seen] == list(range(1, 16))


def test_a_read_always_makes_progress_and_has_no_next_at_the_end(corpus: Corpus) -> None:
    out = tools.read(corpus, "synth-a", section="2.1", max_tokens=1)
    assert "(lines 10-10 of 10-13)" in out and _footer(out)["next"] == "synth-a:11-13"
    assert "next" not in _footer(tools.read(corpus, "synth-a:11-13"))
    with pytest.raises(tools.ToolError, match="max_tokens"):
        tools.read(corpus, "synth-a", section="1", max_tokens=0)


# ---- outline ------------------------------------------------------------------


def test_outline_tree(corpus: Corpus) -> None:
    lines = tools.outline(corpus, "synth-a").splitlines()
    assert lines[1] == "1  Introduction  (lines 4-6)"
    assert lines[3] == "  2.1  Round widgets  (lines 10-13)"
    assert "next" not in _footer(tools.outline(corpus, "synth-a"))


def test_outline_pages_with_a_start_cursor(corpus: Corpus) -> None:
    first = tools.outline(corpus, "synth-a", limit=3)
    assert _footer(first)["next"] == "start=3"
    rest = tools.outline(corpus, "synth-a", start=3, limit=3)
    assert "2.2  Square widgets" in rest and "Round" not in rest
    assert "next" not in _footer(rest)


# ---- info ---------------------------------------------------------------------


def test_info_fields_and_no_warning_for_final(corpus: Corpus) -> None:
    out = tools.info(corpus, "synth-a")
    for needle in (
        "number: SYNTH SP 000-1",
        "date: 2000-01",
        "status: final",
        "sha256: 000",
        "url: https://example.invalid/synth-a.pdf",
    ):
        assert needle in out
    assert "warning" not in _footer(out)


def test_info_warns_when_not_final(corpus: Corpus) -> None:
    assert _footer(tools.info(corpus, "synth-b"))["warning"].startswith("status is 'draft'")


# ---- cite ---------------------------------------------------------------------


def test_cite_section_format(corpus: Corpus) -> None:
    out = tools.cite(corpus, "synth-a", section="2.1")
    assert out.splitlines()[0] == "SYNTH SP 000-1 §2.1"
    assert "https://example.invalid/synth-a.pdf" in out
    assert "Heading: Round widgets" in out


def test_cite_matches_contract_form() -> None:
    # Contract form is "<number> §<section id>"; the number is data, not hard-coded.
    d = Document(
        "x",
        "NIST SP 800-73pt2-5",
        "t",
        "2000-01",
        "final",
        "u",
        "s",
        "x.txt",
        (Section("3.2.4", "h", 1, 2),),
    )
    out = tools.cite(Corpus(FIXTURES, (d,)), "x", section="3.2.4")
    assert out.splitlines()[0] == "NIST SP 800-73pt2-5 §3.2.4"
    assert tools.cite(Corpus(FIXTURES, (d,)), "x§3.2.4").splitlines()[0] == "NIST SP 800-73pt2-5 §3.2.4"


def test_cite_document_only_and_unknown_section(corpus: Corpus) -> None:
    assert tools.cite(corpus, "synth-b").splitlines() == [
        "SYNTH FIPS 000",
        "https://example.invalid/synth-b.pdf",
    ]
    with pytest.raises(tools.ToolError, match="no section"):
        tools.cite(corpus, "synth-b", section="7")


# ---- search -------------------------------------------------------------------


def _hits(out: str) -> list[str]:
    return [line.split("  ")[0] for line in out.splitlines() if "§" in line and "(lines " in line]


def test_search_ranks_and_reports_lines(indexed: Corpus) -> None:
    out = tools.search(indexed, "quokka")
    assert _hits(out)[0] == "synth-a§2.1"
    assert set(_hits(out)) == {"synth-a§2.1", "synth-a§2", "synth-b§1"}
    assert "synth-a§2.1  Round widgets  (lines 10-13, score " in out
    assert "quokka quokka quokka counters" in out


def test_search_does_not_credit_parent_with_child_text(indexed: Corpus) -> None:
    assert _hits(tools.search(indexed, "counters")) == ["synth-a§2.1"]


def test_search_restricted_to_doc_by_number(indexed: Corpus) -> None:
    assert _hits(tools.search(indexed, "quokka", doc="SYNTH FIPS 000")) == ["synth-b§1"]


def test_a_restricted_search_relaxes_within_its_document(indexed: Corpus) -> None:
    # "round quokka" has every word in synth-a; synth-b has only "quokka", so restricted to it the search relaxes.
    out = tools.search(indexed, "round quokka", doc="synth-b")
    assert _hits(out) == ["synth-b§1"] and "relaxed" in _footer(out)
    assert "relaxed" not in _footer(tools.search(indexed, "round quokka"))


def test_search_heading_match_outranks_body_only(indexed: Corpus) -> None:
    # "terms" is the heading of synth-b §2 and a body word of nothing else there; "fictional" is in both.
    assert _hits(tools.search(indexed, "terms fictional", doc="synth-b"))[0] == "synth-b§2"
    assert fts.RANKING.title > fts.RANKING.body


def test_search_pages_with_a_start_cursor_to_the_end(indexed: Corpus) -> None:
    first = tools.search(indexed, "quokka", limit=1)
    assert len(_hits(first)) == 1 and _footer(first)["next"] == "start=1"
    seen = _hits(first)
    cursor = _footer(first)["next"]
    while cursor:
        page = tools.search(indexed, "quokka", limit=1, start=int(cursor.removeprefix("start=")))
        seen += _hits(page)
        cursor = _footer(page).get("next", "")
    assert seen == _hits(tools.search(indexed, "quokka"))


def test_search_no_match_is_stated_not_empty(indexed: Corpus) -> None:
    assert tools.search(indexed, "xyzzy") == "No passages match 'xyzzy'.\n"


def test_search_rejects_empty_query_and_bad_limit(indexed: Corpus) -> None:
    with pytest.raises(tools.ToolError, match="no words") as ei:
        tools.search(indexed, "  !! ")
    assert ei.value.hint == "synth_search('<words>')"
    with pytest.raises(tools.ToolError, match="limit"):
        tools.search(indexed, "quokka", limit=0)
    with pytest.raises(tools.ToolError, match="0-based"):
        tools.search(indexed, "quokka", start=-1)


def test_search_reads_the_index_not_the_text(indexed: Corpus) -> None:
    for document in indexed.documents:
        (indexed.root / document.text_file).unlink()
    assert _hits(tools.search(indexed, "counters")) == ["synth-a§2.1"]


def test_a_missing_index_names_the_index_command(corpus: Corpus) -> None:
    with pytest.raises(CorpusError, match="no search index") as ei:
        tools.search(corpus, "quokka")
    assert (ei.value.hint, ei.value.action) == ("", "synthlib index")


def test_a_stale_index_names_the_index_command(indexed: Corpus) -> None:
    _write_index(indexed.root, lambda d: d["documents"].pop())
    reloaded = load_corpus(indexed.root)
    with pytest.raises(CorpusError, match="stale") as ei:
        tools.search(reloaded, "quokka")
    assert ei.value.action == "synthlib index"
    fts.build(reloaded)
    assert _hits(tools.search(reloaded, "quokka")) == ["synth-a§2.1", "synth-a§2"]


def test_the_index_command_builds_the_index(mutable_corpus: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert fts.main(SPEC, ["--corpus", str(mutable_corpus)]) == 0
    assert "indexed 6 section(s) of 2 document(s)" in capsys.readouterr().out
    assert _hits(tools.search(load_corpus(mutable_corpus), "zebra")) == ["synth-a§1"]
    assert fts.main(SPEC, ["--corpus", str(mutable_corpus / "nowhere")]) == 2
    assert "action: synthlib fetch" in capsys.readouterr().err


# ---- MCP wiring ---------------------------------------------------------------


def _call(server: Any, name: str, arguments: dict[str, Any]) -> Any:
    import anyio
    from mcp import Client

    async def drive() -> Any:
        async with Client(server) as client:
            return await client.call_tool(name, arguments)

    return anyio.run(drive)


def test_tool_surface() -> None:
    from primarysource.pdfcorpus.server import CorpusServer

    names = {t.name for t in asyncio.run(CorpusServer(SPEC).mcp.list_tools())}
    assert names == {"search", "read", "outline", "info", "cite"}


def test_primarysource_mcp_serves_nist_and_usb_tools_prefixed() -> None:
    for name in ("nist", "usb"):
        served = {t.name for t in cli.build_server([name])._tool_manager.list_tools()}
        assert served == {f"{name}_{tool}" for tool in ("search", "read", "outline", "info", "cite")}
        bare = {t.name for t in cli.build_server([name], bare=True)._tool_manager.list_tools()}
        assert bare == {"search", "read", "outline", "info", "cite"}


def test_mcp_tool_maps_errors_and_serves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from primarysource.pdfcorpus.server import CorpusServer

    server = CorpusServer(SPEC)
    monkeypatch.setenv("SYNTHLIB_CORPUS", str(tmp_path))
    with pytest.raises(CorpusError, match="not fetched yet"):
        server.info("synth-a")
    result = _call(server.mcp, "info", {"doc": "synth-a"})
    assert result.is_error is True
    lines = result.content[0].text.splitlines()[1:]
    assert lines[0].startswith("error: no corpus index at ")
    assert lines[1:] == ["action: synthlib fetch"]
    monkeypatch.setenv("SYNTHLIB_CORPUS", str(FIXTURES))
    assert "number: SYNTH SP 000-1" in server.info("synth-a")
    result = _call(server.mcp, "cite", {"doc": "nope"})
    assert result.is_error is True
    assert result.content[0].text.splitlines()[1:] == [
        "error: unknown document 'nope' (known doc_ids: synth-a, synth-b)",
        "hint: synth_search('<words>')",
    ]
    result = _call(server.mcp, "search", {"query": "quokka"})
    assert result.is_error is True and "action: synthlib index" in result.content[0].text


def test_a_running_server_reloads_a_rewritten_corpus(monkeypatch: pytest.MonkeyPatch, mutable_corpus: Path) -> None:
    from primarysource.pdfcorpus.server import CorpusServer

    server = CorpusServer(SPEC)
    monkeypatch.setenv("SYNTHLIB_CORPUS", str(mutable_corpus))
    assert "synth-b" in server.info("synth-b")
    _write_index(mutable_corpus, lambda d: d["documents"].pop())
    with pytest.raises(tools.ToolError, match="unknown document"):
        server.info("synth-b")


# ---- no network ----------------------------------------------------------------

_NETWORK = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "urllib3",
    "httpx",
    "requests",
    "aiohttp",
    "ftplib",
    "smtplib",
    "websockets",
    "asyncio",
}


def test_server_source_imports_no_networking() -> None:
    files = sorted(SERVER_DIR.glob("*.py"))
    assert len(files) >= 6
    for f in files:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module]
            for m in mods:
                assert m.split(".")[0] not in _NETWORK, f"{f.name} imports {m}"


def test_form_feed_at_a_page_break_does_not_shift_line_numbers(mutable_corpus: Path) -> None:
    """pdftotext puts a form feed at each page break; splitlines() would count it as a line break.

    The ingest side numbers lines by newline only, so the server must too, or every section read
    returns the wrong text. Insert a form feed mid-file and check the line count and content stay put.
    """
    path = mutable_corpus / "synth-a.txt"
    original = path.read_text(encoding="utf-8")
    original_lines = original.split("\n")
    if original_lines and original_lines[-1] == "":
        original_lines.pop()
    path.write_text(original.replace("\n", "\n\x0c", 1), encoding="utf-8")
    c = load_corpus(mutable_corpus)
    lines = c.text_lines(c.documents[0])
    assert len(lines) == len(original_lines)
    assert lines[1] == "\x0c" + original_lines[1]
    assert lines[2:] == original_lines[2:]


def test_a_lone_carriage_return_does_not_shift_line_numbers(mutable_corpus: Path) -> None:
    """pdftotext can leave a lone CR inside a line; ingest counts lines by LF only, so the reader must too.

    Found by comparing nist's index with its stored text (sp800-38g, sp800-166): every line after the CR was off
    by one. A CRLF file (how the text is stored on Windows) still reads as one line per CRLF.
    """
    path = mutable_corpus / "synth-a.txt"
    original = path.read_text(encoding="utf-8").split("\n")
    if original and original[-1] == "":
        original.pop()
    lines_in = list(original)
    lines_in[1] = original[1] + "\rtail"
    path.write_bytes(("\r\n".join(lines_in) + "\r\n").encode("utf-8"))
    c = load_corpus(mutable_corpus)
    lines = c.text_lines(c.documents[0])
    assert len(lines) == len(original)
    assert lines[1] == original[1] + "\rtail"
    assert lines[2:] == original[2:]
