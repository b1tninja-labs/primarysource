# pkgdocs: the shared plumbing under six collections

`gitdocs`, `debpolicy`, `rpmdocs`, `pms`, `pep` and `kconfig` are the same thing six times: a pinned git tree of
text, a licence, a reader, refs. `primarysource/pkgdocs/` holds the shape once; each collection directory holds a
`catalogue.py` (the pin, the licence, the file selection, the document ids, a `build`) and three four-line files
(`__init__.py`, `server.py`, `cli.py`). It is private staging for what the core should own; see section 3.

| Module | What it does |
|---|---|
| `fetch.py` | A pinned archive streamed with `tarfile` mode `r|`, never extracted: bounded, one request per second, redirect only to listed hosts, mirrors, and a **manifest digest of the selected files** as the pin |
| `store.py`, `index.py` | An installed edition under `$PRIMARYSOURCE_HOME/<collection>/<tree>/<commit>/` (parsed documents, a catalogue, `edition.json`) and its FTS5 index (BM25, title over body, sanitised terms, strict AND then a relaxed OR that says so, read-only open) |
| `runtime.py` | `Spec`, `TreeSpec`, `Pin`, `Licence`; `Library`: import, docs, outline, read, search, cite, status; ref parsing and section resolution |
| `serving.py` | The MCP server (`<name>_read`, `_outline`, `_search`, `_cite`, `_docs`, `_status`) and the command line, from a `Spec` |
| `readers/` | `asciidoc`, `rst`, `markdown`, `pod`, `scdoc`, `latex`: bytes in, a `Doc` out, no I/O, no recursion, a size-linear worst case |

## 1. Decisions

- **The pin is the selected files, not the archive.** gitiles archives differ from one request to the next (it stamps
  the request time into every header; two fetches of the same commit measured 7,508,480 and 7,514,624 bytes), and a
  forge tarball, a `git archive` and a subtree archive of one commit are different bytes. The manifest digest
  (`sha256` over sorted `<sha256 of file>  <path>` lines of the files the collection selects) is the same from all of
  them: the gitdocs digest from the gitiles subtree archive equals the one from the 54 MB GitHub tarball. A
  digest mismatch is `Refused` and does not fall through to a mirror.
- **A truncated tar is an error.** `tarfile` treats a header cut short as the end of the archive, so a half archive
  would quietly lose files. The fetch checks the tar end marker itself.
- **Section ids are ordinal paths, anchors are labels or slugs, a ref's section may be either, a heading, or a
  unique part of one.** Policy chapters take their number from the toctree, so `debpolicy:5.6.1` works.
- **The unit is a block** everywhere (`Unit.BLOCK`); `¶n` counts the blocks of one section. Each collection's doc
  says what a block is for its format.
- **Licences are read from the source and recorded per collection, and per document where the source says so**
  (Debian's DEP-5 `debian/copyright`, PEPs' Copyright sections, SPDX tags, dpkg's pod headers).

## 2. Interfaces taken from sibling projects, as rows

Neither is imported; the rows name what this code would take.

- **`archivekit` (D:\code\archivekit, being built):** the bounded tar-and-gzip stream reader and its safe-name rules
  in place of `fetch._Counting`, `_Prefixed` and `_safe_name`; and its zip equivalent when a source ships zips.
- **`gitobj` (D:\code\gitobj):** `tree_sha1` over the `Documentation/` files (mode and bytes) so a pin can also name
  the commit's tree object and the files read are checked against `git rev-parse <commit>:Documentation`, independent
  of the server, the compression and the include filter.

## 3. Proposed core readers and modules

Where two collections share a format, the reader belongs in the core. Today:

| Core row | Used by | Here |
|---|---|---|
| `cl.reader_rst` | `pep`, `debpolicy`, `kconfig` | `readers/rst.py` |
| `cl.reader_markdown` | `rpmdocs`, `debpolicy` | `readers/markdown.py` |
| `cl.reader_asciidoc_scdoc` | `gitdocs` (AsciiDoc), `rpmdocs` (scdoc) | `readers/asciidoc.py`, `readers/scdoc.py` |
| `cl.reader_pod` | `debpolicy` | `readers/pod.py` (one consumer so far; stays here until a second) |
| `cl.reader_latex` | `pms` | `readers/latex.py` (one consumer; stays here) |
| `cl.model_anchor` | all six | `pkgdocs/model.py::Sec.anchor`; becomes `Section.anchor` |
| `cl.collection_manifest` | all six | `runtime.Licence` and `runtime.Pin`: licence id, placement, evidence, pin, mirrors |
| `cl.fetch_git_tree_pinned` | all six | `fetch.py` |
| `cl.index_fts5` | all six | `index.py`, with the rules the row already names |
| `cl.cite_generic` | all six | `Library._citation`: ref, title, section, edition, source path, licence and credit |

`cl.reader_roff` has no consumer among these six: dpkg's pages are POD in the source tree, rpm's are scdoc.
