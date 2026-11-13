"""The itu tools on the core MCP contract (PLAN.md §5.9-§5.11), over invented text.

Calls go through the SDK's in-process client, against the server `primarysource mcp --collection itu` builds, so
what is checked is what a client receives: text with the fixed footer, `isError` results with `error:`/`hint:`/
`action:` lines, a read's `next:` that `itu_read` takes back as its ref, and a list's `next: start=<n>`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from primarysource import cli as core_cli
from primarysource.itu import corpus, index, sources, text
from primarysource.itu.sources import Edition
from primarysource.render import FOOTER_ORDER, parse_next_start

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

SYNTHETIC = Edition(
    key="T.0#0000-00",
    rec="T.0",
    edition="00/0000",
    title="Synthetic",
    status="test",
    artifact="none",
    sha256="",
    octets=0,
)
LATER = Edition(
    key="T.0#1111-11",
    rec="T.0",
    edition="11/1111",
    title="Synthetic, later",
    status="test",
    artifact="none",
    sha256="",
    octets=0,
)

LONG = " ".join(f"Gadget number {n} shall be painted blue." for n in range(1, 41))
PAGES = [
    "1.1 Widgets are counted whole. A gadget may be skipped; see clause 1.2 and Rec. ITU-T T.9 for more.\n"
    "1.2 Gadgets are ordered by colour. They should be sorted before widgets, as in clause 1.1 and RFC 9999.\n"
    f"1.3 Painting rules. {LONG}\n"
    "1.4 Doohickeys are kept apart from widgets and from gadgets in every case.\n"
    "1.5 Thingamajigs are listed last and stand alone in this invented text.\n"
]


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ITULIB_HOME", str(tmp_path))
    monkeypatch.setattr(sources, "IN_FORCE", (SYNTHETIC, *sources.IN_FORCE))
    monkeypatch.setattr(sources, "SUPERSEDED", (*sources.SUPERSEDED, LATER))
    monkeypatch.setattr(text, "pages", lambda _path: PAGES)
    for edition in (SYNTHETIC, LATER):
        pdf = corpus.pdf_path(edition)
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(edition.key.encode())
        index.build(edition)
    return core_cli.build_server(["itu"])


def _call(server: Any, name: str, **arguments: Any) -> Any:
    import anyio

    async def drive() -> Any:
        async with Client(server) as client:
            return await client.call_tool(name, arguments)

    return anyio.run(drive)


def _text(server: Any, name: str, **arguments: Any) -> str:
    result = _call(server, name, **arguments)
    assert result.is_error is False, result.content[0].text
    assert result.structured_content is None, "text only"
    return str(result.content[0].text)


def _footer(result: str) -> dict[str, str]:
    """The footer lines after the last blank line, checked to be known keys in the fixed order."""
    body, _, tail = result.rstrip("\n").rpartition("\n\n")
    lines = tail.splitlines() if body else []
    footer = dict(line.split(": ", 1) for line in lines if line.split(": ", 1)[0] in FOOTER_ORDER)
    if len(footer) != len(lines):
        return {}
    assert list(footer) == [key for key in FOOTER_ORDER if key in footer], "footer keys in FOOTER_ORDER"
    return footer


def _error_lines(server: Any, name: str, **arguments: Any) -> list[str]:
    result = _call(server, name, **arguments)
    assert result.is_error is True
    return list(result.content[0].text.splitlines()[1:])


# --- text results ------------------------------------------------------------------------------------------------


def test_a_read_is_text_with_cite_and_unit_footer_lines(server: Any) -> None:
    result = _text(server, "itu_read", ref="T.0§1.2")
    assert result.startswith("§1.2 Gadgets are ordered by colour  [¶1-2 of 2]\n\n[¶1] Gadgets are ordered")
    assert _footer(result) == {"cite": "Rec. ITU-T T.0 (00/0000) §1.2", "unit": "sentence"}


def test_one_sentence_carries_its_cite_and_the_hash_of_the_text(server: Any) -> None:
    result = _text(server, "itu_read", ref="T.0§1.2¶2")
    footer = _footer(result)
    assert result.startswith("They should be sorted before widgets")
    assert footer["cite"] == "Rec. ITU-T T.0 (00/0000) §1.2¶2" and footer["span"].startswith("sha256:")
    cite = _text(server, "itu_cite", ref="T.0§1.2¶2")
    assert _footer(cite)["span"] == footer["span"], "itu_cite hashes the same text itu_read returned"


def test_an_ambiguous_clause_number_says_warning(server: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        text, "pages", lambda _p: ["1.1 The first fragment, long enough.\n1.1 A second fragment, also long enough."]
    )
    index.build(SYNTHETIC)
    footer = _footer(_text(server, "itu_read", ref="T.0§1.1"))
    assert footer["warning"].startswith("1 other extracted fragment(s) carry the number 1.1")


def test_search_is_one_entry_per_hit_and_says_relaxed(server: Any) -> None:
    strict = _text(server, "itu_search", query="widgets counted", edition="T.0")
    assert strict.splitlines()[0] == "T.0§1.1  Widgets are counted whole  (Rec. ITU-T T.0 (00/0000) §1.1)"
    assert _footer(strict) == {}, "every term matched and everything fits: no footer"
    relaxed = _text(server, "itu_search", query="widgets zeppelin", edition="T.0")
    assert _footer(relaxed)["relaxed"] == "no clause holds every term; these hold some of them"


def test_an_empty_search_is_text_not_an_error(server: Any) -> None:
    result = _text(server, "itu_search", query="zeppelin dirigible", edition="T.0")
    assert result == "no clause of T.0#0000-00 matches 'zeppelin dirigible'\n"


# --- cursors -----------------------------------------------------------------------------------------------------


def test_a_read_next_is_a_ref_that_itu_read_takes_back_and_nothing_is_lost(server: Any) -> None:
    ref: str | None = "T.0§1.3"
    seen: list[str] = []
    pages = 0
    while ref is not None:
        result = _text(server, "itu_read", ref=ref, max_tokens=60)
        seen.append(result)
        ref = _footer(result).get("next")
        if ref is not None:
            assert ref.startswith("T.0§1.3¶") and ref.endswith("-"), "a ref: clause, then the ¶ the rest starts at"
        pages += 1
    joined = " ".join(seen)
    assert pages > 1, "a small budget must split a long clause"
    assert [n for n in range(1, 42) if joined.count(f"[¶{n}] ") != 1] == [], "every sentence exactly once"


def test_a_read_cursor_names_the_edition_it_came_from(server: Any) -> None:
    result = _text(server, "itu_read", ref="T.0#1111-11§1.3", max_tokens=60)
    assert _footer(result)["next"].startswith("T.0#1111-11§1.3¶"), "the later edition, not the default one"


def test_a_read_cursor_past_the_end_is_an_error_naming_the_way_back(server: Any) -> None:
    assert _error_lines(server, "itu_read", ref="T.0§1.2¶9-") == [
        "error: §1.2 has 2 sentences; ¶9 is outside 1..2",
        "hint: itu_read('1.2') reads the clause from its first sentence",
    ]


@pytest.mark.parametrize(
    ("tool", "arguments", "prefix"),
    [
        ("itu_search", {"query": "gadget", "edition": "T.0", "limit": 1}, "T.0§"),
        ("itu_outline", {"edition": "T.0", "max_tokens": 1}, "T.0§"),
        ("itu_browse", {"path": "T.0", "max_tokens": 1}, "T.0§"),
        ("itu_grep", {"pattern": "gadget", "edition": "T.0", "max_tokens": 1}, "T.0§"),
    ],
)
def test_a_list_next_is_start_n_and_following_it_loses_nothing(
    server: Any, tool: str, arguments: dict[str, Any], prefix: str
) -> None:
    unbounded = {**arguments, "max_tokens": 100_000, **({"limit": 100} if tool == "itu_search" else {})}
    whole = _text(server, tool, **unbounded)
    assert "next" not in _footer(whole)
    expected = [line.split()[0] for line in whole.splitlines() if line.startswith(prefix)]
    seen: list[str] = []
    start = 0
    for _ in range(50):
        result = _text(server, tool, **arguments, start=start)
        seen += [line.split()[0] for line in result.splitlines() if line.startswith(prefix)]
        cursor = _footer(result).get("next")
        if cursor is None:
            break
        start = parse_next_start(cursor)
    assert seen == expected and len(expected) > 1


# --- errors ------------------------------------------------------------------------------------------------------


def test_an_unknown_edition_names_the_tool_that_lists_them(server: Any) -> None:
    assert _error_lines(server, "itu_read", ref="Z.999§1") == [
        "error: unknown edition 'Z.999'",
        "hint: itu_info lists the registered editions",
    ]


def test_a_missing_clause_names_the_tools_that_find_one(server: Any) -> None:
    assert _error_lines(server, "itu_read", ref="T.0§9.9") == [
        "error: T.0#0000-00: no clause §9.9",
        "hint: itu_search for its words, or itu_outline('T.0') for the numbering",
    ]
    assert _error_lines(server, "itu_cite", ref="T.0§9.9")[0].endswith("refusing to cite what is not there")


def test_a_malformed_ref_names_the_ref_shapes(server: Any) -> None:
    lines = _error_lines(server, "itu_read", ref="banana")
    assert lines[0].startswith("error: 'banana' is not a clause reference")
    assert lines[1].startswith("hint: refs look like X.690§11.6")


def test_a_stale_index_puts_the_human_command_in_action(server: Any) -> None:
    corpus.pdf_path(SYNTHETIC).write_bytes(b"republished, and longer than before")
    assert _error_lines(server, "itu_search", query="widgets", edition="T.0") == [
        "error: T.0#0000-00: the corpus changed since the index was built",
        "hint: itu_info shows the registered digest of each edition",
        "action: primarysource itu index T.0#0000-00",
    ]


def test_parse_target_reads_the_cursor_form_and_parse_ref_refuses_it() -> None:
    assert text.parse_target("X.690#2021-02§11.6¶5-") == text.Target("X.690#2021-02", "11.6", 5, True)
    assert text.parse_target("11.6¶2") == text.Target(None, "11.6", 2, False)
    with pytest.raises(ValueError, match="read cursor"):
        text.parse_ref("X.690§11.6¶5-")
    with pytest.raises(ValueError, match="from 1"):
        text.parse_target("11.6¶0")
