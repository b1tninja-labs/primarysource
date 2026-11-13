"""Invented HTML pages for the converter tests, copied from zimlore `tests/zimfixture.py` (commit 1903b46).

The content is invented. It imitates the *shape* of real DevDocs pages (an application shell with a navbar
element, an inline base64 image, `<section id>` wrappers, `<pre data-language>` code, `<dl>` API definitions)
without copying any upstream documentation. The ZIM-building half of zimlore's fixture is not copied.
"""

from __future__ import annotations

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


def _filler(prefix: str, count: int) -> str:
    return "".join(f"<p>{prefix} filler sentence {n} about nothing in particular.</p>" for n in range(count))


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

MAN_PAGE = shell(
    "<h1>frobnicate(1) - Linux manual page</h1><h2>NAME</h2><pre>       frobnicate - twist the knob</pre>"
    "<h2>DESCRIPTION</h2><pre>       Frobnicate rotates the knob clockwise until the latch engages.</pre>"
    "<p>Pages that refer to this page: <a href='knob.1'>knob(1)</a>, <a href='latch.2'>latch(2)</a></p><hr>"
    "<p>... <a href='https://example.org/man/frobnicate.1.html'>https://example.org/man/frobnicate.1.html</a></p>",
    "frobnicate (1)",
)
