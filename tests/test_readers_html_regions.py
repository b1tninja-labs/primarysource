"""Page chrome and content-region selection. Every HTML string here is invented, shaped like the markup of the
theme named in the test; none of it is upstream text."""

from __future__ import annotations

import pytest

from primarysource.readers.html import convert

# --- a stray close tag inside a skipped element ------------------------------------------------------------------

STARLETTE_TOC = (
    "<body><nav class='md-nav md-nav--secondary'><ul>"
    "<li class='md-nav__item'></li><a href='#a'>Entry A</a></li>"
    "<li class='md-nav__item'></li><a href='#b'>Entry B</a></li>"
    "<li class='md-nav__item'></li><a href='#c'>LEAKED TOC</a></li>"
    "</ul></nav><h1>Responses</h1><p>Body text.</p></body>"
)


def test_a_stray_close_tag_inside_a_nav_does_not_end_the_skip() -> None:
    """Starlette's own TOC template writes `<li></li><a>..</a></li>`: one stray `</li>` per entry. The skip counted
    end tags of any name, reached zero after two entries, and the rest of the menu became page text."""
    doc = convert(STARLETTE_TOC, "responses/index.html")
    assert doc.blocks == ["# Responses", "Body text."]
    assert doc.links == [], "links inside the skipped nav are not reported either"


def test_the_stray_close_tag_does_not_leak_when_the_page_has_a_main_element() -> None:
    doc = convert("<main>" + STARLETTE_TOC.replace("<body>", "").replace("</body>", "") + "</main>", "r")
    assert doc.blocks == ["# Responses", "Body text."]


@pytest.mark.parametrize(
    "inside",
    [
        "<b><i>bold</b> misnested</i> LEAK",  # end tags out of order
        "<br><img src='x'><input> LEAK",  # void tags
        "</p></div></span> LEAK",  # end tags that were never opened
        "<nav>inner menu</nav> LEAK",  # a nested element with the skipped element's own name
    ],
)
def test_a_skipped_element_ends_only_at_its_own_matching_close_tag(inside: str) -> None:
    doc = convert(f"<body><nav>{inside}</nav><p>after</p></body>", "x")
    assert doc.blocks == ["after"]


def test_a_skipped_element_also_ends_at_its_close_tag_when_a_child_is_left_open() -> None:
    doc = convert("<body><div role='navigation'><span>unclosed</div><p>after</p></body>", "x")
    assert doc.blocks == ["after"]


# --- content region: main, role=main, a single article --------------------------------------------------------------

FURO = (
    "<body><aside class='sidebar-drawer'><p>SIDEBAR TREE</p><a href='other'>Other page</a></aside>"
    "<div class='page'><div class='top'><p>TOP BAR</p></div>"
    "<article role='main' id='furo-main-content'><h1>Title</h1><p>Body <a href='dest'>link</a>.</p></article>"
    "<div class='related'><p>RELATED PAGES</p></div></div>"
    "<div class='toc-drawer'><p>ON THIS PAGE</p></div></body>"
)


def test_role_main_selects_the_content_when_there_is_no_main_element() -> None:
    """Furo, Read the Docs, TypeDoc-style pages: the sidebar, the top bar and the TOC drawer led and trailed every
    page because only `<main>` selected a region."""
    doc = convert(FURO, "page.html")
    assert doc.blocks == ["# Title", "Body [link](dest)."]
    assert [link.path for link in doc.links] == ["dest"], "links outside the region are not reported"


@pytest.mark.parametrize(
    "opener, closer",
    [
        ("<div role='main'>", "</div>"),
        ('<section ROLE="Main">', "</section>"),
        ("<div id='main-content'>", "</div>"),
        ("<article>", "</article>"),
    ],
)
def test_other_region_markers_select_the_content_too(opener: str, closer: str) -> None:
    html = (
        f"<body><p>CHROME BEFORE</p>{opener}<h1>Real</h1><div><p>inner</p></div><p>tail</p>{closer}"
        "<p>CHROME AFTER</p></body>"
    )
    assert convert(html, "x").blocks == ["# Real", "inner", "tail"]


def test_a_main_element_wins_over_role_main_and_article() -> None:
    html = "<body><article role='main'><p>article</p></article><main><p>main</p></main></body>"
    assert convert(html, "x").blocks == ["main"]
    html = "<body><article><p>article</p></article><div role='main'><p>role</p></div></body>"
    assert convert(html, "x").blocks == ["role"]


def test_several_articles_are_a_list_of_content_not_one_region() -> None:
    """A blog index or a list of questions has an `<article>` per item; picking one would drop the rest."""
    html = (
        "<body><p>lead</p><article><h2>First</h2><p>one</p></article><p>between</p>"
        "<article><h2>Second</h2><p>two</p></article><p>tail</p></body>"
    )
    assert convert(html, "x").blocks == ["lead", "## First", "one", "between", "## Second", "two", "tail"]
    one = convert("<body><p>menu</p><article><h1>Only</h1><p>one</p></article><p>outside</p></body>", "x")
    assert one.blocks == ["# Only", "one"]


def test_several_role_main_elements_are_all_read() -> None:
    html = "<body><div role='main'><p>one</p></div><p>between</p><div role='main'><p>two</p></div></body>"
    assert convert(html, "x").blocks == ["one", "two"]


def test_a_role_main_that_leaves_the_pages_title_outside_is_not_the_article() -> None:
    """Found on a Stack Exchange ZIM: `#mainbar` has `role="main"` but the question's `<h1>` sits in a header above
    it, so selecting the role dropped the title of 399 of 400 sampled questions."""
    html = (
        "<body><div id='content'><div id='question-header'><h1>How do I plan a language?</h1></div>"
        "<div id='mainbar' role='main'><div class='question'><p>Question body.</p></div>"
        "<div class='answer'><p>Answer body.</p></div></div></div></body>"
    )
    assert convert(html, "q/1").blocks == ["# How do I plan a language?", "Question body.", "Answer body."]
    kept = convert("<body><p>menu</p><div role='main'><h1>Title</h1><p>Body.</p></div><p>footer</p></body>", "x")
    assert kept.blocks == ["# Title", "Body."], "an h1 inside the region does not disqualify it"
    skipped = convert("<body><nav><h1>Site</h1></nav><div role='main'><h1>Title</h1><p>Body.</p></div></body>", "x")
    assert skipped.blocks == ["# Title", "Body."], "an h1 inside skipped chrome does not count as the page's title"


def test_a_region_marker_that_never_opens_falls_back_to_the_whole_body() -> None:
    """The scan is textual: `<main` inside a script or a comment must not empty the page."""
    html = (
        "<body><script>var t = '<main>';</script><!-- <article> --><h1>Head</h1><p>Body</p>"
        "<script>x = \"role='main'\"</script></body>"
    )
    assert convert(html, "x").blocks == ["# Head", "Body"]
    no_title = "<body><script>var t = '<main>';</script><p>Body</p></body>"
    assert convert(no_title, "x").blocks == ["Body"]


def test_a_main_element_is_trusted_even_when_a_site_title_h1_sits_outside_it() -> None:
    """The title guard is for the guessed regions; `<main>` is what DevDocs and most themes mean by content."""
    html = "<body><header><h1>Site name</h1></header><main><h2>Section</h2><p>text</p></main></body>"
    assert convert(html, "x").blocks == ["## Section", "text"]


def test_an_in_page_table_of_contents_is_chrome() -> None:
    html = (
        "<main><h1>Guide</h1><div class='toc'><ul><li><a href='#a'>Part A</a></li></ul></div>"
        "<ul class='table-of-contents'><li>Part A again</li></ul><h2 id='a'>Part A</h2><p>text</p></main>"
    )
    assert convert(html, "x").blocks == ["# Guide", "## Part A", "text"]


def test_a_dialog_is_interface_not_content() -> None:
    assert convert("<body><dialog open><p>Search the docs</p></dialog><p>Body</p></body>", "x").blocks == ["Body"]


def test_without_any_region_marker_the_whole_body_is_still_read() -> None:
    assert convert("<body><h1>A</h1><p>b</p></body>", "x").blocks == ["# A", "b"]


# --- class-named chrome: TypeDoc ----------------------------------------------------------------------------------

TYPEDOC = (
    "<body><header class='tsd-page-toolbar'><div class='tsd-toolbar-contents'><a href='../index.html'>pkg v1</a>"
    "<dialog id='tsd-search'><div id='tsd-search-status'><div>Preparing search index...</div></div></dialog>"
    "</div></header>"
    "<div class='container container-main'><div class='col-content'>"
    "<ul class='tsd-breadcrumb'><li><a href=''>f</a></li></ul>"
    "<h1>Function f</h1><p>Does a thing.</p></div>"
    "<div class='col-sidebar'><div class='page-menu'><h3>Settings</h3><span>Member Visibility</span>"
    "<ul><li>Protected</li><li>Inherited</li></ul><label>Theme</label></div>"
    "<div class='site-menu'><a href='../modules.html'>pkg v1</a></div></div></div>"
    "<footer><div class='tsd-generator'><p>Generated using the tool</p></div></footer></body>"
)


def test_a_typedoc_page_loses_its_toolbar_sidebar_breadcrumb_and_footer() -> None:
    doc = convert(TYPEDOC, "functions/f.html")
    assert doc.blocks == ["# Function f", "Does a thing."]
    assert doc.links == [] or all(link.text == "f" for link in doc.links), "toolbar and sidebar links are chrome"
    assert "pkg v1" not in [link.text for link in doc.links]


def test_a_bare_sidebar_class_is_content_but_a_compound_one_is_the_sites_column() -> None:
    """Sphinx's `.. sidebar::` directive is `class="sidebar"` and holds documentation (the asyncio example);
    `col-sidebar` and `sidebar-drawer` are layout columns."""
    html = (
        "<body><div class='sidebar'><p class='sidebar-title'>Note</p><p>kept example</p></div>"
        "<div class='sidebar-drawer'><p>dropped</p></div><div class='col-sidebar'><p>dropped too</p></div>"
        "<p>end</p></body>"
    )
    assert convert(html, "x").blocks == ["Note", "kept example", "end"]


def test_a_chrome_looking_class_on_body_or_html_does_not_empty_the_page() -> None:
    html = "<html class='has-toolbar'><body class='with-sidebar-open toolbar'><h1>Kept</h1></body></html>"
    assert convert(html, "x").blocks == ["# Kept"]


def test_a_page_footer_is_chrome_but_an_articles_own_footer_is_content() -> None:
    html = (
        "<body><article><h1>Post</h1><p>text</p><footer><p>Written by Ada</p></footer></article>"
        "<footer>SITE</footer></body>"
    )
    assert convert(html, "x").blocks == ["# Post", "text", "Written by Ada"]
    section = "<body><section><footer><p>Section footer</p></footer></section></body>"
    assert convert(section, "x").blocks == ["Section footer"]


# --- pagers and breadcrumbs ---------------------------------------------------------------------------------------


def test_pagination_blocks_are_dropped_from_the_text_but_their_links_are_still_reported() -> None:
    """A previous/next widget is chrome in the text; the neighbouring pages stay reachable through `zim_links`."""
    html = (
        "<main><h1>Chapter</h1><p>Text.</p>"
        "<div class='pagination'><a href='p1'>Page one</a> <a href='p3'>Page three</a></div>"
        "<div class='page-nav'><span>Prev</span><a href='old'>Older chapter</a></div>"
        "<div class='prev-next row'><div class='nav-content'><header>Next</header><h3>Cards</h3></div></div>"
        "<ol class='s-pagination'><li>Q2</li></ol>"
        "<nav class='crumbs'>menu</nav></main>"
    )
    doc = convert(html, "doc/chapter")
    assert doc.blocks == ["# Chapter", "Text."]
    assert {link.path for link in doc.links} == {"doc/p1", "doc/p3", "doc/old"}


def test_a_class_named_like_a_pager_on_a_link_does_not_hide_the_links_text() -> None:
    doc = convert("<main><p>See <a class='pager' href='x'>the next page</a> now.</p></main>", "d/e")
    assert doc.blocks == ["See [the next page](d/x) now."]


# --- Texinfo: node ids on wrapper elements -----------------------------------------------------------------------

TEXINFO = (
    "<body><div class='top-level-extent' id='Top'><div class='nav-panel'><p>Next: <a href='#Intro' rel='next'>"
    "Intro</a> [<a href='#Index' rel='index'>Index</a>]</p></div><h1 class='top' id='manual'>"
    "<span>Manual<a class='copiable-link' href='#manual'> &para;</a></span></h1><p>Welcome.</p>"
    "<ul class='mini-toc'><li><a href='#Intro'>Intro</a></li></ul></div>"
    "<div class='chapter-level-extent' id='Intro'><div class='nav-panel'><p>Next: <a href='#Exit-Status'>Exit</a>,"
    " Up: <a href='#Top'>Top</a></p></div><h2 class='chapter' id='Intro-1'><span>1 Intro</span></h2>"
    "<p>Intro text. See <a href='#Exit-Status'>Exit Status</a>.</p>"
    "<ul class='mini-toc'><li><a href='#Exit-Status'>1.1 Exit Status</a></li></ul>"
    "<div class='section-level-extent' id='Exit-Status'><div class='nav-panel'><p>Previous: <a href='#Intro'>Intro"
    "</a></p></div><h3 class='section' id='Exit-Status-1'><span>1.1 Exit Status</span></h3><p>Zero means success.</p>"
    "</div></div></body>"
)


def test_texinfo_node_ids_on_wrapper_divs_resolve_to_the_heading_inside() -> None:
    """`@ref`, Next/Previous/Up and the contents all link to the wrapper's id, while the heading has `<id>-1`."""
    doc = convert(TEXINFO, "manual.html")
    assert [h.anchor for h in doc.headings] == ["manual", "Intro-1", "Exit-Status-1"]
    for alias, heading in (("Exit-Status", "Exit-Status-1"), ("Intro", "Intro-1"), ("Top", "manual")):
        span = doc.section(alias)
        assert span is not None, alias
        assert span == doc.section(heading)
    start, end = doc.section("Exit-Status") or (0, 0)
    assert doc.blocks[start:end] == ["### 1.1 Exit Status", "Zero means success."]
    assert doc.section("nothing-like-this") is None


def test_wrapper_ids_are_not_outline_entries() -> None:
    doc = convert(TEXINFO, "manual.html")
    assert [h.text for h in doc.headings] == ["Manual", "1 Intro", "1.1 Exit Status"]
    assert "Exit-Status" not in {h.anchor for h in doc.headings}


def test_texinfo_navigation_panels_and_mini_tocs_are_chrome() -> None:
    doc = convert(TEXINFO, "manual.html")
    assert doc.blocks == [
        "# Manual",
        "Welcome.",
        "## 1 Intro",
        "Intro text. See [Exit Status](manual.html#Exit-Status).",
        "### 1.1 Exit Status",
        "Zero means success.",
    ]
    targets = {(link.path, link.anchor) for link in doc.links}
    assert ("manual.html", "Intro") in targets, "the Next/Previous/Up links stay in zim_links"


def test_an_id_on_a_wrapper_that_is_followed_by_text_is_not_an_alias_of_a_later_heading() -> None:
    html = "<main><div id='wrapper'><p>text first</p><h2 id='h'>Heading</h2></div></main>"
    doc = convert(html, "x")
    assert doc.section("wrapper") is None


def test_an_anchor_element_directly_before_a_heading_names_it() -> None:
    doc = convert("<main><p>x</p><a id='old-name'></a><h2 id='new-name'>Heading</h2><p>body</p></main>", "x")
    assert doc.section("old-name") == doc.section("new-name")
    assert doc.section("new-name") is not None


def test_a_wrapper_id_never_replaces_a_real_heading_anchor() -> None:
    html = "<main><h2 id='dup'>Real</h2><p>body</p><div id='dup'></div><h2 id='other'>Other</h2></main>"
    doc = convert(html, "x")
    start, end = doc.section("dup") or (0, 0)
    assert doc.blocks[start] == "## Real"
    assert "dup" not in doc.aliases


def test_an_old_style_named_anchor_before_a_heading_is_an_alias_too() -> None:
    doc = convert("<main><a name='old-style'></a><h2 id='new'>Heading</h2><p>x</p></main>", "x")
    assert doc.section("old-style") == doc.section("new") is not None


def test_a_run_of_thousands_of_empty_anchors_keeps_only_the_last_few_as_candidates() -> None:
    """Texinfo index chapters are runs of empty `<a id=index-...>`; only the ones nearest a heading can name it."""
    anchors = "".join(f"<a id='index-{n}'></a>" for n in range(50))
    doc = convert(f"<main>{anchors}<h2 id='h'>Heading</h2><p>x</p></main>", "x")
    assert len(doc.aliases) == 8 and "index-49" in doc.aliases and "index-0" not in doc.aliases


# --- Doxygen --------------------------------------------------------------------------------------------------------

DOXYGEN_MEMBER = (
    "<div class='contents'><h2 class='groupheader'>Function Documentation</h2>"
    "<a id='a1b2c3' name='a1b2c3'></a>"
    "<h2 class='memtitle'><span class='permalink'><a href='#a1b2c3'>&#9670;&#160;</a></span>event_active()</h2>"
    "<div class='memitem'><div class='memdoc'><p>Activates an event.</p></div></div>"
    "<a id='d4e5f6' name='d4e5f6'></a>"
    "<h2 class='memtitle'><span class='permalink'><a href='#d4e5f6'>&#9670;&#160;</a></span>event_del()</h2>"
    "<div class='memitem'><div class='memdoc'><p>Removes an event.</p></div></div></div>"
)


def test_doxygen_member_titles_are_definitions_without_the_diamond_glyph() -> None:
    doc = convert(DOXYGEN_MEMBER, "event_8h.html")
    assert doc.blocks == [
        "## Function Documentation",
        "**event_active()**",
        "Activates an event.",
        "**event_del()**",
        "Removes an event.",
    ]
    assert [(h.text, h.anchor, h.kind) for h in doc.headings] == [
        ("Function Documentation", "", "heading"),
        ("event_active()", "a1b2c3", "definition"),
        ("event_del()", "d4e5f6", "definition"),
    ]
    start, end = doc.section("a1b2c3") or (0, 0)
    assert doc.blocks[start:end] == ["**event_active()**", "Activates an event."]
    assert "◆" not in doc.markdown


DOXYGEN_SOURCE = (
    "<div class='contents'><a href='x.html'>Go to the documentation of this file.</a>"
    "<div class='fragment'>"
    "<div class='line'><a id='l00001' name='l00001'></a><span class='lineno'>    1</span>"
    "<span class='keywordtype'>int</span> <a class='code' href='x.html#f'>f</a>(<span>void</span>)</div>\n"
    "<div class='line'><a id='l00002' name='l00002'></a><span class='lineno'>    2</span>{</div>\n"
    "<div class='line'><span class='lineno'>    3</span>    <span class='keywordflow'>return</span> 0;</div>\n"
    "<div class='line'><span class='lineno'>    4</span>}</div>"
    "</div><p>After the listing.</p>"
    "<div class='ttc' id='tt1'><div class='ttname'><a href='x.html#f'>f</a></div>"
    "<div class='ttdoc'>Tooltip text that duplicates the brief.</div></div></div>"
)


def test_a_doxygen_source_listing_is_one_fence_with_its_indentation_and_without_tooltips() -> None:
    doc = convert(DOXYGEN_SOURCE, "x_source.html")
    assert doc.blocks == [
        "[Go to the documentation of this file.](x.html)",
        "```\nint f(void)\n{\n    return 0;\n}\n```",
        "After the listing.",
    ]
    assert "Tooltip" not in doc.markdown


def test_a_doxygen_breadcrumb_path_is_chrome() -> None:
    html = "<div class='navpath'><ul><li class='navelem'><a href='d.html'>src</a></li></ul></div><h1>T</h1>"
    assert convert(html, "x").blocks == ["# T"]


def test_a_doxygen_code_example_inside_a_definition_body_is_a_fence_too() -> None:
    html = (
        "<main><dl><dt id='f'>f()</dt><dd><p>Example:</p><div class='fragment'>"
        "<div class='line'>a = 1;</div><div class='line'>  b = 2;</div></div></dd></dl></main>"
    )
    doc = convert(html, "x")
    assert doc.blocks == ["**f()**", "Example:", "```\na = 1;\n  b = 2;\n```"]
