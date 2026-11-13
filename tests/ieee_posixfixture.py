"""Invented pages shaped like The Open Group's POSIX HTML, and a tarball of them shaped like `susv5.tgz`.

The markup imitates what was measured in the 2024 archive (a `div.NAVHEADER` table at top and bottom, a
`<center><font size="2">` banner and trademark footer, `<a name id>` anchors inside `<h4 class="mansect">`,
section bodies in `<blockquote>`, a `<center>` around a data table, a `span.topOfPage` link). Every word of text
is invented; none is copied from the standard.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from dataclasses import replace
from pathlib import Path

from primarysource.ieee.catalogue import POSIX_2024, Edition

NAV = (
    '<div class="NAVHEADER"><table summary="nav" class="nav"><tr class="nav">'
    '<td class="nav"><a href="../functions/frab.html" accesskey="P">&lt;&lt;&lt; Previous</a></td>'
    '<td class="nav"><a href="contents.html">Home</a></td>'
    '<td class="nav"><a href="../functions/frub.html" accesskey="N">Next &gt;&gt;&gt;</a></td>'
    '</tr></table><hr align="left"></div>'
)


def page(title: str, name: str, tag: str, body: str) -> str:
    """One page: chrome around `body`, which holds the headings and their sections."""
    return (
        "<!-- invented notice -->\n<!DOCTYPE HTML>\n<html lang='en'><head>"
        '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
        f"<title>{title}</title></head><body bgcolor='white'>{NAV}"
        '<script language="JavaScript" src="../jscript/codes.js"></script><basefont size="3">'
        '<center><font size="2">Invented Banner Issue 0<br>Invented Std 0-0000<br>Invented notice</font></center>'
        '<hr size="2" noshade>'
        f'<a name="top" id="top"></a> <a name="{name}" id="{name}"></a> <a name="{tag}" id="{tag}"></a>'
        f"{body}"
        '<hr><p>&nbsp;</p><a href="#top"><span class="topOfPage">return to top of page</span></a><br>'
        '<hr size="2" noshade><center><font size="2">Invented trademark line<br>'
        '[ <a href="../mindex.html">Main Index</a> ]</font></center>'
        f"{NAV}</body></html>"
    )


def mansect(tag: str, title: str, body: str, level: int = 4) -> str:
    klass = ' class="mansect"' if level == 4 else ""
    return f'<h{level}{klass}><a name="{tag}" id="{tag}"></a>{title}</h{level}>{body}'


FROB = page(
    "frob",
    "frob",
    "tag_99_01",
    mansect("tag_99_01_01", "NAME", "<blockquote><p>frob - twiddle a sprocket</p></blockquote>")
    + mansect(
        "tag_99_01_02",
        "DESCRIPTION",
        "<blockquote><p>The <i>frob</i>() function shall twiddle the sprocket named by <i>s</i>.</p>"
        "<p>A second paragraph about gaskets.</p>"
        '<center><table border="1"><tr><th>Flag</th><th>Meaning</th></tr>'
        "<tr><td>F_ONE</td><td>one gasket</td></tr></table></center></blockquote>",
    )
    + mansect("tag_99_01_02_01", "Twiddling in Detail", "<p>Sub-section text about flanges.</p>", level=5)
    + mansect("tag_99_01_03", "RETURN VALUE", "<blockquote><p>Upon success, zero sprockets.</p></blockquote>"),
)

CHAPTER = page(
    "Invented Definitions",
    "chap",
    "tag_98_00",
    '<h2><a name="tag_98" id="tag_98"></a>9. Invented Definitions</h2><p>For the purposes of this chapter.</p>'
    + "".join(
        f'<h3><a name="tag_98_{n:02d}" id="tag_98_{n:02d}"></a>9.{n} Term {n}</h3><p>Gasket term {n}.</p>'
        for n in range(1, 4)
    ),
)

PAGES = {
    "susv5-html/functions/frob.html": FROB,
    "susv5-html/basedefs/V9_chap09.html": CHAPTER,
    "susv5-html/utilities/[.html": page("[", "x", "tag_97", mansect("tag_97_01", "NAME", "<p>bracket test</p>")),
}


def tarball(members: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    """A gzip tar holding `members` (and a symlink member, when named), built in memory."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if symlink is not None:
            info = tarfile.TarInfo(symlink)
            info.type = tarfile.SYMTYPE
            info.linkname = "../style.css"
            tar.addfile(info)
    return buffer.getvalue()


def archive(tmp: Path, members: dict[str, bytes] | None = None, **kwargs: str) -> tuple[Path, Edition]:
    """Write a synthetic archive and an edition pinned to its digest (the real pin cannot match invented text)."""
    if members is None:
        members = {name: html.encode("utf-8") for name, html in PAGES.items()}
        members["susv5-html/style.css"] = b"body {}"
        members["susv5-html/images/logo.gif"] = b"GIF89a"
    data = tarball(members, **kwargs)
    path = tmp / "susv5.tgz"
    path.write_bytes(data)
    pinned = replace(POSIX_2024, sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    return path, pinned
