"""HTML to readable markdown, standard library only: the core HTML reader (`cl.reader_html`).

Copied from zimlore `zimlore/markdown.py` at zimlore commit 1903b46, with zimlore's converter tests copied beside
it (`tests/test_readers_html_*.py`). It was first private to the ieee collections (`primarysource/ieee/_html.py`,
now a re-export of this module). The only changes from zimlore are behind `Profile`: with the default `GENERIC`
profile the output is zimlore's, byte for byte, which the copied tests pin. A collection with site-specific rules
defines its own `Profile` value (ieee's `POSIX` lives in `primarysource/ieee/_html.py`).

A ZIM article is whatever the scraper wrote. The devdocs ZIMs wrap each page in an application shell (a
navbar custom element, preload links, a stylesheet) and inline every image as a base64 data URI, so a naive
tag stripper returns kilobytes of base64 before the first heading. This converter keeps what an agent needs:
headings (with their anchors), paragraphs, lists, tables, definition lists, block quotes and, above all,
**code blocks**, with their language when the markup names one. It drops scripts, styles, navigation chrome
and data URIs.

The output is a list of *blocks*. A block is one paragraph, heading, list item, table, code fence or
definition: the unit that paging counts, that a `¶n` reference points at, and that is never split.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

SKIP_TAGS = frozenset(
    {"script", "style", "svg", "nav", "head", "template", "noscript", "button", "select", "iframe", "canvas"}
    | {"devdocs-navbar", "form", "audio", "video", "object", "dialog"}
)
VOID_TAGS = frozenset({"br", "hr", "img", "meta", "link", "input", "wbr", "source", "area", "base", "col", "embed"})
BLOCK_TAGS = frozenset(
    {"p", "div", "section", "article", "header", "footer", "main", "details", "summary", "figure", "figcaption"}
    | {"dl", "dd", "address", "fieldset", "center"}
)
PAGER_RELS = frozenset({"next", "prev", "previous"})
"""HTML link types for pagination. A link with one of them that wraps *block* content (a card with a label and a
heading) is a pager widget and is dropped whole; the same link around inline prose text stays an ordinary link."""
HEADINGS = {f"h{n}": n for n in range(1, 7)}
CLOSES_HEAD = frozenset(HEADINGS) | {"dt", "dd", "pre", "ul", "ol", "li", "blockquote", "table", "hr", "dl"}
"""Start tags that end an open heading or `<dt>` even though its end tag is missing. Other block tags (`p`, `div`)
end it only once it holds text, so `<dt><p>name</p></dt>` still reads as one definition."""
CLOSES_HEAD_END = frozenset({"dl", "ul", "ol", "li", "table", "blockquote", "section", "article", "details"})
MAX_INDENT = 8
"""Nesting levels that are indented. Deeper list items stay at this level: every block repeats its indentation,
so unbounded indentation made the output quadratic in the input (n nested `<ul>` cost 130 MB at n = 8,000)."""
MAX_OUTPUT_CHARS = 4_000_000
"""Ceiling on the converted text of one document. Past it blocks are dropped and `Document.truncated` is set, so a
crafted or merely enormous page cannot grow the process without bound."""
# ARIA landmark roles that are page chrome, whatever the element is called: Sphinx's Read the Docs theme puts the
# whole site menu in a <div role="navigation"> and the Previous/Next buttons in <div role="navigation"> inside a
# <footer>; it has no <main> element to select the content with.
SKIP_ROLES = frozenset({"navigation", "search", "contentinfo"})
CHROME_CLASS_TAGS = frozenset({"div", "span", "ul", "ol", "section", "aside", "header", "footer", "table"})
"""Elements whose class names are read as page chrome. Not `body`, `html`, `a`, headings or `p`: a `<body
class="has-toolbar">` must not empty the page and a `<p class="sidebar-title">` is the sidebar directive's content."""
CHROME_CLASSES = frozenset(
    {"toolbar", "breadcrumb", "breadcrumbs", "pagination", "pager", "prev-next", "page-nav"}
    | {"toc", "table-of-contents", "nav-panel", "mini-toc", "ttc", "lineno", "permalink", "navpath"}
)
"""Whole class names that mark chrome. `nav-panel` and `mini-toc` are Texinfo's per-node Next/Previous/Up bar and
chapter menu, `ttc` is Doxygen's hover tooltip, `lineno` its source line number, `permalink` its member-heading
glyph, `navpath` its breadcrumb; `pagination`, `pager`, `prev-next` and `page-nav` are the previous/next widgets
of doc themes."""
CHROME_WORDS = frozenset({"toolbar", "breadcrumb", "breadcrumbs", "pagination"})
"""A class token whose hyphen- or underscore-separated words include one of these is chrome too (`tsd-page-toolbar`,
`md-breadcrumbs`, `s-pagination--item`). `sidebar` is handled apart: see `is_chrome`."""
REGION_CANDIDATES = ("main", "role", "id", "article")
"""Content-region rules in order of preference: a `<main>` element, an element with `role="main"`, an element
with `id="main-content"`, a *single* `<article>`. See `_region_candidates`."""
# Icon-font glyphs (Font Awesome's permalink U+F0C1, for one) live in the Private Use Area and are noise in text.
PRIVATE_USE = re.compile("[\ue000-\uf8ff]")
TABLE_PARTS = frozenset({"tr", "td", "th", "thead", "tbody", "tfoot"})
CELL_BREAKS = BLOCK_TAGS | frozenset({"li", "ul", "ol", "dt", "blockquote", "tr"}) | frozenset(HEADINGS)
"""Tags that start or end a block inside a table cell. A cell is collected as one string with `\\x01` at each block
boundary, `\\x03` before a list item and `\\x02<n>\\x02` where the n-th `<pre>` of the table sat; the end of the table
decides whether those become one flattened pipe-table cell or real blocks (see `_Builder._finish_table`)."""
CELL_PRE = re.compile("\x02(\\d+)\x02")
CELL_MARKS = re.compile("[\x01\x03]")
CONTROL = re.compile("[\x01-\x03]")
LINE_CLASSES = frozenset({"line", "code-line", "token-line"})
"""Class tokens of the element a highlighter wraps around one source line inside a `<pre>` (Shiki and Chroma
`span.line`, Prism `token-line`). Their end is a line break unless the text already ends with one."""
LANG_NOISE = frozenset({"default", "none", "nohighlight", "notranslate", "line", "lines", "block", "wrapper"})
LANG_PREFIX = re.compile(r"(?:language|lang)[-_](.+)", re.IGNORECASE)
LANG_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_+#.\-]{0,31}")
LANG_MARKERS = frozenset({"highlight", "highlighter-rouge", "sourcecode", "codehilite", "code-block", "codeblock"})
"""A wrapper element only names a fence language through `language-x` when it also carries one of these, so
`<body class="language-en">` (a page language) is not mistaken for a code language."""
FOLD_NOISE = frozenset({"hljs", "highlight", "numberlines", "numbersource", "sourcecode", "prettyprint", "linenums"})
GLYPHS = frozenset({"§", "¶"})
"""Permalink glyphs: a pilcrow (Sphinx) or a section sign (rustdoc) that is the whole text of an anchor."""
GRID_COLUMNS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


@dataclass(frozen=True, slots=True)
class Profile:
    """Site-specific rules on top of zimlore's generic ones. Each is off in `GENERIC`.

    - `chrome_classes`: more whole class names that mark chrome (lowercase).
    - `inner_anchor`: a heading with no `id` of its own takes its anchor from an `<a id>` or `<a name>` that is the
      first thing inside it. The Open Group writes `<h4><a name="tag_17_372_03" id="tag_17_372_03"></a>DESCRIPTION
      </h4>`; zimlore's rule reads ids on the heading or its wrappers only, so every POSIX heading lost its anchor.
    - `small_print_centre`: a `<font size="2">` that is the first element inside a `<center>` is page furniture
      (the edition banner and the trademark footer on every POSIX page). Other `<center>` elements hold tables
      and stay content.
    - `plain_blockquote`: `<blockquote>` is indentation, not quotation, so its blocks get no `> ` mark. The Open
      Group wraps the body of every section in one.
    - `rules`: an `<hr>` becomes a `---` block. Off for POSIX, where every rule is page furniture.
    """

    chrome_classes: frozenset[str] = frozenset()
    inner_anchor: bool = False
    small_print_centre: bool = False
    plain_blockquote: bool = False
    rules: bool = True


GENERIC = Profile()


def fence_language(classes: str, *, wrapper: bool = False) -> str:
    """The code language a class list names, or "". Understands `language-x` / `lang-x` (CommonMark, Prism,
    highlight.js, Docusaurus), Sphinx's and GitHub's `highlight-x` / `highlight-source-x`, SyntaxHighlighter's
    `brush: x`, and the bare second token of pandoc's `sourceCode python` and highlight.js's `hljs python`.
    With `wrapper` set the list belongs to an enclosing element, where `language-x` needs a marker class."""
    tokens = classes.split()
    lowered = [token.lower() for token in tokens]
    candidates: list[str] = []
    for index, token in enumerate(tokens):
        low = lowered[index]
        named = LANG_PREFIX.match(token)
        if named:
            if not wrapper or LANG_MARKERS.intersection(lowered):
                candidates.append(named.group(1))
        elif low.startswith("highlight-"):
            rest = token[10:]
            candidates.append(rest[7:] if rest.lower().startswith("source-") else rest)
        elif low.startswith("brush:"):
            candidates.append(token[6:] or (tokens[index + 1] if index + 1 < len(tokens) else ""))
    if not candidates and ("sourcecode" in lowered or "hljs" in lowered):
        candidates = [t for t, low in zip(tokens, lowered, strict=True) if low not in FOLD_NOISE]
    for candidate in candidates:
        if LANG_NAME.fullmatch(candidate) and candidate.lower() not in LANG_NOISE:
            return candidate
    return ""


@dataclass(frozen=True)
class Heading:
    """An addressable place in a document: a real heading, or a definition (`<dt id=...>`) in an API reference."""

    level: int
    text: str
    anchor: str
    block: int
    kind: str = "heading"


@dataclass(frozen=True)
class Link:
    text: str
    href: str
    path: str | None  # resolved ZIM path for an internal link, None for an external one
    anchor: str


@dataclass
class Document:
    title: str
    blocks: list[str]
    headings: list[Heading] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    dropped_images: int = 0
    tight: list[bool] = field(default_factory=list)
    truncated: bool = False
    aliases: dict[str, int] = field(default_factory=dict)
    """Anchor -> position in `headings`, for ids that sit on a wrapper element next to a heading rather than on the
    heading itself (Texinfo's `<div class="section-level-extent" id="Exit-Status">`). Not outline entries."""

    @property
    def markdown(self) -> str:
        return join_blocks(self.blocks, self.tight)

    def span(self, position: int) -> tuple[int, int]:
        """Half-open block range owned by `self.headings[position]`. A heading owns everything up to the next
        heading of the same or a shallower level; a definition owns its body up to the next addressable place."""
        head = self.headings[position]
        end = len(self.blocks)
        for later in self.headings[position + 1 :]:
            if head.kind == "definition" or (later.kind == "heading" and later.level <= head.level):
                end = later.block
                break
        return head.block, max(end, head.block + 1)

    def section(self, anchor: str) -> tuple[int, int] | None:
        """Block range of the section or definition an anchor names. Anchors are unique within a document
        (the converter suffixes repeats, see `_Builder._unique`), so there is exactly one."""
        for position, head in enumerate(self.headings):
            if head.anchor == anchor:
                return self.span(position)
        if anchor in self.aliases:
            return self.span(self.aliases[anchor])
        return None


def join_blocks(blocks: list[str], tight: list[bool] | None = None) -> str:
    """Blank line between blocks, except that consecutive list items stay together."""
    out: list[str] = []
    for index, block in enumerate(blocks):
        if index:
            out.append("\n" if tight and tight[index] and tight[index - 1] else "\n\n")
        out.append(block)
    return "".join(out)


def resolve_href(base: str, href: str) -> tuple[str | None, str]:
    """Resolve a link found in the article at `base` to (ZIM path, anchor). A scheme or `//host` target is
    external and has no path. ZIM paths have no leading slash and `..` is resolved against the article's own
    directory, which is how the scrapers write relative links."""
    parts = urlsplit(href.strip())
    anchor = unquote(parts.fragment)
    if parts.scheme or parts.netloc:
        return None, anchor
    target = unquote(parts.path)
    if not target:
        return base, anchor
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/")), anchor
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(base), target))
    return ("" if joined == "." else joined), anchor


class _Depth:
    """One element being tracked by its own tag name: open it, count only the same-named tags nested inside, and
    it ends when that count returns to zero. Stray, void or misnested tags of other names are ignored, which is
    what real HTML needs: Starlette's table-of-contents template writes `<li></li><a>..</a></li>` inside a `<nav>`,
    and a counter that decremented on *every* end tag reached zero while the nav was still open."""

    __slots__ = ("depth", "tag")

    def __init__(self) -> None:
        self.tag = ""
        self.depth = 0

    def __bool__(self) -> bool:
        return self.depth > 0

    def open(self, tag: str) -> None:
        self.tag = tag
        self.depth = 1

    def nest(self, tag: str) -> None:
        if self.depth and tag == self.tag:
            self.depth += 1

    def close(self, tag: str) -> bool:
        """True when this end tag closes the tracked element itself."""
        if self.depth and tag == self.tag:
            self.depth -= 1
            return self.depth == 0
        return False


def is_chrome(
    tag: str,
    attrs: dict[str, str],
    in_container: bool = False,
    *,
    links: bool = False,
    extra: frozenset[str] = frozenset(),
) -> bool:
    """Is this element page chrome (navigation, toolbar, tooltip) whose content is not documentation?

    `in_container` says that an `<article>` or `<section>` is open, where a `<footer>` is the article's own byline
    rather than the page footer. With `links=True` only the chrome whose links are noise too is reported."""
    if tag in VOID_TAGS:
        return False
    if tag in SKIP_TAGS or attrs.get("role", "").lower() in SKIP_ROLES:
        return True
    if tag == "footer" and not in_container:
        return True
    if tag not in CHROME_CLASS_TAGS or not attrs.get("class"):
        return False
    for token in attrs["class"].lower().split():
        words = re.split(r"[-_]", token)
        # A bare `sidebar` is Sphinx's own directive, whose content is documentation (the asyncio Hello World
        # example); a compound such as `col-sidebar` or `sidebar-drawer` is the site's column.
        sidebar = len(words) > 1 and "sidebar" in words and tag != "span"
        if sidebar or "toolbar" in words:
            return True
        # Pager, breadcrumb and Texinfo node-bar links stay in `zim_links`: they are the neighbouring chapters,
        # while a sidebar tree is thousands of site-wide links.
        if not links and (token in CHROME_CLASSES or token in extra or CHROME_WORDS.intersection(words)):
            return True
    return False


def _region_candidates(html: str) -> list[str]:
    """The content-region rules that this page might satisfy, in order of preference. A page that has no `<main>`
    often has `role="main"` on a div or article (Furo, Read the Docs, Stack Exchange), `id="main-content"`, or a
    single `<article>`. Several `<article>`s (a blog index, a list of questions) are the content *list*, not one
    region, and are never selected. The scan is textual, so a candidate can be a false positive (inside a script
    or a comment): `convert` falls back to the next rule when the parser never enters the region."""
    found: list[str] = []
    if re.search(r"<main\b", html, re.IGNORECASE):
        found.append("main")
    if re.search(r"\brole\s*=\s*[\"']?main(?![\w-])", html, re.IGNORECASE):
        found.append("role")
    if re.search(r"\bid\s*=\s*[\"']?main-content(?![\w-])", html, re.IGNORECASE):
        found.append("id")
    if len(re.findall(r"<article\b", html, re.IGNORECASE)) == 1:
        found.append("article")
    return found


class _Region:
    """The part of the page that is read. `kind` is one of `REGION_CANDIDATES`, or empty for the whole body."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.element = _Depth()
        self.entered = False

    @property
    def inside(self) -> bool:
        return not self.kind or bool(self.element)

    def start(self, tag: str, attrs: dict[str, str]) -> bool:
        """Feed a start tag; True when it opens the region's own element."""
        if self.element:
            self.element.nest(tag)
            return False
        if tag in VOID_TAGS or not self.kind:
            return False
        matches = {
            "main": tag == "main",
            "role": attrs.get("role", "").strip().lower() == "main",
            "id": attrs.get("id", "") == "main-content",
            "article": tag == "article",
        }[self.kind]
        if matches:
            self.element.open(tag)
            self.entered = True
        return matches

    def end(self, tag: str) -> bool:
        """Feed an end tag; True when it closes the region's own element."""
        return self.element.close(tag)


class _Builder(HTMLParser):
    def __init__(self, base: str, region: str = "", profile: Profile = GENERIC) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.profile = profile
        self._after_centre = False  # the last start tag was <center> (Profile.small_print_centre)
        self._head_inherited = False  # the open heading's anchor came from a wrapper, not its own id
        self.region = _Region(region)
        self.title_outside = False  # an <h1> was seen outside the region (and outside any chrome)
        self.title = ""
        self.blocks: list[str] = []
        self.headings: list[Heading] = []
        self.links: list[Link] = []
        self.dropped_images = 0
        self._skip = _Depth()  # the chrome element being skipped, if any
        self._frag = _Depth()  # a Doxygen `div.fragment` source listing being read as one code block
        self._pending_ids: list[str] = []  # ids seen since the last block, candidates for a heading's aliases
        self._head_aliases: list[str] = []
        self.aliases: dict[str, int] = {}
        self._in_title = False
        self._title_parts: list[str] = []
        self._buf: list[str] = []
        self._ids: list[tuple[str, str, str]] = []  # (tag, id, class) of every open element
        self._lists: list[list[int]] = []  # [ordered?, counter] per open list
        self._quote = 0
        self._item_prefix: str | None = None
        self._head: tuple[int, str, str] | None = None  # level, anchor, kind of the heading being read
        self._pre: list[str] | None = None
        self._pre_lang = ""
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._cell_pre: list[str] | None = None  # a <pre> inside a table cell: see _finish_table
        self._cell_pres: list[tuple[str, str]] = []  # (language, code) of each <pre> met in the table's cells
        self._nested = 0  # open <table>s inside a cell: their markup is flattened into the cell
        self._grid: _Grid | None = None  # a javadoc div.summary-table being read as a table
        self._code_stack: list[str] = []  # open elements inside the current <pre>
        self._code_break = False  # a line ended inside the <pre> and its newline has not been written
        self._code_closed = 0  # <code> children of the current <pre> already closed
        self._tab: list[str] | None = None  # id, aria-controls, text of the <button role=tab> being read
        self._tabs: list[tuple[str, str, str]] = []  # (id, controls, label) of tabs not yet matched to a panel
        self._lead: str | None = None  # admonition kind waiting to prefix the next paragraph
        self._title: tuple[str, int] | None = None  # tag and depth of an open admonition-title
        self._glyph: int | None = None  # buffer index where an <a> inside a heading began
        self._header_row = False
        self._code = 0
        self._link_mark: tuple[int, str] | None = None  # buffer index of the "[" and the target
        self._cell_link: tuple[int, str] | None = None
        self._tight_marks: list[bool] = []
        self._chars = 0
        self.truncated = False
        self._anchors: dict[str, int] = {}  # anchor -> how many headings have claimed it
        self._pager: tuple[int, int, int] | None = (
            None  # blocks, headings, buffer length at an open rel=next/prev link
        )

    # --- region selection -------------------------------------------------------------------------------
    @property
    def _live(self) -> bool:
        return not self._skip and self.region.inside

    def _in_container(self) -> bool:
        """Is an `<article>` or `<section>` open? A `<footer>` there is its byline, not the page footer."""
        return any(entry[0] in {"article", "section"} for entry in self._ids)

    # --- output helpers ---------------------------------------------------------------------------------
    def _text(self) -> str:
        return re.sub(r"[ \t\r\f\v\n]+", " ", "".join(self._buf)).strip()

    def _emit(self, block: str, *, tight: bool = False) -> None:
        self._pending_ids = []  # text came between an earlier id and whatever heading follows
        if self._lead is not None:
            self._emit_lead()  # the next block is not a paragraph (a fence, a table, a definition)
        if self._quote:
            block = "\n".join(("> " + line).rstrip() for line in block.split("\n"))
        if self._chars + len(block) > MAX_OUTPUT_CHARS:
            self.truncated = True
            return
        self._chars += len(block) + 2
        self.blocks.append(block)
        self._tight_marks.append(tight)

    def _emit_lead(self) -> None:
        """An admonition's kind (`Note`, `Warning`) as a line of its own, when no paragraph came to carry it."""
        lead, self._lead = self._lead, None
        if lead is not None:
            self._emit(f"**{lead}:**")

    def _flush(self) -> None:
        if self._head is not None:
            return  # a heading collects its own text on close
        if self._link_mark is not None:
            # A block boundary inside an open link (<a><h2>..</h2></a>, card links wrapping <div>s): markdown
            # links cannot span blocks, so the link is dropped and its text kept. Without this the "[" already in
            # the buffer became a block of its own - on 91% of mankier pages in a sample of 1,802.
            index = self._link_mark[0]
            if index < len(self._buf) and self._buf[index] == "[":
                del self._buf[index]
            self._link_mark = None
            if self._pager is not None:
                # Prose before a rel=next/prev link is not part of the card: emit it, then start the card here.
                tail = self._buf[index:]
                self._buf = self._buf[:index]
                self._flush()
                self._buf = tail
                self._pager = (len(self.blocks), len(self.headings), 0)
        text = self._text()
        self._buf = []
        if not text:
            return
        if self._lead is not None:
            text, self._lead = f"**{self._lead}:** {text}", None
        if self._item_prefix is not None:
            depth = min(len(self._lists) - 1, MAX_INDENT)
            self._emit("  " * max(depth, 0) + self._item_prefix + text, tight=True)
            self._item_prefix = None
        else:
            indent = "  " * min(len(self._lists), MAX_INDENT)
            self._emit(indent + text)

    def _unique(self, anchor: str) -> str:
        """An anchor no earlier heading has claimed: the second claimant of `content` becomes `content-2`. Without
        this every heading under `<div id=content>` shared one anchor and only the first could be addressed."""
        if not anchor:
            return ""
        seen = self._anchors.get(anchor, 0)
        self._anchors[anchor] = seen + 1
        if not seen:
            return anchor
        while True:
            seen += 1
            candidate = f"{anchor}-{seen}"
            if candidate not in self._anchors:
                self._anchors[candidate] = 1
                self._anchors[anchor] = seen
                return candidate

    def _anchor_here(self, attrs: dict[str, str]) -> str:
        if attrs.get("id"):
            return self._unique(attrs["id"])
        for _, ident, _ in reversed(self._ids):
            if ident:
                return self._unique(ident)
        return ""

    def _note_id(self, tag: str, attrs: dict[str, str]) -> None:
        """Remember an id that sits on something other than a heading, until text or a heading follows it. Texinfo
        names a node on a wrapper `<div id="Exit-Status">` and gives the heading inside it another id, and Doxygen
        puts `<a id=...>` just before a member's heading; links and `#anchor` reads use the wrapper's id."""
        if tag in HEADINGS or tag == "dt":
            return
        ident = attrs.get("id") or (attrs.get("name", "") if tag == "a" else "")
        if ident:
            self._pending_ids.append(ident)
            del self._pending_ids[:-8]  # an index chapter is thousands of empty anchors in a row

    def _heading_head(self, tag: str, attrs: dict[str, str]) -> tuple[int, str, str]:
        """What a heading start tag opens. The ids pending since the last block become its aliases, except for a
        Doxygen member title (`h2.memtitle`): that is a definition, the way a Sphinx `<dt id>` is, anchored by the
        `<a id>` just before it, and not a section at the level of the `Function Documentation` it sits under."""
        pending, self._pending_ids = self._pending_ids, []
        if "memtitle" in attrs.get("class", "").lower().split():
            return 0, pending[-1] if pending else "", "definition"
        self._head_aliases = pending
        self._head_inherited = not attrs.get("id")
        return HEADINGS[tag], self._anchor_here(attrs), "heading"

    def _fragment_opens(self, tag: str, attrs: dict[str, str]) -> bool:
        """Doxygen writes a source listing and `@code` examples as `<div class="fragment">` holding one
        `<div class="line">` per line: read it as a pre-formatted block instead of one paragraph per line."""
        if tag != "div" or self._pre is not None or self._cell is not None:
            return False
        if "fragment" not in attrs.get("class", "").lower().split():
            return False
        if self._head is not None and self._text():
            self._close_head()
        self._flush()
        self._pre = []
        self._pre_lang = ""
        self._frag.open("div")
        return True

    def _fragment_done(self) -> None:
        body = "".join(self._pre or []).strip("\n").rstrip()
        self._pre = None
        if body.strip():
            self._emit(_fenced(body))

    def _close_head(self) -> None:
        """Finish the heading or definition being read, as if its end tag had arrived. HTML lets `</dt>`,
        `</dd>` and `</p>` be omitted, and a browser reads `<h2>Title<p>Body</p>` as a heading and a paragraph.
        Waiting for an end tag that never comes swallowed the rest of the page (found in review, C1)."""
        if self._head is None:
            return
        level, anchor, kind = self._head
        self._head = None
        text = self._text().rstrip(chr(0xB6)).rstrip()  # a trailing pilcrow is a permalink glyph
        self._buf = []
        aliases, self._head_aliases = self._head_aliases, []
        if not text:
            return
        if kind == "heading":
            for ident in aliases:
                if ident not in self._anchors:  # a real heading anchor always wins over a wrapper's id
                    self.aliases.setdefault(ident, len(self.headings))
            self.headings.append(Heading(level, text, anchor, len(self.blocks), kind))
            self._emit("#" * level + " " + text)
        else:
            if kind == "definition" and text.lower() == "expand description":
                return  # rustdoc's toggle label, not a term
            if anchor:
                self.headings.append(Heading(7, text, self._unique(anchor), len(self.blocks), kind))
            self._emit("**" + _escape_asterisks(text) + "**")

    # --- parser callbacks -------------------------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        if tag == "title":
            self._in_title = True
            return
        if self._skip:
            self._skip.nest(tag)
            return
        after_centre, self._after_centre = self._after_centre, tag == "center"
        small_print = tag == "font" and attrs.get("size", "").strip() == "2"
        if self.profile.small_print_centre and after_centre and small_print:
            self._skip.open(tag)
            return
        if is_chrome(tag, attrs, tag == "footer" and self._in_container(), extra=self.profile.chrome_classes):
            if tag == "button" and attrs.get("role", "").lower() == "tab" and self._live:
                # sphinx-tabs: the label is the only thing that says which shell or language a panel is for.
                self._tab = [attrs.get("id", ""), attrs.get("aria-controls", ""), ""]
            self._skip.open(tag)
            return
        if self.region.start(tag, attrs) and tag == "main":
            return
        if tag == "h1" and not self.region.inside:
            self.title_outside = True
        if not self._live:
            return
        if self._frag:
            self._frag.nest(tag)  # inside a source listing the tags are layout; the text goes to the fence
            return
        if self._fragment_opens(tag, attrs):
            return
        self._note_id(tag, attrs)
        if tag not in VOID_TAGS:
            self._ids.append((tag, attrs.get("id", ""), attrs.get("class", "")))
        if self._grid is not None and self._grid_start(tag, attrs):
            return
        if self._table is not None and self._table_start(tag, attrs):
            return
        if self._cell is not None:
            self._cell_start(tag, attrs)
            return
        self._start_block(tag, attrs)

    # --- tables -----------------------------------------------------------------------------------------
    def _table_start(self, tag: str, attrs: dict[str, str]) -> bool:
        """Row and cell structure of an open `<table>`, with HTML's implied end tags: `<tr>` closes the open row
        and cell, `<td>`/`<th>` close the open cell. Returns True when the tag was consumed."""
        if tag == "table" and self._cell is not None:
            self._nested += 1  # a table inside a cell is read as text of that cell
            self._cell.append("\x01")
            return True
        if tag not in TABLE_PARTS:
            return False
        if self._nested:
            if self._cell is not None:
                self._cell.append("\x01" if tag == "tr" else " ")
            return True
        if tag in {"td", "th"}:
            self._close_cell()
            if self._row is None:
                self._row = []  # `<td>` without `<tr>`: the row is implied
            self._cell = []
            if tag == "th":
                self._header_row = True
        else:
            self._close_row()
            if tag == "tr":
                self._row = []
        return True

    def _close_cell(self) -> None:
        if self._cell is None:
            return
        if self._cell_pre is not None:
            self._end_cell_pre()
        if self._row is not None:
            self._row.append("".join(self._cell))
        self._cell = None
        self._cell_link = None

    def _close_row(self) -> None:
        self._close_cell()
        if self._row and self._table is not None:
            self._table.append(self._row)
        self._row = None

    def _end_cell_pre(self) -> None:
        if self._cell is None or self._cell_pre is None:
            return
        code = "".join(self._cell_pre).strip("\n").rstrip()
        self._cell_pre = None
        if code.strip():
            self._cell_pres.append((self._pre_lang, code))
            self._cell.append(f"\x01\x02{len(self._cell_pres) - 1}\x02\x01")
        self._pre_lang = ""

    def _table_end(self, tag: str) -> bool:
        if self._nested:
            if tag == "table":
                self._nested -= 1
            if tag in TABLE_PARTS or tag == "table":
                if self._cell is not None:
                    self._cell.append("\x01" if tag in {"tr", "table"} else " ")
                return True
            return False
        if tag in {"td", "th"}:
            self._close_cell()
        elif tag in TABLE_PARTS:
            self._close_row()
        elif tag == "table":
            self._finish_table()
        else:
            return False
        return True

    def _finish_table(self) -> None:
        self._close_row()
        rows, self._table = self._table or [], None
        pres, self._cell_pres = self._cell_pres, []
        self._cell = None
        self._row = None
        if not rows:
            return
        if _is_box(rows):
            self._emit_box(rows, pres)
        else:
            self._emit(_render_table([[_gfm_cell(cell, pres) for cell in row] for row in rows]))

    def _emit_box(self, rows: list[list[str]], pres: list[tuple[str, str]]) -> None:
        """A layout table (see `_is_box`): its cells become ordinary blocks, in reading order."""
        indent = "  " * min(len(self._lists), MAX_INDENT)
        for row in rows:
            for cell in row:
                for segment in cell.split("\x01"):
                    pieces = CELL_PRE.split(segment)
                    for index, piece in enumerate(pieces):
                        if index % 2:
                            lang, code = pres[int(piece)]
                            self._emit(_fenced(code, lang))
                            continue
                        bullet = "\x03" in piece
                        text = re.sub(r"\s+", " ", CELL_MARKS.sub(" ", piece)).strip()
                        if text:
                            self._emit(indent + ("- " if bullet else "") + text)

    # --- div grids (javadoc 17+ summary tables) ---------------------------------------------------------
    def _grid_start(self, tag: str, attrs: dict[str, str]) -> bool:
        grid = self._grid
        if grid is None or tag != "div":
            return False
        grid.depth += 1
        if grid.depth != 2:
            return False  # a div inside a cell is cell content
        grid.header = "table-header" in attrs.get("class", "").split()
        self._cell = []
        return True

    def _grid_end(self, tag: str) -> bool:
        grid = self._grid
        if grid is None or tag != "div":
            return False
        grid.depth -= 1
        if grid.depth == 1 and self._cell is not None:
            if self._cell_pre is not None:
                self._end_cell_pre()
            grid.cells.append((grid.header, "".join(self._cell)))
            self._cell = None
            self._cell_link = None
            return True
        if grid.depth == 0:
            self._grid = None
            headers = [text for is_head, text in grid.cells if is_head]
            body = [text for is_head, text in grid.cells if not is_head]
            width = len(headers) or grid.columns
            pres, self._cell_pres = self._cell_pres, []
            rows = [headers or [""] * width]
            rows += [body[i : i + width] for i in range(0, len(body), width)]
            if body or headers:
                self._emit(_render_table([[_gfm_cell(cell, pres) for cell in row] for row in rows]))
            return True
        return False

    def _cell_start(self, tag: str, attrs: dict[str, str]) -> None:
        if self._cell is None:
            return
        if self._cell_pre is not None:
            self._code_start(tag, attrs, self._cell_pre)
            return
        if tag == "pre":
            self._cell_pre = []
            self._code_reset()
            self._pre_lang = self._language_for(attrs)
        elif tag == "br":
            self._cell.append(" ")
        elif tag == "code":
            self._cell.append("`")
        elif tag in CELL_BREAKS:
            self._cell.append("\x01\x03" if tag == "li" else "\x01")
        elif tag == "a" and attrs.get("href"):
            self._cell_link = self._open_link(self._cell, attrs["href"])
        elif tag == "img":
            self._cell.append(self._image(attrs))

    def _image(self, attrs: dict[str, str]) -> str:
        self.dropped_images += 1
        alt = re.sub(r"\s+", " ", attrs.get("alt", "")).strip()
        return f"[image: {alt}]" if alt and not alt.startswith("_images/") else "[image]"

    # --- code blocks ------------------------------------------------------------------------------------
    def _code_reset(self) -> None:
        self._code_stack = []
        self._code_break = False
        self._code_closed = 0

    def _code_text(self, sink: list[str], data: str) -> None:
        if self._code_break:
            self._code_break = False
            if not data.startswith("\n"):
                sink.append("\n")
        sink.append(data)

    def _code_newline(self, sink: list[str]) -> None:
        """A line break the markup asks for. It is written lazily: a newline character that follows (Shiki writes
        `</span>\\n<span class=line>`) is the same break, not a blank line, and a break at the very end of the
        block is not written at all. A second break in a row does write the first, so `<br><br>` is a blank line."""
        if self._code_break:
            sink.append("\n")
        self._code_break = True

    def _code_start(self, tag: str, attrs: dict[str, str], sink: list[str]) -> None:
        """A tag inside `<pre>`: `<br>` and per-line wrappers end lines (TypeDoc, Dokka, javadoc 8 separate the
        lines of a snippet with `<br>` and no newline character at all), `<img>` is dropped, the rest is inline
        markup around text that already is the code."""
        if tag == "br":
            self._code_newline(sink)
            return
        if tag == "img":
            self.dropped_images += 1  # javadoc 8's inheritance-tree gifs: not code
            return
        if tag in VOID_TAGS:
            return
        direct = not self._code_stack
        if tag == "code" and direct:
            if self._code_closed and sink and not sink[-1].endswith("\n"):
                self._code_break = True  # one <code> per line
            if sink is self._pre and not self._pre_lang:
                self._pre_lang = fence_language(attrs.get("class", "")) or attrs.get("data-language", "")
        elif self._is_line(tag, attrs) and self._code_break:
            self._code_break = False
            sink.append("\n")
        self._code_stack.append(tag + ("\x00line" if self._is_line(tag, attrs) else ""))

    @staticmethod
    def _is_line(tag: str, attrs: dict[str, str]) -> bool:
        return tag in {"div", "span", "p", "li"} and bool(
            LINE_CLASSES.intersection(attrs.get("class", "").lower().split())
        )

    def _code_pop(self, tag: str) -> bool:
        """Close `tag` inside the pre if it is open there. Returns whether it was."""
        for index in range(len(self._code_stack) - 1, -1, -1):
            if self._code_stack[index].split("\x00")[0] == tag:
                del self._code_stack[index:]
                return True
        return False

    def _code_end(self, tag: str, sink: list[str]) -> None:
        for index in range(len(self._code_stack) - 1, -1, -1):
            entry = self._code_stack[index]
            if entry.split("\x00")[0] != tag:
                continue
            del self._code_stack[index:]
            if "\x00line" in entry:
                if sink and not sink[-1].endswith("\n"):
                    self._code_break = True
            elif tag == "code" and index == 0:
                self._code_closed += 1
            return

    def _language_for(self, attrs: dict[str, str]) -> str:
        """Fence language of a `<pre>` that has just been pushed on `_ids`: its own attributes, then its
        wrapper (Sphinx `div.highlight-python`, Material `div.language-python.highlight`, pandoc)."""
        own = attrs.get("data-language") or attrs.get("data-lang") or fence_language(attrs.get("class", ""))
        if own:
            return own
        for _, _, classes in reversed(self._ids[-5:-1]):
            found = fence_language(classes, wrapper=True)
            if found:
                return found
        return ""

    def _tab_panel(self, attrs: dict[str, str]) -> None:
        """The label of the `<button role=tab>` a `role=tabpanel` belongs to, as a bold line before it."""
        if not self._tabs:
            return
        wanted = {attrs.get("id", ""), attrs.get("aria-labelledby", "")} - {""}
        pick = next((i for i, (ident, controls, _) in enumerate(self._tabs) if {ident, controls} & wanted), 0)
        label = self._tabs.pop(pick)[2]
        self._flush()
        self._emit("**" + _escape_asterisks(label) + "**")

    def _start_block(self, tag: str, attrs: dict[str, str]) -> None:
        if self._pre is not None:
            self._code_start(tag, attrs, self._pre)
            return
        if self._head is not None and (tag in CLOSES_HEAD or (tag in BLOCK_TAGS and self._text())):
            self._close_head()
        if tag == "a" and self.profile.inner_anchor:
            self._inner_anchor(attrs)
        if attrs.get("role", "").lower() == "tabpanel":
            self._tab_panel(attrs)
        if "admonition-title" in attrs.get("class", "").split():
            self._flush()
            self._title = (tag, len(self._ids))
            return
        if tag in HEADINGS:
            self._flush()
            self._head = self._heading_head(tag, attrs)
        elif tag == "dt":
            self._flush()
            self._head = (0, attrs.get("id", ""), "definition")
        elif tag == "pre":
            self._flush()
            self._pre = []
            self._code_reset()
            self._pre_lang = self._language_for(attrs)
        elif tag == "summary":
            self._flush()
            parent = self._ids[-2] if len(self._ids) > 1 else None
            if parent is not None and parent[0] == "details" and parent[1]:
                # <details id=...><summary>Example (X)</summary>: the summary names the part, so it is a
                # definition and the id is its anchor. Without an id the summary stays a plain line.
                self._head = (0, parent[1], "definition")
        elif tag in {"ul", "ol"}:
            self._flush()
            self._lists.append([1 if tag == "ol" else 0, 0])
        elif tag == "li":
            self._flush()
            if self._lists:
                kind = self._lists[-1]
                kind[1] += 1
                self._item_prefix = f"{kind[1]}. " if kind[0] else "- "
            else:
                self._item_prefix = "- "
        elif tag == "blockquote":
            self._flush()
            self._quote += 0 if self.profile.plain_blockquote else 1
        elif tag == "table":
            self._flush()
            self._table = []
            self._row = None
            self._nested = 0
            self._cell_pres = []
            self._header_row = False
        elif tag == "div" and "summary-table" in attrs.get("class", "").split():
            self._flush()
            columns = next((n for word, n in GRID_COLUMNS.items() if f"{word}-column-summary" in attrs["class"]), 1)
            self._grid = _Grid(columns)
            self._table = None
        elif tag == "br":
            self._buf.append(" ")
        elif tag == "hr":
            self._flush()
            if self.profile.rules:
                self._emit("---")
        elif tag == "code" and self._pre is None:
            self._code += 1
            self._buf.append("`")
        elif tag in {"em", "i"} and self._pre is None and self._head is None:
            self._buf.append("*")
        elif tag in {"strong", "b"} and self._pre is None and self._head is None:
            self._buf.append("**")
        elif tag == "a" and self._head is not None and not (self._head[2] == "definition" and not self._head[1]):
            self._glyph = len(self._buf)  # a link inside a heading is plain text, but its glyph is dropped
        elif tag == "a" and attrs.get("href"):
            if PAGER_RELS.intersection(attrs.get("rel", "").lower().split()):
                self._pager = (len(self.blocks), len(self.headings), len(self._buf))
            self._link_mark = self._open_link(self._buf, attrs["href"])
        elif tag == "img":
            self._buf.append(self._image(attrs))
        elif tag in BLOCK_TAGS:
            self._flush()

    def _inner_anchor(self, attrs: dict[str, str]) -> None:
        """`Profile.inner_anchor`: an `<a id>`/`<a name>` before any text of a heading that has no id of its own
        names that heading (The Open Group's markup)."""
        head = self._head
        if head is None or head[2] != "heading" or not self._head_inherited or self._text():
            return
        ident = attrs.get("id") or attrs.get("name", "")
        if ident:
            self._head = (head[0], self._unique(ident), head[2])
            self._head_inherited = False

    def _open_link(self, sink: list[str], href: str) -> tuple[int, str] | None:
        """Start a markdown link in `sink`. Script and mailto targets are not links; the rest is resolved
        against this article so an internal target reads as a ZIM path an agent can follow."""
        if href.lower().startswith(("javascript:", "data:", "mailto:", "tel:")):
            return None
        path, anchor = resolve_href(self.base, href)
        target = (path or "") + ("#" + anchor if anchor else "") if path is not None else href.strip()
        sink.append("[")
        return len(sink) - 1, target

    @staticmethod
    def _close_link(sink: list[str], mark: tuple[int, str] | None) -> None:
        if mark is None:
            return
        index, target = mark
        label = "".join(sink[index + 1 :]).strip()
        if not label or label in {"¶", "#", "§"}:
            del sink[index:]  # an empty or permalink-glyph anchor carries nothing
        else:
            sink.append(f"]({target})")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            self.title = re.sub(r"\s+", " ", "".join(self._title_parts)).strip()
            return
        if self._skip:
            if self._skip.close(tag) and self._tab is not None and tag == "button":
                label = re.sub(r"\s+", " ", self._tab[2]).strip()
                if label:
                    self._tabs.append((self._tab[0], self._tab[1], label))
                self._tab = None
            return
        closed = self.region.end(tag)
        if closed:
            self._close_head()
            self._flush()
            if tag == "main":
                return
        elif not self._live:
            return
        if self._frag:
            depth = self._frag.depth
            if self._frag.close(tag):
                self._fragment_done()
            elif tag == "div" and depth == 2 and self._pre is not None:
                self._pre.append("\n")  # `</div>` of a `div.line`: one source line per line element
            return
        if tag not in VOID_TAGS:
            while self._ids:
                if self._ids.pop()[0] == tag:
                    break
        if self._grid is not None and self._grid_end(tag):
            return
        if self._table is not None and self._table_end(tag):
            return
        if self._cell is not None:
            if self._cell_pre is not None:
                if tag == "pre" and not self._code_pop(tag):
                    self._end_cell_pre()
                elif tag != "pre":
                    self._code_end(tag, self._cell_pre)
                return
            if tag == "code":
                self._cell.append("`")
            elif tag == "a":
                self._close_link(self._cell, self._cell_link)
                self._cell_link = None
            elif tag in CELL_BREAKS:
                self._cell.append("\x01")
            elif tag in {"td", "th"}:
                self._cell.append(" ")
            return
        self._end_block(tag)

    def _end_block(self, tag: str) -> None:
        if self._pre is not None and (tag != "pre" or self._code_pop(tag)):
            self._code_end(tag, self._pre)
            return
        if self._title is not None and tag == self._title[0] and len(self._ids) == self._title[1] - 1:
            kind = self._text().rstrip(":").strip()
            self._buf = []
            self._title = None
            self._lead = kind if kind and len(kind) <= 60 else None
            return
        if self._head is not None and tag in CLOSES_HEAD_END:
            self._close_head()
        if tag in HEADINGS or tag == "dt":
            self._close_head()
        elif tag == "summary":
            if self._head is not None:
                self._close_head()
            else:
                if self._text().lower() == "expand description":
                    self._buf = []  # rustdoc's toggle label
                self._flush()
        elif tag == "pre" and self._pre is not None:
            body = "".join(self._pre).strip("\n").rstrip()
            lang = self._pre_lang
            self._pre = None
            self._pre_lang = ""
            if body.strip():
                self._emit(_fenced(body, lang))
        elif tag in {"ul", "ol"}:
            self._flush()
            if self._lists:
                self._lists.pop()
        elif tag == "li":
            self._flush()
            self._item_prefix = None
        elif tag == "blockquote":
            self._flush()
            if not self.profile.plain_blockquote:
                self._quote = max(0, self._quote - 1)
        elif tag == "code" and self._pre is None:
            self._code = max(0, self._code - 1)
            self._buf.append("`")
        elif tag in {"em", "i"} and self._pre is None and self._head is None:
            self._buf.append("*")
        elif tag in {"strong", "b"} and self._pre is None and self._head is None:
            self._buf.append("**")
        elif tag == "a" and self._glyph is not None:
            if "".join(self._buf[self._glyph :]).strip() in GLYPHS:
                del self._buf[self._glyph :]
            self._glyph = None
        elif tag == "a" and self._pager is not None:
            blocks, heads, buffered = self._pager
            self._pager = None
            if len(self.blocks) > blocks:
                # A pager card: rel=next/prev around block content. Everything it emitted is navigation, not text.
                del self.blocks[blocks:], self._tight_marks[blocks:], self.headings[heads:]
                del self._buf[buffered:]
                self._link_mark = None
            elif self._link_mark is not None:
                self._close_link(self._buf, self._link_mark)
                self._link_mark = None
        elif tag == "a" and self._link_mark is not None:
            self._close_link(self._buf, self._link_mark)
            self._link_mark = None
        elif tag in BLOCK_TAGS or tag == "dd":
            self._flush()
            if self._lead is not None and tag in {"div", "section", "article", "details", "figure"}:
                self._emit_lead()  # the admonition ended without a paragraph to prefix

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._tab is not None and self._skip:
            self._tab[2] += data
            return
        if not self._live:
            return
        data = PRIVATE_USE.sub("", data)
        if self._cell is not None or self._grid is not None:
            data = CONTROL.sub("", data)  # the cell markers are control characters; none belongs in text
        if not data:
            return
        if self._frag and self._frag.depth == 1 and not data.strip():
            return  # the newline Doxygen writes between two line elements is not a line
        if self._pre is not None:
            self._code_text(self._pre, data)
        elif self._cell_pre is not None:
            self._code_text(self._cell_pre, data)
        elif self._cell is not None:
            self._cell.append(data)
        else:
            self._buf.append(data)


def _fenced(body: str, lang: str = "") -> str:
    fence = "```"
    while fence in body:
        fence += "`"
    return f"{fence}{lang}\n{body}\n{fence}"


def _gfm_cell(raw: str, pres: list[tuple[str, str]]) -> str:
    """One pipe-table cell from the marked-up text `_Builder` collected. A pipe table cell cannot hold a fence
    or a newline, so each `<pre>` in it becomes one code span with its lines joined by `<br>`."""

    def span(match: re.Match[str]) -> str:
        code = pres[int(match.group(1))][1]
        return "`" + code.replace("`", "'").replace("\n", "<br>") + "`"

    text = CELL_MARKS.sub(" ", CELL_PRE.sub(span, raw))
    return re.sub(r"\s+", " ", text).strip().replace("|", "\\|")


def _is_box(rows: list[list[str]]) -> bool:
    """Is this table a layout box rather than data? One column (or one filled cell) whose content has block
    structure - a `<pre>`, or two or more paragraphs/items. Texinfo's `@cartouche` is exactly that: a one-cell table
    around a whole box of prose and examples, and a pipe table cannot hold it. Such a table is emitted as ordinary
    blocks. Everything else, including a single column of plain values with a header, stays a pipe table, where a
    `<pre>` degrades to an inline code span."""
    cells = [cell for row in rows for cell in row if CELL_MARKS.sub("", cell).strip()]
    if max(len(row) for row in rows) != 1 and len(cells) != 1:
        return False
    return any(CELL_PRE.search(cell) or sum(bool(s.strip()) for s in CELL_MARKS.split(cell)) > 1 for cell in cells)


_VERBATIM = re.compile(r"(`[^`]*`|\]\([^)]*\))")


def _escape_asterisks(text: str) -> str:
    """Backslash every literal `*` that is outside a code span or a link target, so `*args, **kwargs` survives
    being wrapped in `**...**`. Deleting the asterisks instead turned `**kwargs` into `kwargs`."""
    parts = _VERBATIM.split(text)
    return "".join(part if index % 2 else part.replace("*", "\\*") for index, part in enumerate(parts))


def _render_table(rows: list[list[str]]) -> str:
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(padded[0]) + " |", "|" + "|".join(" --- " for _ in range(width)) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in padded[1:]]
    return "\n".join(lines)


@dataclass
class _Grid:
    """A `div` grid read as a table: `depth` counts open divs (1 between cells), `cells` is (is_header, text)."""

    columns: int
    depth: int = 1
    header: bool = False
    cells: list[tuple[bool, str]] = field(default_factory=list)


class _LinkCollector(HTMLParser):
    """Second, tiny pass: anchors with their visible text. Kept separate from the block builder so that links
    inside skipped regions (the navbar) are not reported and the builder stays about layout."""

    def __init__(self, base: str, region: str = "", profile: Profile = GENERIC) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.profile = profile
        self.region = _Region(region)
        self.links: list[Link] = []
        self._skip = _Depth()
        self._open: list[str] = []  # open tags, to tell a page footer from an article's own
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        if tag in VOID_TAGS:
            return
        attrs = {key: value or "" for key, value in attrs_list}
        if self._skip:
            self._skip.nest(tag)
            return
        in_container = any(t in {"article", "section"} for t in self._open)
        if is_chrome(tag, attrs, in_container, links=True, extra=self.profile.chrome_classes):
            self._skip.open(tag)
            return
        self.region.start(tag, attrs)
        self._open.append(tag)
        if tag == "a":
            href = dict(attrs_list).get("href") or ""
            self._href = href if href and not href.lower().startswith(("javascript:", "data:", "mailto:")) else None
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if self._skip:
            self._skip.close(tag)
            return
        in_region = self.region.inside
        self.region.end(tag)
        while self._open:
            if self._open.pop() == tag:
                break
        if tag == "a" and self._href is not None:
            if in_region:
                text = re.sub(r"\s+", " ", PRIVATE_USE.sub("", "".join(self._text))).strip()
                path, anchor = resolve_href(self.base, self._href)
                # A link with no text left (a permalink glyph, an icon) points nowhere an agent would follow.
                if text and (path is not None or self._href.lower().startswith(("http:", "https:"))):
                    self.links.append(Link(text, self._href if path is None else "", path, anchor))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._href is not None and not self._skip:
            self._text.append(data)


def _build(html: str, base_path: str, region: str, profile: Profile = GENERIC) -> _Builder:
    builder = _Builder(base_path, region, profile)
    builder.feed(html)
    builder.close()
    builder._close_head()
    builder._flush()
    return builder


def convert(html: str, base_path: str = "", profile: Profile = GENERIC) -> Document:
    """Convert one page. `base_path` is the page's own path, against which links are resolved."""
    builder = None
    for kind in _region_candidates(html):
        attempt = _build(html, base_path, kind, profile)
        # A textual candidate inside a script or comment never opens. A `role=main` that leaves the page's own `<h1>`
        # outside is not the article: Stack Exchange puts the question title in a header above `#mainbar`.
        if attempt.region.entered and (kind == "main" or not attempt.title_outside):
            builder = attempt
            break
    if builder is None:
        builder = _build(html, base_path, "", profile)
    links = _LinkCollector(base_path, builder.region.kind, profile)
    links.feed(html)
    links.close()
    title = builder.title
    if not title:
        title = next((h.text for h in builder.headings if h.level == 1), "")
    return Document(
        title,
        builder.blocks,
        builder.headings,
        links.links,
        builder.dropped_images,
        builder._tight_marks,
        builder.truncated,
        builder.aliases,
    )


_LINK = re.compile(r"\[([^\]]{0,500})\]\([^)]{0,2000}\)")
"""Bounded on both sides. Unbounded `[^]]*` made a run of `[` quadratic: each one scanned to the end of the line
looking for a `]` (40,000 of them took 2.3 s, found in review, D3)."""


def to_plain(markdown: str) -> str:
    """Plain text from the converter's own markdown: heading marks, emphasis, backticks and fences removed,
    links reduced to their text. Applied to the converter's output, not to arbitrary markdown."""
    out: list[str] = []
    in_fence = ""
    for line in markdown.split("\n"):
        stripped = line.lstrip("> ").lstrip()
        if in_fence:
            if stripped.startswith(in_fence):
                in_fence = ""
                continue
            out.append(line)
            continue
        if stripped.startswith("```"):
            in_fence = re.match(r"`+", stripped).group(0)  # type: ignore[union-attr]
            continue
        line = re.sub(r"^(\s*)#{1,6} ", r"\1", line)
        line = _LINK.sub(r"\1", line)
        line = line.replace("**", "").replace("`", "")
        out.append(line)
    return "\n".join(out)
