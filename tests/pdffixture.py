"""Build a small bookmarked PDF with invented text, for the bbf and ecma tests. Needs pypdf (the test importskips)."""

from __future__ import annotations

import io

PAGE_FURNITURE = ("INVENTED STANDARD 9999", "Draft for tests only")


def make_pdf(pages: list[list[str]], outline: list[tuple[str, int, int]], title: str = "Invented standard") -> bytes:
    """`pages` is the text lines of each page; `outline` is (bookmark title, 0-based page, depth), depth 0 first.
    Every page gets a header line and a `Page n of N` footer, so the furniture filter has something to drop."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    total = len(pages)
    for number, lines in enumerate(pages, start=1):
        page = writer.add_blank_page(612, 792)
        everything = [PAGE_FURNITURE[0], *lines, f"Page {number} of {total}"]
        ops = ["BT /F1 11 Tf"]
        y = 740.0
        for line in everything:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"1 0 0 1 72 {y:.0f} Tm ({escaped}) Tj")
            y -= 18
        ops.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(ops).encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
    parents: list[object] = []
    for heading, page_index, depth in outline:
        parent = parents[depth - 1] if depth > 0 else None
        item = writer.add_outline_item(heading, page_index, parent=parent)  # type: ignore[arg-type]
        del parents[depth:]
        parents.append(item)
    writer.add_metadata({"/Title": title})
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def standard() -> tuple[bytes, list[str]]:
    """A five-page invented standard: clauses 1, 2 (with 2.1 and 2.2), 3, Annex A and a Bibliography.
    Returns the PDF and the section ids the reader should find, in order."""
    filler = "This sentence is padding for the furniture filter."
    pages = [
        ["1 Scope", "The widget protocol defines gaskets. It applies to sprockets. " + filler],
        ["2 Terms", "A gasket is a seal. A sprocket is a toothed wheel.", "2.1 Gasket", "A gasket MUST be round."],
        [
            "2.2 Sprocket",
            "A sprocket SHOULD have teeth. The tooth count is even.",
            "3 Conformance",
            "An implementation conforms if it works.",
        ],
        ["Annex A (normative) Registry", "The registry lists flanges. Flanges are optional."],
        ["Bibliography", "RFC 9999 is invented. So is everything here."],
    ]
    outline = [
        ("1 Scope", 0, 0),
        ("2 Terms", 1, 0),
        ("2.1 Gasket", 1, 1),
        ("2.2 Sprocket", 2, 1),
        ("3 Conformance", 2, 0),
        ("Annex A (normative) Registry", 3, 0),
        ("Bibliography", 4, 0),
    ]
    return make_pdf(pages, outline), ["1", "2", "2.1", "2.2", "3", "A", "bibliography"]
