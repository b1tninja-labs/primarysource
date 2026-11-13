"""The core readers (PLAN.md §4). Each takes bytes or text and never unpacks an archive to disk.

- `html`: HTML to readable markdown blocks, zimlore's converter plus a `Profile` (`cl.reader_html`).
- `markdown`: a strict Markdown subset into headings and blocks (`cl.reader_markdown`).
- `pdf`: a bookmarked PDF into sections of sentences, `pypdf` imported only when a PDF is read
  (`cl.reader_pdf_pypdf`); `bookmarks` cuts the page texts at the bookmarks (`cl.segment_bookmarks`).
- `xml`: the one hardened XML parser: no DTDs, no entities, no network (`cl.reader_xml_hardened`).

Standard library only, apart from `pypdf`, which is an ingest-time extra (PLAN.md §5.13).
"""
