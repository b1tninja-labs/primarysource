"""Shared plumbing for the packaging and tooling specification collections: `gitdocs`, `debpolicy`, `rpmdocs`,
`pms`, `pep` and `kconfig`.

Every one of them is published as text in a git repository (AsciiDoc, reStructuredText, Markdown, scdoc, POD,
LaTeX). They share one shape, so the shape lives here once and each collection directory holds only what is its
own: the pinned trees, the licence, the choice of files, the document ids and the ref spelling.

- `readers/`: minimal, bounded readers, one per format, bytes in and a `Doc` out. Nothing here opens a path a
  document names, runs a command or imports anything outside the standard library. These are the proposed core
  readers (ROADMAP rows `cl.reader_markdown`, `cl.reader_rst`, ...); they are private to this package until two
  collections outside it need one.
- `fetch.py`: a pinned archive streamed, never extracted to disk (the proposed `cl.fetch_git_tree_pinned`).
- `store.py`, `index.py`: an installed edition under `$PRIMARYSOURCE_HOME/<collection>/<tree>/<commit>/`, and its
  FTS5 index.
- `runtime.py`, `serving.py`, `cli.py`: read, outline, search, cite and docs, and the MCP tools and command line
  that expose them under each collection's prefix.

No document text is kept in this repository: tests use invented text.
"""
