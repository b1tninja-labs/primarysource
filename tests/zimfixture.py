"""A tiny synthetic ZIM built with libzim's own writer, so the suite needs no download.

The content is invented. It imitates the *shape* measured in real DevDocs ZIMs (an application shell with a
navbar element, an inline base64 image, `<section id>` wrappers, `<pre data-language>` code, `<dl>` API
definitions) without copying any upstream documentation.
"""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from primarysource.zim import library

PIXEL = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def shell(body: str, title: str = "Page") -> str:
    return (
        f"<html><head><meta charset='utf-8'><title>{title}</title>"
        "<link rel='stylesheet' href='application.css'><script>var junk = 1;</script></head><body>"
        "<div class='_app'><devdocs-navbar current='x'><a href='nav-only'>NAVLINK</a></devdocs-navbar>"
        f"<div class='_container'><main class='_content'><div class='_page _acme'>{body}</div></main></div></div>"
        "</body></html>"
    )


INSTALL = shell(
    "<h1>Installing Acme Widgets</h1>"
    f"<img alt='logo' src='data:image/png;base64,{PIXEL}'>"
    "<p>Acme Widgets installs with <code>pip install acme</code>. See <a href='config#timeouts'>timeouts</a>, "
    "<a href='../guide/config'>the config page</a>, the <a href='missing/page'>archived elsewhere</a> note and "
    "<a href='https://example.org/acme'>the project</a>.</p>"
    "<section id='requirements'><h2>Requirements<a class='headerlink' href='#requirements'>¶</a></h2>"
    "<ul><li>Python 3.12</li><li>A kettle<ul><li>with a lid</li></ul></li></ul></section>"
    "<section id='quickstart'><h2>Quickstart</h2><p>Run the widget:</p>"
    "<pre data-language='python'>from acme import Widget\n\nwidget = Widget('spin')\nwidget.run()\n</pre>"
    "<table><thead><tr><th>Option</th><th>Default</th></tr></thead>"
    "<tbody><tr><td><code>speed</code></td><td>3 | 4</td></tr><tr><td>mode</td><td>quiet</td></tr></tbody></table>"
    "<blockquote><p>Widgets bite.</p></blockquote></section>",
    "Installing Acme Widgets",
)

PARAS = "".join(f"<p>Paragraph {n} about gaskets and sprockets in the acme widget factory.</p>" for n in range(1, 41))
CONFIG = shell(
    "<h1>Configuration</h1><p>Settings control widgets.</p>"
    "<section id='timeouts'><h2>Timeouts</h2><p>The timeout setting bounds how long a flange may spin.</p>"
    "<pre class='highlight-bash'>acme --timeout 30</pre></section>"
    "<section id='api'><h2>API</h2><dl class='py function'>"
    "<dt id='widget.run'><code>widget.run(speed)</code></dt><dd><p>Run the widget at a speed.</p></dd>"
    "<dt id='widget.stop'><code>widget.stop()</code></dt><dd><p>Stop the widget.</p></dd></dl></section>"
    f"<section id='long'><h2>Long section</h2>{PARAS}</section>"
    "<section id='after'><h2>After</h2><p>Nothing here.</p></section>",
    "Configuration",
)
INDEX = shell("<h1>Acme Widgets</h1><p>Start with the <a href='guide/install'>installation guide</a>.</p>", "Acme")
HUGE_BLOCK = shell("<h1>Dump</h1><pre>" + "line of a very long log\n" * 400 + "</pre><p>After the dump.</p>", "Dump")


def _filler(prefix: str, count: int) -> str:
    return "".join(f"<p>{prefix} filler sentence {n} about nothing in particular.</p>" for n in range(count))


# One huge page, the shape of the single-page DevDocs ZIMs: 8 anchored sections of 30 filler paragraphs each plus
# two API definitions, well over `service.LARGE_ARTICLE_BLOCKS`. Only the "gizmo" sections mention the topics the
# tests search for, so the section a hit names is checkable.
BIG_MANUAL = shell(
    "<h1>Gadget Manual</h1><p>Everything about gadgets lives on this page.</p>"
    + "".join(
        f"<section id='{anchor}'><h2>{heading}</h2><p>{lead}</p>{_filler(anchor, 30)}</section>"
        for anchor, heading, lead in [
            ("overview", "Overview", "A gadget is a thing."),
            ("install", "Install", "Unpack the crate."),
            ("flux-capacitor", "Flux capacitor", "The capacitor must be primed before the gizmo spins."),
            ("calibration", "Calibration", "Calibrate the zorblax regulator monthly."),
            ("storage", "Storage", "Keep gadgets dry."),
        ]
    )
    + "<section id='api'><h2>API</h2><dl>"
    "<dt id='gizmo.spin'><code>gizmo.spin(rate)</code></dt><dd><p>Spin the gizmo at a rate.</p></dd>"
    "<dt id='gizmo.halt'><code>gizmo.halt()</code></dt><dd><p>Halt the quibbleframe gizmo.</p></dd></dl></section>"
    + _filler("tail", 40),
    "Gadget Manual",
)

# A man page in the shape the DevDocs man ZIM has: each section is one preformatted block, and the page ends with
# back-references and a bare URL.
MAN_PAGE = shell(
    "<h1>frobnicate(1) - Linux manual page</h1><h2>NAME</h2><pre>       frobnicate - twist the knob</pre>"
    "<h2>DESCRIPTION</h2><pre>       Frobnicate rotates the knob clockwise until the latch engages.</pre>"
    "<p>Pages that refer to this page: <a href='knob.1'>knob(1)</a>, <a href='latch.2'>latch(2)</a></p><hr>"
    "<p>... <a href='https://example.org/man/frobnicate.1.html'>https://example.org/man/frobnicate.1.html</a></p>",
    "frobnicate (1)",
)


# A web-crawl ZIM stores third-party frames under their own host. The text imitates the shape measured in a real
# ZIM (a notice that a widget could not load), not its wording.
EMBED_FRAME = shell(
    "<p>The invented comment widget could not load. Gaskets and sprockets are discussed elsewhere.</p>"
)


def _translation(lang: str, repeats: int) -> str:
    body = "<p>Gaskets and sprockets: how a gasket meets a sprocket.</p>" * repeats
    return shell(f"<div id='mw-content-text' class='mw-body-content' lang='{lang}'><h1>Gasket</h1>{body}</div>")


# The base page and a German translation that repeats the query words, so the engine ranks the translation first.
GASKET_EN = _translation("en", 1)
GASKET_DE = _translation("de", 6)

# The metadata header the PEPs open with: label blocks, values, a link, then a rule before the body.
PEP_LIKE = shell(
    "<h1>PEP 9999 - Quill feathers</h1><p><strong>Author:</strong></p><p>Ann Example</p>"
    "<p><strong>Discussions-To:</strong></p><p><a href='https://example.org/t/1'>Discourse thread</a></p>"
    "<p><strong>Status:</strong></p><p>Final</p><hr><p>This PEP describes how a quillfeather is trimmed.</p>"
)


def _item_class() -> Any:
    from libzim import writer

    class Item(writer.Item):  # type: ignore[misc]
        def __init__(self, path: str, title: str, mimetype: str, content: str | bytes, front: bool = True) -> None:
            super().__init__()
            self._path, self._title, self._mimetype, self._front = path, title, mimetype, front
            self._content = content if isinstance(content, bytes) else content.encode("utf-8")

        def get_path(self) -> str:
            return self._path

        def get_title(self) -> str:
            return self._title

        def get_mimetype(self) -> str:
            return self._mimetype

        def get_contentprovider(self) -> Any:
            return writer.StringProvider(self._content.decode("utf-8", errors="replace"))

        def get_hints(self) -> dict[Any, Any]:
            return {writer.Hint.FRONT_ARTICLE: self._front}

    return Item  # built lazily: `libzim.writer.Item` can only be subclassed once libzim is imported


def _unseal(function: Any, path: str, _info: Any) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def build_zim(
    directory: Path,
    filename: str = "acme_en_widgets_2026-10.zim",
    *,
    name: str = "acme_en_widgets",
    title: str = "Acme Widgets Docs",
    date: str = "2026-10-01",
    fulltext: bool = True,
    extra: dict[str, str] | None = None,
    license_text: str = "",
    source: str = "",
    tags: str = "devdocs;acme;_ftindex:yes",
) -> Path:
    from libzim import writer

    item = _item_class()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    creator = writer.Creator(str(path)).config_indexing(fulltext, "eng").config_verbose(False)
    creator.set_mainpath("index")
    pages = {"index": INDEX, "guide/install": INSTALL, "guide/config": CONFIG, "dump": HUGE_BLOCK, **(extra or {})}
    with creator:
        creator.add_metadata("Name", name)
        creator.add_metadata("Title", title)
        creator.add_metadata("Description", "Invented documentation for tests")
        creator.add_metadata("Language", "eng")
        creator.add_metadata("Creator", "Acme Docs")
        creator.add_metadata("Publisher", "tests")
        creator.add_metadata("Date", date)
        creator.add_metadata("Tags", tags)
        if license_text:
            creator.add_metadata("License", license_text)
        if source:
            creator.add_metadata("Source", source)
        for page_path, html in pages.items():
            page_title = {"index": "Acme Widgets", "guide/install": "Installing Acme Widgets"}.get(page_path)
            creator.add_item(item(page_path, page_title or page_path.rsplit("/", 1)[-1].title(), "text/html", html))
        creator.add_item(item("application.css", "application.css", "text/css", "body{}", front=False))
        creator.add_item(item("notes.txt", "Plain notes", "text/plain", "first note\n\nsecond note about sprockets"))
        creator.add_item(item("blob.bin", "blob", "application/octet-stream", "xx", front=False))
        creator.add_redirection("old/install", "Old install page", "guide/install", {writer.Hint.FRONT_ARTICLE: True})
    for scratch in directory.glob(f"{filename}*idx*"):
        shutil.rmtree(scratch, onerror=_unseal) if scratch.is_dir() else scratch.unlink(missing_ok=True)
    return path


def build_redirect_loop_zim(directory: Path, filename: str = "loop_en_x_2026-10.zim") -> Path:
    """A ZIM whose redirects `a` -> `b` -> `a` form a loop. libzim's writer refuses loops, so the ZIM is written
    with `a` -> `x` and `b` -> `a` and the target index of `a`'s directory entry is then patched to `b`'s. The
    checksum no longer matches; the reader does not check it on open."""
    import struct

    from libzim import writer
    from libzim.reader import Archive

    item = _item_class()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    creator = writer.Creator(str(path)).config_indexing(True, "eng").config_verbose(False)
    creator.set_mainpath("index")
    page = "<html><body><main><p>zebra {}</p></main></body></html>"
    with creator:
        for key, value in dict(Name="loop_en_x", Title="Loop", Date="2026-10-01", Language="eng").items():
            creator.add_metadata(key, value)
        creator.add_item(item("index", "Index", "text/html", page.format("index")))
        creator.add_item(item("x", "Xarticle zebra", "text/html", page.format("x")))
        creator.add_redirection("a", "A zebra loop", "x", {writer.Hint.FRONT_ARTICLE: True})
        creator.add_redirection("b", "B zebra loop", "a", {writer.Hint.FRONT_ARTICLE: True})
    archive = Archive(str(path))
    index_a = archive.get_entry_by_path("a")._index
    index_b = archive.get_entry_by_path("b")._index
    del archive
    data = bytearray(path.read_bytes())
    url_pointers = struct.unpack_from("<Q", data, 32)[0]
    entry_a = struct.unpack_from("<Q", data, url_pointers + 8 * index_a)[0]
    struct.pack_into("<I", data, entry_a + 8, index_b)
    path.write_bytes(bytes(data))
    for scratch in directory.glob(f"{filename}*idx*"):
        shutil.rmtree(scratch, onerror=_unseal) if scratch.is_dir() else scratch.unlink(missing_ok=True)
    return path


def managed(zim: Path, added_by: str = "get") -> Path:
    """Give `zim` the sidecar a zimlore download would have written (a true size and SHA-256)."""
    from primarysource.zim import manage

    manage.write_sidecar(
        zim,
        manage.Provenance(
            "https://example.org/x.zim",
            "n",
            "d",
            manage.sha256_of(zim),
            zim.stat().st_size,
            "2026-01-01T00:00:00Z",
            added_by,
        ),
    )
    return zim


def age(path: Path, seconds: float = 3600) -> Path:
    """Make `path` look untouched for `seconds`: prune and du leave anything younger than ten minutes alone."""
    then = os.stat(path).st_mtime - seconds
    os.utime(path, (then, then))
    return path


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An empty home (ZIMLORE_HOME). Archive handles are dropped afterwards so Windows can delete the directory."""
    root = tmp_path / "home"
    (root / "zim").mkdir(parents=True)
    monkeypatch.setenv(library.HOME_ENV, str(root))
    for name in (library.PATH_ENV, library.LEGACY_PATH_ENV, "PRIMARYSOURCE_ZIM_HOME", "PRIMARYSOURCE_HOME"):
        monkeypatch.delenv(name, raising=False)
    library.close_all()
    yield root
    library.close_all()


@pytest.fixture
def acme(home: Path) -> Path:
    """ZIMLORE_HOME holding one synthetic library."""
    from primarysource.zim import service

    service.forget()
    build_zim(home / "zim")
    return home
