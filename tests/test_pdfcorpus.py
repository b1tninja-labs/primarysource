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

from primarysource import pdfcorpus
from primarysource.pdfcorpus import tools
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
    with pytest.raises(CorpusError, match="synthlib fetch"):
        load_corpus(tmp_path)


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
    with pytest.raises(CorpusError, match="synthlib fetch"):
        c.text_lines(c.documents[0])


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
    with pytest.raises(tools.ToolError, match="Unknown document.*synth-a, synth-b"):
        tools.info(corpus, "nope")


# ---- read ---------------------------------------------------------------------


def test_read_section_range_and_numbers(corpus: Corpus) -> None:
    out = tools.read(corpus, "synth-a", section="2.1")
    assert "(lines 10-13)" in out
    assert "10: 2.1 Round widgets" in out
    assert "11: Round widgets use quokka quokka quokka counters." in out
    assert "13: " in out
    assert "14:" not in out and " 9:" not in out


def test_read_section_accepts_section_sign(corpus: Corpus) -> None:
    assert "(lines 3-5)" in tools.read(corpus, "synth-b", section="§1")


def test_read_lines(corpus: Corpus) -> None:
    out = tools.read(corpus, "synth-a", lines="4-5")
    assert out.splitlines()[1:] == [
        "4: 1 Introduction",
        "5: This synthetic introduction mentions the zebra token once.",
    ]


def test_read_unknown_section(corpus: Corpus) -> None:
    with pytest.raises(tools.ToolError, match="no section '9.9'.*outline"):
        tools.read(corpus, "synth-a", section="9.9")


def test_read_requires_exactly_one_selector(corpus: Corpus) -> None:
    with pytest.raises(tools.ToolError, match="exactly one"):
        tools.read(corpus, "synth-a")
    with pytest.raises(tools.ToolError, match="exactly one"):
        tools.read(corpus, "synth-a", section="1", lines="1-2")


@pytest.mark.parametrize("spec", ["abc", "5-2", "10-99", "0-3"])
def test_read_bad_lines(corpus: Corpus, spec: str) -> None:
    with pytest.raises(tools.ToolError):
        tools.read(corpus, "synth-a", lines=spec)


def test_read_truncates_long_ranges(corpus: Corpus, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "MAX_READ_LINES", 3)
    out = tools.read(corpus, "synth-a", lines="1-8")
    assert "(lines 1-3)" in out and "truncated at 3 lines" in out and "4:" not in out


# ---- outline ------------------------------------------------------------------


def test_outline_tree(corpus: Corpus) -> None:
    lines = tools.outline(corpus, "synth-a").splitlines()
    assert lines[1] == "1  Introduction  (lines 4-6)"
    assert lines[3] == "  2.1  Round widgets  (lines 10-13)"


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
    assert "WARNING" not in out


def test_info_warns_when_not_final(corpus: Corpus) -> None:
    assert "WARNING: status is 'draft'" in tools.info(corpus, "synth-b")


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


def test_cite_document_only_and_unknown_section(corpus: Corpus) -> None:
    assert tools.cite(corpus, "synth-b").splitlines() == [
        "SYNTH FIPS 000",
        "https://example.invalid/synth-b.pdf",
    ]
    with pytest.raises(tools.ToolError, match="no section"):
        tools.cite(corpus, "synth-b", section="7")


# ---- search -------------------------------------------------------------------


def test_search_ranks_and_reports_lines(corpus: Corpus) -> None:
    out = tools.search(corpus, "quokka")
    assert out.splitlines()[1] == ""
    assert out.splitlines()[2].startswith("synth-a §2.1 Round widgets (lines 10-12")
    assert out.index("synth-a §2.1") < out.index("synth-a §2 ") < out.index("synth-b §1")
    assert "11: Round widgets use quokka quokka quokka counters." in out


def test_search_does_not_credit_parent_with_child_text(corpus: Corpus) -> None:
    out = tools.search(corpus, "counters")
    assert "§2.1" in out and "§2 " not in out


def test_search_restricted_to_doc_by_number(corpus: Corpus) -> None:
    out = tools.search(corpus, "quokka", doc="SYNTH FIPS 000")
    assert "synth-b" in out and "synth-a" not in out


def test_search_heading_match_outranks_body_only(corpus: Corpus) -> None:
    out = tools.search(corpus, "scope terms fictional", doc="synth-b")
    assert out.splitlines()[2].startswith("synth-b §2 Terms")


def test_search_limit(corpus: Corpus) -> None:
    out = tools.search(corpus, "quokka", limit=1)
    assert out.startswith("1 of 3 passages")
    assert out.count("(lines ") == 1


def test_search_no_match_is_stated_not_empty(corpus: Corpus) -> None:
    assert tools.search(corpus, "xyzzy") == "No passages match 'xyzzy'."


def test_search_rejects_empty_query_and_bad_limit(corpus: Corpus) -> None:
    with pytest.raises(tools.ToolError, match="Empty query"):
        tools.search(corpus, "  !! ")
    with pytest.raises(tools.ToolError, match="limit"):
        tools.search(corpus, "quokka", limit=0)


# ---- MCP wiring ---------------------------------------------------------------


def test_tool_surface() -> None:
    from primarysource.pdfcorpus.server import CorpusServer

    names = {t.name for t in asyncio.run(CorpusServer(SPEC).mcp.list_tools())}
    assert names == {"search", "read", "outline", "info", "cite"}


def test_mcp_tool_maps_errors_and_serves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp.server.mcpserver.exceptions import ToolError as McpToolError

    from primarysource.pdfcorpus.server import CorpusServer

    server = CorpusServer(SPEC)
    monkeypatch.setenv("SYNTHLIB_CORPUS", str(tmp_path))
    with pytest.raises(McpToolError, match="synthlib fetch"):
        server.info("synth-a")
    monkeypatch.setenv("SYNTHLIB_CORPUS", str(FIXTURES))
    assert "number: SYNTH SP 000-1" in server.info("synth-a")
    with pytest.raises(McpToolError, match="Unknown document"):
        server.cite("nope")
    server.reset()
    monkeypatch.setenv("SYNTHLIB_CORPUS", str(tmp_path))
    with pytest.raises(McpToolError, match="not fetched yet"):
        server.outline("synth-a")


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
    assert len(files) >= 4
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
