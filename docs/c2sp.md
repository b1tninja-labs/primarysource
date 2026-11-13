# `c2sp`: the Community Cryptography Specification Project

```
pip install "primarysource[c2sp]"                 # the standard library only; add ,mcp to serve it
primarysource c2sp import                         # 31 specifications, one request per second
primarysource c2sp read "static-ct-api@09f3e51§Log Entries"
primarysource mcp --collection c2sp               # tools c2sp_read, c2sp_search, c2sp_outline, c2sp_cite, c2sp_docs
```

The repository holds **no C2SP text**: the code, `catalogue.json` (names, titles, sizes, sha256) and invented
test documents. Text lives under `$PRIMARYSOURCE_HOME/c2sp/<commit>/`.

## 1. Source, licence, placement

- **Source:** the top-level `*.md` files of <https://github.com/C2SP/C2SP>, the editor's copies of the
  specifications (`static-ct-api`, `tlog-tiles`, `tlog-checkpoint`, `tlog-cosignature`, `tlog-witness`,
  `signed-note`, `age`, `BLAKE3`, and 23 more: `primarysource c2sp docs` lists them).
- **Pin:** commit `09f3e519fe79bcbdccadcf821182e3b488a14d71` (11 November 2026), the commit ctspy pins. Every file
  is fetched from `raw.githubusercontent.com/C2SP/C2SP/<commit>/<name>.md` and kept only if its sha256 equals the
  catalogue's. 31 files, 716,703 bytes.
- **Licence:** "All C2SP specifications are licensed CC BY 4.0. All code and data in this repository is licensed
  under the BSD 1-Clause License", from the repository's `.github/README.md` at the pinned commit (read
  2026-11-12; the repository has no top-level LICENSE file and GitHub reports none). Attribution is required: every
  `cite:` line carries "CC BY 4.0" and the commit URL.
- **Placement: image layer allowed** (CC BY 4.0 permits redistribution with attribution). The importer only writes
  to the home directory; baking the files into an image is a build step that must keep the attribution.
  Subdirectories (test vectors, `jq255/`, ...) are not part of the collection.
- **Why a commit and not a tag:** C2SP versions each specification with semver tags (`static-ct-api/v1.0.0`) but
  the consumers pin a commit. A tag-per-spec catalogue is a roadmap row.

## 2. Refs

```
c2sp:static-ct-api@09f3e51§Log Entries¶2
```

- `c2sp:` prefix: optional.
- `static-ct-api`: the file name without `.md`, case as in the repository (`BLAKE3`, `XAES-256-GCM`).
- `@09f3e51`: a commit prefix (7 to 40 lowercase hex digits). Without it, the newest import. An import of another
  commit lives beside this one and is addressed by its prefix.
- `§Log Entries`: a heading, by its exact text, else by its GitHub-style slug (`log-entries`), else ignoring case.
  A title containing `:`, `#`, `¶` or `§` cannot appear in a ref, so the outline offers the slug instead
  (`§entry-format-details`). When two headings read alike the first wins and a `warning:` line says so; the second
  is `log-entries-1`.
- `¶n`: the nth **block** of the section's span. A block is a blank-line-separated chunk (a paragraph, a list, a
  quotation) or one whole fenced code block. The span runs from the heading to the next heading of the same or a
  higher level: subsections are inside it, each subsection heading is a block (`### Title`), the section's own
  heading is not. No `§`: the whole document.

`¶n` indexes are stable only for one commit; the `span:` hash in each result is of the exact text cited, so a
later extraction can be checked against it.

## 3. Tools and commands

| Tool | What it does |
|---|---|
| `c2sp_read(ref, start, max_tokens)` | the text of a ref, cut at block boundaries; `next: start=N` continues |
| `c2sp_search(query, doc, limit, start)` | blocks containing every word (else at least half, flagged `relaxed:`); `<ref>¶n: <snippet>` |
| `c2sp_outline(doc)` | headings, indented, each with its ref and block count |
| `c2sp_cite(ref)` | `cite:`, `unit: block` and `span:` lines |
| `c2sp_docs()` | the catalogue and what is imported |

`primarysource c2sp import | docs | outline | read | search | cite` are the same operations. Results are text with the
fixed footer (`cite`, `unit`, `span`, `next`, `relaxed`, `warning`). Search is a plain scan with term-frequency
scoring (no index yet: the core's `cl.index_fts5` is not built); it is fast enough for 2,829 top-level blocks.

## 4. The reader and what it distrusts

`markdown.py` reads ATX and one-line setext headings, fenced code, front matter and blank-line blocks, and nothing
else: HTML, links and images are text, never followed. The importer refuses, before writing, a pinned file that is
not UTF-8, contains a NUL, is over 4 MiB, has a line over 20,000 characters or more than 20,000 headings. The
fetcher takes only `https://raw.githubusercontent.com/...`, no credentials or ports, follows a redirect only to the
same allow-list, and refuses a body larger than twice the pinned size. A file on disk that no longer matches its
recorded sha256 is refused when read.

## 5. Real import (2026-11-13)

31 specifications at `09f3e51`: 453 headings, 2,829 top-level blocks, 31 requests in about 30 s. The brief's
example resolves: `static-ct-api@09f3e51§Log Entries` reads the heading the repository spells "Log entries",
case-insensitively.

## 6. Open

See the roadmap rows `c2sp.*` in the coordinator's report: tag-per-spec pins, the core FTS5 index, an
`https://c2sp.org/<spec>@<version>` URL in `cite:` once a tag is pinned, and `Section.anchor` from the core model.
