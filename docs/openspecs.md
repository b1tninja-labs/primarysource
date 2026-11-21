# `openspecs`: Microsoft Open Specifications

```
primarysource openspecs fetch                         # the Learn table-of-contents tree, no page HTML
primarysource openspecs sync                          # download every catalogued page and index it
primarysource openspecs sync --only MS-SMB2           # one specification
primarysource openspecs index                         # rebuild the index from pages already stored
primarysource openspecs read "openspecs:MS-SMB2§2.2.1¶2"
primarysource mcp --collection openspecs              # openspecs_read, openspecs_search, openspecs_outline,
                                                      # openspecs_cite, openspecs_docs
```

The repository holds no Open Specifications text. The catalog, the page text and the index live under
`$PRIMARYSOURCE_HOME/openspecs/`.

## 1. Source

Microsoft publishes the library as HTML on Microsoft Learn, not as one archive. The crawl starts at
<https://learn.microsoft.com/en-us/openspecs/toc.json>. Each family directory and each specification directory
has its own `toc.json`. A specification page is an entry in that specification's table. A guessed `toc.json`
that returns HTTP 404 is recorded in `catalog.json` as missing and is not an error. The root table being
missing is an error.

There is no current `[MS-CAB]` body in that tree. Cabinet structure is the 1997 cabinet chapter. `[MS-MCI]` is
MSZIP. `[MS-PATCH]` is LZX DELTA, a derivative of Cabinet LZX, not the 1997 Cabinet LZX bitstream. The crawl
indexes the pages Learn actually publishes, including `[MS-MCI]` and `[MS-PATCH]`, and does not invent a page
for the 1997 chapter.

The on-disk registry hive is not an `[MS-*]` page in that tree either. `fetch` records the archived Technet
article <https://learn.microsoft.com/en-us/previous-versions/cc750583(v=technet.10)> as `TN-CC750583`. `sync`
downloads that one page and stores one section per chapter heading.

## 2. What is stored

`fetch` writes `catalog.json`: document id, section id, title, URL, depth. `sync` writes `pages/<DOC>/<section>.json`
(the converted blocks and the sha256 of the HTML) and `sections.sqlite` (the FTS5 index). A page whose stored
URL still matches the catalog is not downloaded again.

The documents are free to view and download. Many of them describe patented technology, some of it under the
Open Specifications Promise or the Microsoft Community Promise and some of it under a separate licence. This
package does not redistribute the text. The copy is the user's, on the collection's own volume.

Fetched 2026-11-17: 1,058 documents, 184,698 pages, 1,082 tables of contents. Eight guessed tables returned
HTTP 404, all of them overview directories whose children were already listed by the parent table
(`MS-COMPLANLP`, `MS-STDSUPLP`, `MS-DATAPORTLP`, `ms-openspeclp`, `ms-protocolslp`, and the lowercase twins of
the three family directories). There is no `[MS-CAB]` page in the catalog. `[MS-MCI]`, `[MS-PATCH]` and
`[MS-XCA]` are.

## 3. Refs

`openspecs:MS-SMB2§2.2.1¶2`. The prefix is optional. The document id is case-insensitive. `§` is the section
number from the table-of-contents title, or a slug when the title does not start with a number. `¶n` counts
blocks on that Learn page.
