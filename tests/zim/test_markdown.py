from __future__ import annotations

from zimfixture import CONFIG, INSTALL, PIXEL

from primarysource.zim.markdown import convert, resolve_href, to_plain


def test_application_shell_and_inline_images_are_not_content() -> None:
    doc = convert(INSTALL, "guide/install")
    text = doc.markdown
    assert "base64" not in text and PIXEL not in text, "a data URI would cost thousands of tokens"
    assert "NAVLINK" not in text and "junk" not in text, "navbar and script text are chrome, not content"
    assert text.startswith("# Installing Acme Widgets")
    assert doc.dropped_images == 1
    assert "[image: logo]" in text


def test_code_blocks_keep_their_language_and_their_blank_lines() -> None:
    doc = convert(INSTALL, "guide/install")
    fence = next(b for b in doc.blocks if b.startswith("```python"))
    assert fence == "```python\nfrom acme import Widget\n\nwidget = Widget('spin')\nwidget.run()\n```"
    bash = next(b for b in convert(CONFIG, "guide/config").blocks if "--timeout" in b)
    assert bash.startswith("```bash"), "a highlight-<lang> class names the language when data-language is absent"


def test_a_fence_inside_code_gets_a_longer_fence() -> None:
    doc = convert("<pre>before\n```\ninside\n```\nafter</pre>", "x")
    assert doc.blocks[0].startswith("````") and doc.blocks[0].endswith("````")


def test_tables_become_pipe_tables_and_escape_pipes() -> None:
    table = next(b for b in convert(INSTALL, "g").blocks if b.startswith("|"))
    assert table.split("\n") == [
        "| Option | Default |",
        "| --- | --- |",
        "| `speed` | 3 \\| 4 |",
        "| mode | quiet |",
    ]


def test_lists_nest_and_block_quotes_are_marked() -> None:
    doc = convert(INSTALL, "guide/install")
    assert "- Python 3.12" in doc.blocks and "  - with a lid" in doc.blocks
    assert "> Widgets bite." in doc.blocks
    ordered = convert("<ol><li>one</li><li>two</li></ol>", "x")
    assert ordered.blocks == ["1. one", "2. two"]
    assert ordered.markdown == "1. one\n2. two", "list items stay together instead of being split by blank lines"


def test_headings_carry_anchors_from_their_section_wrapper() -> None:
    doc = convert(INSTALL, "guide/install")
    anchors = {h.text: h.anchor for h in doc.headings}
    assert anchors["Requirements"] == "requirements", "the permalink glyph must not leak into the heading text"
    assert anchors["Quickstart"] == "quickstart"
    assert "[¶]" not in doc.markdown and "(#requirements)" not in doc.markdown


def test_definitions_are_addressable_and_end_at_the_next_definition() -> None:
    doc = convert(CONFIG, "guide/config")
    span = doc.section("widget.run")
    assert span is not None
    run = doc.blocks[span[0] : span[1]]
    assert run[0] == "**`widget.run(speed)`**"
    assert "Run the widget at a speed." in run[1]
    assert not any("widget.stop" in block for block in run)


def test_a_section_ends_at_the_next_heading_of_the_same_or_shallower_level() -> None:
    doc = convert(CONFIG, "guide/config")
    start, end = doc.section("long") or (0, 0)
    body = doc.blocks[start:end]
    assert body[0] == "## Long section"
    assert len(body) == 41
    assert doc.blocks[end] == "## After"
    assert doc.section("no-such-anchor") is None


def test_internal_links_resolve_against_the_article_and_external_ones_stay_urls() -> None:
    doc = convert(INSTALL, "guide/install")
    by_text = {link.text: link for link in doc.links}
    assert (by_text["timeouts"].path, by_text["timeouts"].anchor) == ("guide/config", "timeouts")
    assert by_text["the config page"].path == "guide/config", "../guide/config from guide/ is guide/config"
    assert by_text["the project"].path is None and by_text["the project"].href == "https://example.org/acme"
    assert "NAVLINK" not in by_text and all(link.text != "NAVLINK" for link in doc.links)
    assert "[timeouts](guide/config#timeouts)" in doc.markdown


def test_resolve_href_cases() -> None:
    assert resolve_href("a/b/c", "../d") == ("a/d", "")
    assert resolve_href("a/b", "#x") == ("a/b", "x")
    assert resolve_href("a/b", "/root/page#frag") == ("root/page", "frag")
    assert resolve_href("a/b", "https://example.org/x#y") == (None, "y")
    assert resolve_href("a/b", "x%20y") == ("a/x y", "")


def test_without_main_the_whole_body_is_read_and_the_title_comes_from_the_page() -> None:
    doc = convert(
        "<html><head><title>T &amp; U</title></head><body><h1>Head</h1><p>Body &lt;text&gt;.</p></body></html>"
    )
    assert doc.title == "T & U"
    assert doc.blocks == ["# Head", "Body <text>."]


def test_plain_text_drops_markup_but_keeps_code() -> None:
    doc = convert(INSTALL, "guide/install")
    plain = to_plain(doc.markdown)
    assert "# " not in plain.split("\n")[0] and plain.startswith("Installing Acme Widgets")
    assert "```" not in plain and "widget.run()" in plain
    assert "[timeouts]" not in plain and "timeouts" in plain
    assert "**" not in plain and "`pip install acme`" not in plain


def test_sidebars_and_quoted_code_are_content() -> None:
    """Found by `scripts/measure_conversion.py` on the real Python docs: `<aside class="sidebar">` held the
    asyncio 'Hello World' example and was being dropped with the navigation chrome."""
    doc = convert(
        "<main><aside class='sidebar'><p>Hello World!</p><pre data-language='python'>print(1)</pre></aside>"
        "<blockquote><pre><code>quoted code</code></pre></blockquote></main>",
        "x",
    )
    assert "Hello World!" in doc.markdown
    assert any(b.startswith("```python") for b in doc.blocks)
    assert any(b.startswith("> ```") and "quoted code" in b for b in doc.blocks)


def test_navigation_elements_are_dropped_even_without_a_main_wrapper() -> None:
    """With `<main>` present the navbar is excluded by region; this pins the element skip for pages without it."""
    doc = convert(
        "<body><devdocs-navbar><a href='x'>NAVLINK</a></devdocs-navbar><nav>MENU</nav><p>Body</p></body>", "p"
    )
    assert doc.blocks == ["Body"]
    assert doc.links == []


def test_a_block_inside_a_link_does_not_leave_a_stray_bracket() -> None:
    """Found on 91% of sampled mankier pages: `<a href='#Synopsis'><h2>Synopsis</h2></a>` produced a block `[`."""
    doc = convert(
        "<main><a href='#s'><h2>Synopsis</h2></a><a href='x'><div><h3>Next</h3></div></a>"
        "<p>ok <a href='y'>y</a></p></main>",
        "p",
    )
    assert doc.blocks == ["## Synopsis", "### Next", "ok [y](y)"]
    assert not any(block.strip() in {"[", "]"} for block in doc.blocks)


def test_pager_cards_are_dropped_but_prose_links_with_rel_next_are_kept() -> None:
    """Found on 29 of 79 TypeScript handbook pages: `<a rel=next>` around a card (label, heading, blurb) left
    'Next', a heading and a sentence at the end of the page. Only rel=next/prev around *block* content is dropped."""
    card = (
        "<a class='pager' rel='{rel}' href='{to}'><div class='card'><header>{label}</header>"
        "<h3>{title}</h3><p>Blurb about {title}.</p></div></a>"
    )
    doc = convert(
        "<main><h1>Gizmos</h1><p>Read about gizmos. See the <a rel='next' href='more'>next chapter</a> too.</p>"
        "<p>Lead-in text <a rel='prev' href='old'><div><h3>Old</h3></div></a></p>"
        "<h2>Last</h2><p>Final words.</p><div>"
        + card.format(rel="prev", to="a", label="Previous", title="Alpha")
        + card.format(rel="NEXT other", to="b", label="Next", title="Beta")
        + "</div></main>",
        "g/gizmos",
    )
    assert doc.blocks == [
        "# Gizmos",
        "Read about gizmos. See the [next chapter](g/more) too.",
        "Lead-in text",
        "## Last",
        "Final words.",
    ]
    assert [h.text for h in doc.headings] == ["Gizmos", "Last"]
    assert {"g/a", "g/b"} <= {link.path for link in doc.links}, "dropped from the text, still reported by zim_links"


def test_preformatted_text_in_a_table_cell_keeps_its_lines_as_one_code_span() -> None:
    """Found on the PEPs and the TypeScript handbook: a <pre> in a <td> lost its fence and its newlines."""
    doc = convert(
        "<main><table><tr><th>Field</th><th>Example</th></tr>"
        "<tr><td>name</td><td><pre><code>a = 1\nb | 2</code></pre></td></tr></table></main>",
        "p",
    )
    assert doc.blocks == ["| Field | Example |\n| --- | --- |\n| name | `a = 1<br>b \\| 2` |"]


RTD_PAGE = (
    "<html><body>"
    "<nav class='wy-nav-side'>SITE MENU TAG</nav>"
    "<div class='wy-menu' role='navigation' aria-label='Navigation menu'>"
    "<ul><li><a href='a.html'>Menu item</a></li></ul></div>"
    "<div role='main' class='document'>"
    "<div role='navigation' aria-label='Page navigation'><ul><li>Breadcrumb</li></ul></div>"
    "<h1>Fernet (symmetric encryption)<a class='headerlink' href='#fernet' title='Link to this heading'></a></h1>"
    "<p>Body text.</p>"
    "<dl class='py class'><dt class='sig sig-object py' id='x.Fernet'><em class='property'><span class='k'>"
    "<span class='pre'>class</span></span><span class='w'> </span></em><span class='sig-prename'>x.</span>"
    "<span class='sig-name'>Fernet</span><span class='sig-paren'>(</span><em class='sig-param'>key</em>"
    "<span class='sig-paren'>)</span><a class='reference external' href='https://example.org/src'>"
    "<span class='viewcode-link'>[source]</span></a><a class='headerlink' href='#x.Fernet'></a></dt>"
    "<dd><p>The class.</p></dd></dl>"
    "<footer><div role='navigation' aria-label='Footer'><a href='b.html' rel='next'>Next</a></div>"
    "<div role='contentinfo'><p>Copyright holders</p></div></footer>"
    "</div></body></html>"
)


def test_landmark_navigation_icon_glyphs_and_markup_in_signatures_are_cleaned() -> None:
    """Found converting a real Sphinx + Read the Docs build (cryptography 50.0.2): the site menu came first on
    every page, headings ended in an empty permalink, and a class line read `***class *x.Fernet(*key*)`."""
    doc = convert(RTD_PAGE, "fernet.html")
    text = doc.markdown
    assert "Menu item" not in text and "Breadcrumb" not in text and "Copyright" not in text and "Next" not in text
    assert "" not in text and "[](" not in text
    assert doc.blocks[0] == "# Fernet (symmetric encryption)"
    assert "**class x.Fernet(key)[source]**" in doc.blocks, doc.blocks
    assert all("*key*" not in block for block in doc.blocks)
    assert {link.path for link in doc.links} == {None}, "menu and footer links are not reported"
    assert [link.href for link in doc.links] == ["https://example.org/src"]
