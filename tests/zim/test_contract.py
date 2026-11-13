"""The zim tools on the core MCP contract (PLAN.md §5.9-§5.12), over the invented synthetic ZIM.

Calls go through the SDK's in-process client, against the server `primarysource mcp --collection zim` builds, so
what is checked is what a client receives: text with the fixed footer, `isError` results with `error:`/`hint:`/
`action:` lines, a read's `next:` that `zim_read` takes back as its `ref`, and a list's `next: start=<n>`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mcp")

from zimfixture import build_zim, contract_server, footer_of, tool_error, tool_text  # noqa: E402

from primarysource import registry, render  # noqa: E402
from primarysource.zim import service  # noqa: E402

BOOK = "acme_en_widgets"
PARTIAL = "how do the automated gaskets and sprockets work"  # 'automated' occurs nowhere: every hit is partial


def test_the_collection_is_registered_and_listed_without_libzim(monkeypatch: pytest.MonkeyPatch) -> None:
    """The collection imports with no binding at all: its extra is only needed to open a ZIM."""
    import sys

    for module in ("libzim", "libzim.reader", "libzim.search", "libzim.suggestion", "libzim.writer"):
        monkeypatch.setitem(sys.modules, module, None)
    assert "zim" in registry.available()
    collection = registry.load("zim")
    assert collection.prefix == "zim_" and collection.cli == "primarysource.zim.cli:main"
    ref = collection.grammar.parse("devdocs_en_flask§blueprints/index#why-blueprints¶3")
    assert (ref.doc, ref.section, ref.anchor, ref.para) == (
        "devdocs_en_flask",
        "blueprints/index",
        "why-blueprints",
        3,
    )
    assert collection.grammar.format(ref) == "devdocs_en_flask§blueprints/index#why-blueprints¶3"


def test_every_tool_is_prefixed_text_only_and_read_only() -> None:
    server = contract_server()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
    assert set(tools) == {
        "zim_libraries",
        "zim_resolve",
        "zim_search",
        "zim_read",
        "zim_outline",
        "zim_links",
        "zim_cite",
        "zim_available",
    }
    assert all(tool.annotations is not None and tool.annotations.read_only_hint for tool in tools.values())
    assert all(tool.output_schema is None for tool in tools.values()), "text only, no structured output"


def test_a_read_is_text_with_cite_unit_and_next_as_a_ref_that_reads_on(acme: Path) -> None:
    server = contract_server()
    page = tool_text(server, "zim_read", ref="acme§guide/config", max_tokens=60)
    footer = footer_of(page)
    assert footer["cite"].startswith(
        "Acme Widgets Docs [acme_en_widgets], ZIM edition 2026-10-01, entry guide/config"
    )
    assert footer["unit"] == "block" and footer["next"].startswith(f"{BOOK}§guide/config¶")
    assert page.startswith("Configuring Widgets  [¶1-") or page.startswith("Configuration  [¶1-"), page[:80]
    # Following `next:` as the ref reads the whole article, nothing lost and nothing repeated.
    seen = [page]
    while "next" in footer_of(seen[-1]):
        seen.append(tool_text(server, "zim_read", ref=footer_of(seen[-1])["next"], max_tokens=60))
    assert len(seen) > 3
    whole = tool_text(server, "zim_read", ref="acme§guide/config", max_tokens=100_000)
    assert "next" not in footer_of(whole)
    bodies = ["\n\n".join(p.split("\n\n")[1:]).rsplit("\n\ncite: ", 1)[0] for p in seen]
    joined = "\n\n".join(bodies).replace("\n- ", "\n\n- ")
    expected = "\n\n".join(whole.split("\n\n")[1:]).rsplit("\n\ncite: ", 1)[0].replace("\n- ", "\n\n- ")
    assert joined == expected


def test_a_pilcrow_read_cites_the_blocks_it_shows(acme: Path) -> None:
    server = contract_server()
    page = tool_text(server, "zim_read", ref="acme§guide/config#timeouts¶2", max_tokens=1)
    footer = footer_of(page)
    assert footer["cite"].endswith("entry guide/config#timeouts ¶2") and footer["next"].endswith("#timeouts¶3")
    cite = tool_text(server, "zim_cite", ref="acme§guide/config#timeouts¶2")
    assert footer_of(cite)["cite"] == footer["cite"] and footer_of(cite)["span"].startswith("sha256:")
    assert footer_of(cite)["unit"] == "block"
    whole_article = tool_text(server, "zim_cite", ref="acme§guide/config")
    assert "span" not in footer_of(whole_article), "a page nobody read has no text to hash"


def test_a_search_is_text_and_pages_by_a_zero_based_start(acme: Path) -> None:
    server = contract_server()
    everything = tool_text(server, "zim_search", query="widgets", library="acme", limit=50)
    assert not everything.startswith("{") and f"searched: {BOOK} (ZIM edition 2026-10-01)" in everything
    refs = [line.split("  ")[0] for line in everything.splitlines() if line.startswith(f"{BOOK}§")]
    assert len(refs) >= 3
    paged: list[str] = []
    start = 0
    for _ in range(20):
        page = tool_text(server, "zim_search", query="widgets", library="acme", limit=1, start=start)
        paged += [line.split("  ")[0] for line in page.splitlines() if line.startswith(f"{BOOK}§")]
        footer = footer_of(page)
        if "next" not in footer:
            break
        start = render.parse_next_start(footer["next"])
    assert paged == refs, "paging by start neither skips nor repeats a hit"


def test_a_search_that_found_only_partial_matches_says_relaxed_and_low_confidence(acme: Path) -> None:
    footer = footer_of(tool_text(contract_server(), "zim_search", query=PARTIAL, library="acme"))
    assert "some of the words" in footer["relaxed"] and footer["confidence"].startswith("low")


def test_a_search_that_matches_nothing_is_text_not_an_error(acme: Path) -> None:
    text = tool_text(contract_server(), "zim_search", query="qqqqzzzz", library="acme")
    assert "no entry matched" in text and "this is the search" in text


def _rows(text: str) -> list[str]:
    """The lines of a list result between its header and the blank line before the footer."""
    lines = text.splitlines()[1:]
    return lines[: lines.index("")] if "" in lines else lines


def test_outline_and_links_page_with_next_start(acme: Path) -> None:
    server = contract_server()
    whole = tool_text(server, "zim_outline", ref="acme§guide/config")
    rows = _rows(whole)
    assert len(rows) > 3 and "next" not in footer_of(whole)
    first = tool_text(server, "zim_outline", ref="acme§guide/config", limit=2)
    assert footer_of(first)["next"] == "start=2"
    second = tool_text(server, "zim_outline", ref="acme§guide/config", limit=100, start=2)
    assert _rows(first) + _rows(second) == rows, "paging neither skips nor repeats a row"
    listing = tool_text(server, "zim_outline", ref="acme", limit=2)
    start = render.parse_next_start(footer_of(listing)["next"])
    rest = tool_text(server, "zim_outline", ref="acme", limit=100, start=start)
    assert "next" not in footer_of(rest) and f"{BOOK}§guide/install" in listing + rest
    everything = service.links("acme§guide/install", limit=100)
    assert everything["total"] >= 3
    one = tool_text(server, "zim_links", ref="acme§guide/install", limit=1)
    assert footer_of(one)["next"] == "start=1"
    tail = tool_text(server, "zim_links", ref="acme§guide/install", limit=100, start=1)
    assert "next" not in footer_of(tail)
    assert len(_rows(one)) + len(_rows(tail)) == everything["total"]


def test_libraries_and_available_page_with_next_start(home: Path) -> None:
    service.forget()
    for name in ("alpha", "beta", "gamma"):
        build_zim(home / "zim", f"{name}_en_x_2026-10.zim", name=f"{name}_en_x", title=f"{name} docs")
    server = contract_server()
    first = tool_text(server, "zim_libraries", limit=2)
    assert footer_of(first)["next"] == "start=2" and first.startswith("3 installed")
    last = tool_text(server, "zim_libraries", limit=2, start=2)
    assert "gamma_en_x" in last and "next" not in footer_of(last)


def test_a_stale_zim_puts_the_age_in_a_warning_line(acme: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from primarysource.zim import library

    monkeypatch.setattr(library, "STALE_DAYS", 1)
    page = tool_text(contract_server(), "zim_read", ref="acme§guide/config#timeouts")
    assert "snapshot from 2026-10-01" in footer_of(page)["warning"]


def test_errors_are_is_error_results_with_hint_for_tools_and_action_for_the_human(home: Path) -> None:
    server = contract_server()
    empty = tool_error(server, "zim_libraries")
    assert empty["error"].startswith("no ZIM files found") and "zim_available" in empty["hint"]
    assert "primarysource zim get" in empty["action"], "only the human can download a library"
    missing = tool_error(server, "zim_available", query="flask")
    assert missing["action"] == "primarysource zim catalog --refresh"


def test_a_missing_libzim_is_an_error_naming_the_extra_never_an_import_error(
    acme: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from primarysource.zim import library

    library.close_all()
    for module in ("libzim", "libzim.reader", "libzim.search", "libzim.suggestion", "libzim.writer"):
        monkeypatch.setitem(sys.modules, module, None)
    error = tool_error(contract_server(), "zim_search", query="widgets")
    assert "could not be read" in error["error"]
    assert 'pip install "primarysource[zim]"' in error["action"], "the extra is the human's to install"
