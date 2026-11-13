"""Each interim copy left at its old path is the core reader, not a second copy that could drift."""

from __future__ import annotations

from primarysource.bbf import _xml as bbf_xml
from primarysource.c2sp import markdown as c2sp_markdown
from primarysource.ecma import _pdf
from primarysource.iana import xmlsafe as iana_xml
from primarysource.ieee import _html
from primarysource.readers import bookmarks, html, markdown, pdf, xml


def test_the_old_modules_hand_out_the_core_objects() -> None:
    assert _pdf.extract is pdf.extract and _pdf.INSTALL_HINT is pdf.INSTALL_HINT
    assert _pdf._cut is bookmarks.cut and _pdf._heading_id is bookmarks.heading_id
    assert _pdf.split_sentences is bookmarks.split_sentences and _pdf.slug is bookmarks.slug
    assert _html.convert is html.convert and _html.Profile is html.Profile and _html.GENERIC is html.GENERIC
    assert c2sp_markdown.parse is markdown.parse and c2sp_markdown.MarkdownDocument is markdown.MarkdownDocument
    assert iana_xml.XmlRefused is xml.XmlRefused


def test_the_wrappers_parse_with_the_core_reader() -> None:
    assert iana_xml.parse(b"<?pi?><r/>", 100).tag == "r"  # iana drops instructions
    assert isinstance(_html.POSIX, html.Profile) and _html.POSIX != html.GENERIC
    root = bbf_xml.parse(b'<?pi?><dm:r xmlns:dm="urn:invented"/>')
    assert root.tag == "r"
