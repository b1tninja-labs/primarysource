"""Converter, reference and service behaviour on malformed or hostile input (review findings C1-C6, D1-D4).

Every size or timing check asserts on the *shape* of the result (output length, block count) rather than on a
stopwatch where it can, and uses bounds that are orders of magnitude from both the fixed and the old behaviour.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import pytest
import zimfixture
from zimfixture import build_redirect_loop_zim, build_zim, shell

from primarysource.zim import library, markdown, service
from primarysource.zim.errors import ZimloreError
from primarysource.zim.markdown import convert, to_plain
from primarysource.zim.refs import Ref, format_ref, parse_ref

BOOK = "acme_en_widgets"


def _plain_words(html: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9]+", re.sub(r"<[^>]+>", " ", html)))


# --- C1: omitted end tags -----------------------------------------------------------------------------------------

UNCLOSED = [
    "<main><dl><dt>Term<dd>Definition one<dt>Term2<dd>Def two</dl><p>After the list.</p><p>More.</p></main>",
    "<main><h1>T</h1><p>before</p><dl><dt>Term<dd>Def</dl><h2>H</h2><p>After</p></main>",
    "<main><h2>Title<p>Body para</p></main>",
    "<main><h2>Title<ul><li>item one</li></ul><p>tail</p></main>",
    "<main><h3>Heading<pre>code body</pre><p>tail</p></main>",
    "<main><h2>One<h2>Two<p>Body</p></main>",
    "<main><section><h2>Open heading</section><p>after the section</p></main>",
    "<main><p>lead</p><h2>Dangling at the end of the page",
    "<h2>No main element<p>Body</p>",
]


@pytest.mark.parametrize("html", UNCLOSED)
def test_an_omitted_end_tag_never_swallows_the_text_that_follows(html: str) -> None:
    """The invariant: every word of the visible text survives conversion. `blocks == []` for the first case was
    the defect (an open `<dt>` waited for an end tag that HTML lets a writer omit)."""
    doc = convert(html, "x")
    survived = set(re.findall(r"[A-Za-z0-9]+", to_plain(doc.markdown)))
    assert _plain_words(html) <= survived, _plain_words(html) - survived


def test_an_unclosed_dt_ends_at_its_dd_and_an_unclosed_heading_does_not_fuse_with_the_next() -> None:
    doc = convert(UNCLOSED[1], "x")
    assert doc.blocks == ["# T", "before", "**Term**", "Def", "## H", "After"]
    assert [h.text for h in doc.headings] == ["T", "H"]
    assert convert(UNCLOSED[2], "x").blocks == ["## Title", "Body para"]


def test_an_unclosed_heading_ends_where_its_container_ends() -> None:
    doc = convert("<section><h2>Open heading</section>bare tail text", "x")
    assert doc.blocks == ["## Open heading", "bare tail text"]


def test_a_definition_that_wraps_its_name_in_a_paragraph_is_still_one_definition() -> None:
    doc = convert("<main><dl><dt id='a.b'><p>name</p></dt><dd>body</dd></dl></main>", "x")
    assert doc.blocks == ["**name**", "body"] and [h.anchor for h in doc.headings] == ["a.b"]


# --- C2: anchors --------------------------------------------------------------------------------------------------


def test_headings_under_one_wrapper_id_get_distinct_anchors_and_distinct_sections() -> None:
    html = (
        "<main><div id='content'><h1>Big</h1><p>intro</p><h2>One</h2><p>aaa</p><h2>Two</h2><p>bbb</p>"
        "<h2 id='own'>Own</h2><h2 id='own'>Own again</h2></div></main>"
    )
    doc = convert(html, "x")
    anchors = [h.anchor for h in doc.headings]
    assert anchors == ["content", "content-2", "content-3", "own", "own-2"]
    assert len(set(anchors)) == len(anchors)
    one, two = doc.section("content-2"), doc.section("content-3")
    assert one is not None and two is not None and one != two
    assert doc.blocks[two[0] : two[1]] == ["## Two", "bbb"], "the second heading is reachable and owns its own text"


def test_a_section_wrapper_still_names_its_heading() -> None:
    doc = convert("<main><section id='requirements'><h2>Requirements</h2><p>x</p></section></main>", "x")
    assert [h.anchor for h in doc.headings] == ["requirements"]


# --- C4: references with a separately given library ---------------------------------------------------------------


def test_a_double_colon_is_part_of_the_path_when_the_library_is_given() -> None:
    assert parse_ref("std::vector", "cpp") == Ref("cpp", "std::vector")
    assert parse_ref("Foo::Bar#baz", "ruby") == Ref("ruby", "Foo::Bar", "baz")
    assert parse_ref("cpp::std::vector") == Ref("cpp", "std::vector"), "without a library `::` is the separator"
    assert parse_ref("cpp§std::vector", "other") == Ref("cpp", "std::vector"), "an explicit § always wins"


def test_a_hash_in_a_path_is_written_percent_23_and_round_trips() -> None:
    assert parse_ref("Array#map", "ruby") == Ref("ruby", "Array", "map"), "# stays the anchor separator"
    ref = parse_ref("c%23/intro", "dotnet")
    assert ref == Ref("dotnet", "c#/intro")
    assert str(ref) == "dotnet§c%23/intro" and parse_ref(str(ref)) == ref
    odd = format_ref("lib", "100%25 #x", "frag")
    assert parse_ref(odd) == Ref("lib", "100%25 #x", "frag")


# --- C6: paging and limits ----------------------------------------------------------------------------------------


def test_paging_past_the_end_is_an_error_not_an_inverted_range(acme: Path) -> None:
    total = service.read("acme§guide/config", max_tokens=100_000)["blocks"]["of"]
    last = service.read(f"acme§guide/config¶{total}")
    assert last["blocks"] == {"from": total, "to": total, "of": total} and last["next"] is None
    with pytest.raises(ZimloreError, match="no ¶"):
        service.read(f"acme§guide/config¶{total + 1}")
    with pytest.raises(ZimloreError, match="no ¶999"):
        service.read("acme§guide/config#long¶999")
    with pytest.raises(ZimloreError, match="start must be an integer of at least 0"):
        service.search("widgets", "acme", start=-1)
    with pytest.raises(ZimloreError, match="start must be an integer of at least 0"):
        service.libraries(start=-5)


def test_non_positive_limits_and_budgets_are_rejected_and_huge_ones_are_clamped(acme: Path) -> None:
    with pytest.raises(ZimloreError, match="limit must be"):
        service.search("widgets", "acme", limit=0)
    with pytest.raises(ZimloreError, match="max_tokens must be"):
        service.search("widgets", "acme", max_tokens=0)
    with pytest.raises(ZimloreError, match="max_tokens must be"):
        service.read("acme§guide/config", max_tokens=-1)
    with pytest.raises(ZimloreError, match="limit must be"):
        service.outline("acme§guide/config", limit=0)
    with pytest.raises(ZimloreError, match="start must be"):
        service.outline("acme§guide/config", start=-1)
    with pytest.raises(ZimloreError, match="past the end"):
        service.outline("acme§guide/config", start=1000)
    with pytest.raises(ZimloreError, match="past the end"):
        service.outline("acme", start=10**6)
    with pytest.raises(ZimloreError, match="limit must be"):
        service.links("acme§guide/install", limit=0)
    outline = service.outline("acme§guide/config", limit=10**9)
    assert outline["clamped"] == {"limit": 1000}
    read = service.read("acme§guide/config", max_tokens=10**9)
    assert read["clamped"] == {"max_tokens": service.MAX_TOKENS_CAP}
    assert "clamped" not in service.read("acme§guide/config")


# --- D1: redirect loops -------------------------------------------------------------------------------------------


def _within(seconds: float, call: object) -> object:
    """Run `call` on a daemon thread. A hang fails the test instead of freezing the suite."""
    box: dict[str, object] = {}

    def run() -> None:
        try:
            box["value"] = call()  # type: ignore[operator]
        except Exception as error:  # noqa: BLE001
            box["error"] = error

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), f"still running after {seconds}s: an unbounded loop"
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]


def test_a_redirect_loop_does_not_hang_search_and_its_hits_are_skipped(home: Path) -> None:
    build_redirect_loop_zim(home / "zim")
    with pytest.raises(ZimloreError, match="redirect loop"):
        service.read("loop§a")
    result = _within(20, lambda: service.search("zebra", "loop"))
    refs = [hit["ref"] for hit in result["hits"]]  # type: ignore[index]
    assert "loop_en_x§x" in refs, "the ordinary article is still found"
    assert not any(ref.endswith(("§a", "§b")) for ref in refs), "the looping redirects are skipped, not fatal"


def test_resolve_redirect_is_bounded_and_reports_unreadable_targets() -> None:
    class Loop:
        is_redirect = True

        def get_redirect_entry(self) -> Loop:
            return self

    class Dangling:
        is_redirect = True

        def get_redirect_entry(self) -> object:
            raise RuntimeError("no such entry")

    class Plain:
        is_redirect = False

    with pytest.raises(ZimloreError, match="redirect loop"):
        service.resolve_redirect(Loop(), "p")
    with pytest.raises(ZimloreError, match="cannot be read"):
        service.resolve_redirect(Dangling(), "p")
    plain = Plain()
    assert service.resolve_redirect(plain, "p") is plain


# --- D2: nested lists ---------------------------------------------------------------------------------------------


def test_deeply_nested_lists_do_not_repeat_unbounded_indentation() -> None:
    """3,000 nested lists produced 18 MB of leading spaces before the cap (n^2); a crafted 1 MB page, gigabytes."""
    n = 3000
    doc = convert("<ul>" * n + "<li>x</li>" * n, "x")
    assert len(doc.blocks) == n, "no item is lost to the cap"
    assert len(doc.markdown) < 200_000
    assert max(len(block) - len(block.lstrip(" ")) for block in doc.blocks) == 2 * markdown.MAX_INDENT
    prose = convert("<ul>" * n + "<p>x</p>" * n, "x")
    assert len(prose.blocks) == n and len(prose.markdown) < 200_000, "paragraphs inside lists are capped too"
    nested = convert("<ul><li>a<ul><li>b</li></ul></li></ul>", "x")
    assert nested.blocks == ["- a", "  - b"], "ordinary nesting keeps its indentation"


# --- D3: to_plain on runs of brackets -----------------------------------------------------------------------------


def test_to_plain_is_linear_on_runs_of_opening_brackets() -> None:
    """40,000 `[` took 2.3 s before the label and target were bounded; this is 100,000."""
    # Measured with a stopwatch, not `_within`: a regex holds the GIL, so a watchdog thread cannot interrupt it.
    # The old code needs roughly 15 s for the first input and 10 s for the second; the bound is generous.
    for text in ["[" * 100_000, "[a](" * 100_000, "[" + "x" * 100_000, "[a](" + "b" * 100_000]:
        started = time.perf_counter()
        to_plain(text)
        assert time.perf_counter() - started < 4, f"{text[:6]!r}... took {time.perf_counter() - started:.1f}s"
    assert to_plain("see [the page](guide/config#timeouts) and [b](c)") == "see the page and b"


def test_the_converted_text_of_one_document_has_a_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(markdown, "MAX_OUTPUT_CHARS", 500)
    doc = convert("<main>" + "<p>0123456789</p>" * 200 + "</main>", "x")
    assert doc.truncated and 0 < len(doc.blocks) < 200
    assert sum(len(b) for b in doc.blocks) <= 500
    assert not convert("<p>short</p>", "x").truncated


# --- D4: size budget ----------------------------------------------------------------------------------------------


def test_an_entry_over_the_size_budget_is_refused_naming_the_size_and_the_way_out(
    acme: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = library.find("acme", library.scan())
    size = int(library.open_archive(book.path).get_entry_by_path("guide/install").get_item().size)
    monkeypatch.setenv(service.MAX_ENTRY_ENV, str(size - 1))
    with pytest.raises(service.EntryTooLarge) as refused:
        service.read("acme§guide/install")
    assert f"{size:,} bytes" in refused.value.message and f"{size - 1:,}-byte" in refused.value.message
    assert service.MAX_ENTRY_ENV in refused.value.hint and refused.value.extra["size"] == size
    monkeypatch.setenv(service.MAX_ENTRY_ENV, str(size))
    assert "Acme Widgets installs" in service.read("acme§guide/install")["content"], "at the limit is allowed"


def test_a_search_keeps_a_hit_whose_entry_is_over_the_budget_and_says_why(
    acme: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(service.MAX_ENTRY_ENV, "100")
    result = service.search("timeout flange", "acme")
    hit = next(h for h in result["hits"] if h["ref"].endswith("guide/config"))
    assert hit["excerpt"] == "" and "read limit" in hit["note"], "the hit is kept, with the reason"


@pytest.mark.parametrize("bad", ["0", "-5", "lots"])
def test_a_malformed_size_budget_is_an_error_not_unlimited(
    acme: Path, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setenv(service.MAX_ENTRY_ENV, bad)
    with pytest.raises(ZimloreError, match=service.MAX_ENTRY_ENV):
        service.read("acme§guide/config")


def test_a_read_says_when_the_converter_ceiling_cut_the_page(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service.forget()
    body = "".join(f"<p>paragraph {n} of a very long page</p>" for n in range(100))
    build_zim(home / "zim", extra={"long": shell(body)})
    monkeypatch.setattr(markdown, "MAX_OUTPUT_CHARS", 600)
    result = service.read(f"{BOOK}§long", max_tokens=50_000)
    assert "ceiling" in result["converted_truncated"]
    assert result["blocks"]["of"] < 100


# --- C2/C3 through the service: shared ancestor ids and whole-article sections -------------------------------------

_FILL = "".join(f"<p>filler {n} nothing special</p>" for n in range(120))
SHARED_ID = shell(
    f"<div id='content'><h1>Big</h1>{_FILL}<h2>One</h2><p>aaa alpha</p><h2>Two</h2><p>needle zebra</p>"
    f"<h2>Three</h2>{_FILL}</div>"
)
SPREAD = shell(
    f"<h1 id='top'>Spread</h1><h2 id='a'>Alpha</h2><p>quokka lives here</p>{_FILL}"
    f"<h2 id='b'>Beta</h2><p>wombat lives here</p>{_FILL}"
)


def _pages(home: Path) -> None:
    service.forget()
    build_zim(home / "zim", extra={"shared": SHARED_ID, "spread": SPREAD})


def test_a_section_under_a_shared_wrapper_id_is_found_and_readable(home: Path) -> None:
    _pages(home)
    hit = next(h for h in service.search("needle zebra", "acme")["hits"] if h["ref"].endswith("§shared"))
    assert hit["section"]["heading"] == "Two", "not 'Big', the first heading that shared the anchor"
    assert hit["section"]["blocks"] < 10 and "needle zebra" in hit["excerpt"]
    read = service.read(hit["section"]["ref"])
    assert read["scope"] == "section" and "needle zebra" in read["content"] and "Big" not in read["content"]


def test_a_query_spread_over_the_page_does_not_name_the_whole_article_as_its_section(home: Path) -> None:
    """With an `<h1 id>` the whole page is a 'section' that covers both words; naming it helps nobody."""
    _pages(home)
    hit = next(h for h in service.search("quokka wombat", "acme")["hits"] if h["ref"].endswith("§spread"))
    assert "section" not in hit
    one = next(h for h in service.search("quokka", "acme")["hits"] if h["ref"].endswith("§spread"))
    assert one["section"]["anchor"] == "a" and "quokka" in one["excerpt"]


# --- C5: excerpts ---------------------------------------------------------------------------------------------------


def test_an_excerpt_ignores_stopwords_and_matches_whole_words() -> None:
    blocks = ["How to use the other thing for the other users", "The flange rotor is mounted on the frame"]
    assert service._excerpt(blocks, "how to use the flange rotor").startswith("The flange rotor")
    assert service._excerpt(["concatenate strings", "the cat sat"], "cat") == "the cat sat", "no mid-word hit"
    assert service._excerpt(["rotors spin", "nothing"], "rotor") == "rotors spin", "a word matches its plural"


def test_the_excerpt_window_is_anchored_on_the_first_query_word() -> None:
    block = "start " + "padding " * 80 + "the needle sits here " + "tail " * 80
    excerpt = service._excerpt([block], "needle")
    assert excerpt.startswith("…") and "needle sits here" in excerpt and len(excerpt) < 260


# --- section choice -----------------------------------------------------------------------------------------------


def _article(*sections: tuple[str, str, str], filler: int = 10) -> markdown.Document:
    body = "".join(f"<section id='{a}'><h2>{h}</h2><p>{t}</p></section>" for a, h, t in sections)
    pad = "".join(f"<p>pad {n} nothing</p>" for n in range(filler))
    return convert(
        f"<main><h1 id='top'>Article</h1>{body}<section id='pad'><h2>Padding</h2>{pad}</section></main>", "x"
    )


def test_a_heading_word_breaks_a_tie_between_sections_with_equal_coverage() -> None:
    doc = _article(("first", "Notes", "zebra stripes"), ("second", "Zebra", "zebra stripes"))
    chosen = service._best_section(doc, "zebra stripes")
    assert chosen is not None and chosen[0].anchor == "second", "the section whose heading names the topic wins"


def test_stopwords_do_not_count_towards_a_section() -> None:
    doc = _article(
        ("filler", "Prose", "how to use the other thing for the users"), ("rotor", "Mounting", "rotor mounted")
    )
    chosen = service._best_section(doc, "how to use the rotor")
    assert chosen is not None and chosen[0].anchor == "rotor"
    assert service._best_section(doc, "how to use the") is None, "only stopwords: no section"


def test_the_smallest_section_with_the_best_coverage_wins_and_a_giant_one_is_not_named() -> None:
    doc = _article(("a", "Alpha", "quokka"), ("b", "Beta", "wombat"), filler=2)
    assert service._best_section(doc, "quokka wombat") is None, "only the whole page covers both words"
    chosen = service._best_section(doc, "quokka")
    assert chosen is not None and chosen[0].anchor == "a"


def test_every_zimfixture_page_converts_without_losing_a_heading() -> None:
    for html in (zimfixture.INSTALL, zimfixture.CONFIG, zimfixture.BIG_MANUAL, zimfixture.MAN_PAGE):
        doc = convert(html, "x")
        anchors = [h.anchor for h in doc.headings if h.anchor]
        assert len(set(anchors)) == len(anchors), "anchors are unique within a document"
