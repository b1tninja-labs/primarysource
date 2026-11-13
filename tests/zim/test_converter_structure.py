"""Structure defects found by the documentation-generator prototypes (docs/prototypes/*/DEFECTS.md).

The HTML is invented, in the shape the generators emit; none of it is upstream text.
"""

from __future__ import annotations

from primarysource.zim.markdown import convert, fence_language


def blocks(html: str) -> list[str]:
    return convert(f"<main>{html}</main>", "x.html").blocks


# --- 1. line breaks inside <pre> ---------------------------------------------------------------------------


def test_br_inside_pre_is_a_newline() -> None:
    """TypeDoc, Dokka and javadoc 8 separate the lines of a snippet with <br> and no newline character."""
    html = "<pre><code>import a.B<br>import a.C<br><br>fun test() {<br>  B().run()<br>}</code></pre>"
    assert blocks(html) == ["```\nimport a.B\nimport a.C\n\nfun test() {\n  B().run()\n}\n```"]
    old_javadoc = "<PRE>public class Folder<BR>extends Resource<BR>implements Rule</PRE>"
    assert blocks(old_javadoc) == ["```\npublic class Folder\nextends Resource\nimplements Rule\n```"]


def test_a_br_followed_by_a_newline_is_one_break_and_images_in_pre_are_not_code() -> None:
    doc = convert("<main><pre>a<br>\nb<br/>\n<img src='t.gif' alt='tree'>c</pre></main>", "x")
    assert doc.blocks == ["```\na\nb\nc\n```"], "no '[image: tree]' paragraph after the fence"
    assert doc.dropped_images == 1


def test_line_wrappers_inside_pre_end_a_line() -> None:
    no_newlines = "<pre><code><span class='line'>one</span><span class='line'>two</span></code></pre>"
    assert blocks(no_newlines) == ["```\none\ntwo\n```"]
    shiki = "<pre><code><span class='line'>one</span>\n<span class='line'>two</span>\n</code></pre>"
    assert blocks(shiki) == ["```\none\ntwo\n```"], (
        "the newline between the spans is the same break, not a blank line"
    )
    chroma = (
        "<pre><code><span class='line'><span class='cl'>one\n</span></span>"
        "<span class='line'><span class='cl'>two\n</span></span></code></pre>"
    )
    assert blocks(chroma) == ["```\none\ntwo\n```"]
    divs = "<pre><div class='line'>x = 1</div><div class='line'>  y = 2</div></pre>"
    assert blocks(divs) == ["```\nx = 1\n  y = 2\n```"]
    per_code = "<pre><code>first</code><code>second</code></pre>"
    assert blocks(per_code) == ["```\nfirst\nsecond\n```"]


def test_inline_markup_inside_pre_does_not_break_lines() -> None:
    assert blocks("<pre>a <span>b</span> <code>c</code> <em>d</em></pre>") == ["```\na b c d\n```"]
    assert blocks("<pre><code>x</code></pre>") == ["```\nx\n```"], "a single <code> is the code, not a line"


# --- 2. implied end tags ----------------------------------------------------------------------------------


def test_table_with_omitted_end_tags_keeps_its_body() -> None:
    html = (
        "<table><caption>Encodings</caption><tr><th>Encoding<th>Alphabet"
        "<tr><td>base16<td>0-9 A-F<tr><td>base32<td>A-Z 2-7</table>"
    )
    table = next(b for b in blocks(html) if b.startswith("|"))
    assert table.split("\n") == [
        "| Encoding | Alphabet |",
        "| --- | --- |",
        "| base16 | 0-9 A-F |",
        "| base32 | A-Z 2-7 |",
    ]


def test_cells_without_a_row_and_sections_close_rows() -> None:
    table = next(b for b in blocks("<table><thead><th>a<th>b<tbody><td>1<td>2<tr><td>3<td>4</table>") if b[0] == "|")
    assert table.split("\n")[2:] == ["| 1 | 2 |", "| 3 | 4 |"]


def test_a_table_inside_a_cell_is_text_of_that_cell() -> None:
    html = "<table><tr><td>outer<table><tr><td>in1</td><td>in2</td></tr></table></td><td>side</td></tr></table>"
    table = next(b for b in blocks(html) if b[0] == "|")
    assert table.split("\n")[0] == "| outer in1 in2 | side |"


# --- 3. <pre> in table cells ------------------------------------------------------------------------------


def test_pre_in_a_data_table_stays_an_inline_code_span() -> None:
    html = "<table><tr><th>Field</th><th>Example</th></tr><tr><td>a</td><td><pre>x = 1\ny = 2</pre></td></tr></table>"
    assert blocks(html)[0].split("\n")[2] == "| a | `x = 1<br>y = 2` |"


def test_a_cartouche_is_emitted_as_blocks() -> None:
    """Texinfo @cartouche: a one-cell table around prose and an example."""
    html = (
        "<table class='cartouche'><tr><td><p>Intro text.</p><div class='example'><pre class='language-sh'>"
        "#!/bin/sh\necho hello\n</pre></div><p>Outro.</p></td></tr></table>"
    )
    assert blocks(html) == ["Intro text.", "```sh\n#!/bin/sh\necho hello\n```", "Outro."]


def test_a_single_column_table_of_values_is_still_a_pipe_table() -> None:
    assert blocks("<table><tr><th>Name</th></tr><tr><td>one</td></tr></table>")[0].startswith("| Name |")


def test_a_multitable_row_with_a_pre_keeps_the_pipe_table() -> None:
    html = "<table><tr><td>Shell script:</td><td><pre>echo a\necho b</pre></td></tr></table>"
    assert blocks(html) == ["| Shell script: | `echo a<br>echo b` |\n| --- | --- |"]


# --- 4. javadoc 17 div grids ------------------------------------------------------------------------------


def test_summary_table_divs_become_a_pipe_table() -> None:
    html = (
        "<div class='caption'><span>Methods</span></div>"
        "<div class='summary-table three-column-summary'>"
        "<div class='table-header col-first'>Modifier and Type</div><div class='table-header col-second'>Method</div>"
        "<div class='table-header col-last'>Description</div>"
        "<div class='col-first even-row-color'><code>int</code></div>"
        "<div class='col-second even-row-color'><code>size()</code></div>"
        "<div class='col-last even-row-color'><div class='block'>Number of items.</div></div>"
        "<div class='col-first odd-row-color'><code>void</code></div>"
        "<div class='col-second odd-row-color'><code>clear()</code></div>"
        "<div class='col-last odd-row-color'><div class='block'>Removes all.</div></div></div><p>After.</p>"
    )
    assert blocks(html) == [
        "Methods",
        "| Modifier and Type | Method | Description |\n| --- | --- | --- |\n"
        "| `int` | `size()` | Number of items. |\n| `void` | `clear()` | Removes all. |",
        "After.",
    ]


def test_two_column_constructor_grid_and_plain_div_grids() -> None:
    grid = (
        "<div class='summary-table two-column-summary'><div class='table-header col-first'>Constructor</div>"
        "<div class='table-header col-last'>Description</div>"
        "<div class='col-constructor-name'><code>Box()</code></div>"
        "<div class='col-last'>Makes one.</div></div>"
    )
    assert blocks(grid) == ["| Constructor | Description |\n| --- | --- |\n| `Box()` | Makes one. |"]
    plain = "<div class='grid'><div class='col-first'>a</div><div class='col-second'>b</div></div>"
    assert blocks(plain) == ["a", "b"], "a div grid that is not a summary-table is left alone"


# --- 5. fence languages -----------------------------------------------------------------------------------


def test_fence_language_sources() -> None:
    cases = {
        '<pre><code class="language-bash">pip install x</code></pre>': "bash",
        '<pre class="language-go"><code>x := 1</code></pre>': "go",
        '<pre data-language="rust">fn main() {}</pre>': "rust",
        '<div class="highlight-python notranslate"><div class="highlight"><pre>print(2)</pre></div></div>': "python",
        '<div class="language-python highlight"><pre><span></span><code>print(1)</code></pre></div>': "python",
        '<div class="sourceCode" id="cb1"><pre class="sourceCode python"><code>x</code></pre></div>': "python",
        '<pre><code class="hljs javascript">let a</code></pre>': "javascript",
        '<div class="highlight highlight-source-yaml"><pre>a: 1</pre></div>': "yaml",
        '<div class="highlight-default notranslate"><div class="highlight"><pre>plain</pre></div></div>': "",
        '<body class="language-en"><div class="content"><pre>text</pre></div></body>': "",
        '<pre><code class="hljs">text</code></pre>': "",
    }
    for html, lang in cases.items():
        assert blocks(html)[0].split("\n")[0] == "```" + lang, html


def test_fence_language_function() -> None:
    assert fence_language("brush: python") == "python"
    assert fence_language("lang-js prettyprint") == "js"
    assert fence_language("highlight-shell-session notranslate", wrapper=True) == "shell-session"
    assert fence_language("language-en", wrapper=True) == ""


# --- 6. details, definition links, tabs, admonitions --------------------------------------------------------


def test_details_id_is_an_anchor_named_by_its_summary() -> None:
    html = (
        '<h2 id="a">A</h2><details id="example-X" class="example"><summary>Example (X)</summary><pre>code()</pre>'
        '</details><h2 id="b">B</h2><p>after</p>'
    )
    doc = convert(f"<main>{html}</main>", "x.html")
    assert doc.blocks == ["## A", "**Example (X)**", "```\ncode()\n```", "## B", "after"]
    span = doc.section("example-X")
    assert span is not None and doc.blocks[span[0] : span[1]] == ["**Example (X)**", "```\ncode()\n```"]
    plain = blocks("<details><summary>More</summary><p>text</p></details>")
    assert plain == ["More", "text"], "a summary without an id stays a plain line"


def test_dt_link_is_kept_when_the_term_has_no_id() -> None:
    html = '<dl><dt><a class="struct" href="struct.Widget.html">Widget</a></dt><dd>A widget.</dd></dl>'
    assert blocks(html) == ["**[Widget](struct.Widget.html)**", "A widget."]
    anchored = '<dl><dt id="w"><a href="struct.Widget.html">Widget</a></dt><dd>A widget.</dd></dl>'
    assert blocks(anchored) == ["**Widget**", "A widget."], "a term with its own id is an anchor, not a link"


def test_sphinx_tab_labels_lead_their_panels() -> None:
    html = (
        '<div class="sphinx-tabs"><div role="tablist"><button role="tab" id="t0" aria-controls="p0">Bash</button>'
        '<button role="tab" id="t1" aria-controls="p1">Zsh</button></div>'
        '<div role="tabpanel" id="p0"><p>Add this to bashrc.</p></div>'
        '<div role="tabpanel" id="p1" aria-labelledby="t1" hidden><p>Add this to zshrc.</p></div></div>'
    )
    assert blocks(html) == ["**Bash**", "Add this to bashrc.", "**Zsh**", "Add this to zshrc."]


def test_tab_labels_match_panels_by_id_not_only_by_order() -> None:
    html = (
        '<button role="tab" id="t0" aria-controls="p0">Bash</button>'
        '<button role="tab" id="t1" aria-controls="p1">Zsh</button>'
        '<div role="tabpanel" id="p1"><p>zsh text</p></div><div role="tabpanel" id="p0"><p>bash text</p></div>'
    )
    assert blocks(html) == ["**Zsh**", "zsh text", "**Bash**", "bash text"]


def test_admonition_kind_leads_its_paragraph() -> None:
    html = (
        '<div class="admonition warning"><p class="admonition-title">Warning</p>'
        "<p>Do not do this.</p></div><p>Next.</p>"
    )
    assert blocks(html) == ["**Warning:** Do not do this.", "Next."]
    code_first = '<div class="admonition note"><p class="admonition-title">Note</p><pre>x</pre></div>'
    assert blocks(code_first) == ["**Note:**", "```\nx\n```"]
    empty = '<div class="admonition note"><p class="admonition-title">Note</p></div><p>Next.</p>'
    assert blocks(empty) == ["**Note:**", "Next."]


# --- 7. rustdoc glyphs --------------------------------------------------------------------------------------


def test_section_sign_permalink_is_dropped_from_headings() -> None:
    doc = convert(
        '<main><h2 id="examples"><a href="#examples" class="doc-anchor">§</a>Examples</h2>'
        '<h2 id="structs">Structs<a href="#structs" class="anchor">§</a></h2>'
        "<h2 id='legal'>§ 5 Scope</h2></main>",
        "x.html",
    )
    assert doc.blocks == ["## Examples", "## Structs", "## § 5 Scope"]
    assert [h.text for h in doc.headings] == ["Examples", "Structs", "§ 5 Scope"]


def test_expand_description_summary_is_dropped() -> None:
    html = (
        '<details class="toggle top-doc" open><summary class="hideme"><span>Expand description</span></summary>'
        '<div class="docblock"><p>Real text.</p></div></details>'
    )
    assert blocks(html) == ["Real text."]


# --- 8. literal asterisks in a definition ------------------------------------------------------------------


def test_star_args_in_a_definition_survive() -> None:
    html = (
        '<dl><dt id="f"><em class="sig-param"><span class="o">*</span><span class="n">args</span></em>, '
        '<em class="sig-param"><span class="o">**</span><span class="n">kwargs</span></em></dt><dd>Body.</dd></dl>'
    )
    assert blocks(html)[0] == "**\\*args, \\*\\*kwargs**"
    code = '<dl><dt id="r"><code>widget.run(speed)</code></dt><dd>Runs.</dd></dl>'
    assert blocks(code)[0] == "**`widget.run(speed)`**"
    in_code = '<dl><dt id="k"><code>f(**kwargs)</code></dt><dd>x</dd></dl>'
    assert blocks(in_code)[0] == "**`f(**kwargs)`**"
