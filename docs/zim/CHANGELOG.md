# Changelog

## 0.1.0 (unreleased)

First version. Nothing has been published or pushed.

- **Library.** ZIM files are read from `$ZIMLORE_HOME/zim` (default `~/.zimlore`) or `ZIMLORE_ZIM_PATH`. A library
  is a ZIM's `Name`; its version is the ZIM `Date`. Names and aliases (DevDocs slug, title, Stack Exchange host,
  `aliases.json`) are ranked; ties are listed, not guessed.
- **Reading.** HTML to markdown with the standard library only: code blocks with language, tables, headings,
  lists, definition lists kept; navigation chrome and inline base64 images dropped. Reads address an article, a
  `#anchor` section or API definition, or a `¶n` block, and page by token budget with `next` cursors.
- **Search.** Title suggestions plus full-text, with a per-word fallback when no page contains every word.
  34-question eval over DevDocs Flask and Python: hit@1 10/34, hit@5 23/34, MRR 0.436.
- **Real-ZIM defects.** Pager cards (`rel=next|prev` around block content) dropped from text; Disqus and OAuth
  frames not listed or returned as articles; `zim_search` takes `language` (translations ranked after originals by
  default); PEP-style metadata headers skipped in excerpts.
- **Versions and purls.** A library has a derived `family` and `version` (from the ZIM's `purl:` tag, else the
  Name's trailing version token). `cobra` resolves to the newest installed version by a real version order and
  `other_versions` lists the rest; `cobra v1.8.1`, `flask 3.1`, `cryptography==50.0.2`, `cryptography@50` and
  `pkg:pypi/flask@3.1.0` select a version (`exact` or `prefix`), and one that is not installed is an error listing
  those that are. A purl is accepted wherever a library name is. Fixes `cobra` resolving to v1.8.1 over v1.10.2
  (alias length decided it and the ambiguity guard never fired). `prune` still counts only editions of one Name;
  `list` collapses a package's versions (`--all-versions` undoes it); `remove` of a package with several versions
  needs a version or `--all-versions`.
- **Catalogue.** `zimlore catalog`, `get` (SHA-256 verified against the `.meta4`), `outdated`.
- **MCP.** Eight tools (`zim_libraries`, `zim_resolve`, `zim_search`, `zim_read`, `zim_outline`, `zim_links`,
  `zim_cite`, `zim_available`) and one prompt, behind `zimlore[mcp]`.
- **Managing the library.** Every download writes a provenance sidecar; `verify`, `remove`, `prune` and `du` work
  on what is installed (deleting commands are dry runs unless `--yes`). Design for the rest: `docs/library-management.md`.
- **Offline catalogue.** `zimlore catalog --refresh` stores the English catalogue as `catalog.json`; `zimlore available`,
  `catalog --offline` and the `zim_available` MCP tool search it with no network, and a missing-library miss carries
  `obtainable` from it. The MCP server still never touches the network.
- **MCP usability.** From a model using the real server with only its descriptions: a search with no full-text match
  says `confidence: low` and lists `obtainable`; errors name MCP tools (`tool_hint`) and say what only the user can do
  (`user_action`), the CLI keeps its commands; `#anchor¶n` counts inside the section; hits on pages over 60 blocks
  (was 200) carry a `section`, and every hit a `blocks` count; a cut read reports `remaining_tokens`, an outline its
  `total`; a bad anchor gets `did_you_mean`; `max_tokens` is capped at 8000; the instructions open with a decision tree.
- **Adding and syncing.** `zimlore add PATH [--link]` installs a local ZIM (libzim opens it and its checksum holds
  or it is refused; copy by default; never overwrites; sidecar `added_by: add`). `zimlore sync` plans against a
  TOML manifest and/or `--group` names (`libraries`, `groups`, `max_age_days`, `budget`; catalogue names only),
  `--dry-run` downloads nothing, `--update` stages newer editions beside the old one, extras are reported and
  never removed. Downloads resume from a `.part` with an HTTP Range request (the whole file is re-hashed), take
  their size cap from the `.meta4`, and hold a `.part.lock` so two runs cannot share a `.part`. The groups in
  `zimlore/groups.py` are an editorial default pending the maintainer's decision.
- **Review fixes (behaviour changes).** `prune` orders editions by parsed date, treats copies of one uuid as one
  edition, refuses a library with an unparseable or tied date or a kept edition that fails verification, deletes only
  files with a get/sync/add sidecar unless `--include-unmanaged`, sweeps only stale `*.zim.part` regular files, and
  `remove`/`prune` report `deleted` and `failed` (exit 1 on any failure). `zimlore get` refuses to replace an existing
  file unless `--replace` (identical content is a no-op). `verify --adopt` no longer invents catalogue or fetch fields.
  Downloads re-check every redirect hop, pin the `.meta4` to kiwix.org, have a deadline and a free-space check, and
  turn truncated bodies and malformed numbers into `ZimloreError`.
- **Page chrome and content region (converter).** A stray close tag inside a skipped element no longer ends the skip
  (the skip follows the element's own tag name; Starlette's TOC template leaked its menu); with no `<main>` the content
  is the element with `role="main"`, `id="main-content"` or the page's single `<article>` (not when its `<h1>` lies
  outside, as on Stack Exchange; a marker that never opens falls back to the whole body); class-named chrome
  (toolbar, breadcrumb, pagination, TOC, a compound `*-sidebar`) and page-level `<footer>` are dropped, while a bare
  `sidebar` stays content; Texinfo `#Node` ids on wrapper divs now resolve to the heading, and its `nav-panel` /
  `mini-toc` are dropped; Doxygen member titles lose the diamond and become definitions, `div.fragment` listings
  are code fences and hover tooltips are gone.
- **Catalogue filters.** `zimlore catalog --tag devdocs --max-mb 1` passes the catalogue's own `tag` and `maxsize`
  filters (bytes; checked against the live feed), so the searchable Kiwix catalogue can be browsed by kind and size.
- **Release readiness** (advice from the rfclib release setup). The dev tools are a PEP 735 dependency group (`pip install -e . --group dev`), so `zimlore[dev]` is no longer published; twine 6.1+ for Metadata 2.4; the release job runs the whole suite against the *installed wheel* as well as the sdist, and both pass (287 tests); the sdist now ships `PLAN.md` and `ROADMAP.md` because tests read them; the deployment links to the project on PyPI. No test touches the network (checked by running the suite with every non-loopback connection refused).
- **Tool results sized for a model.** Found by auditing the live MCP server: compact JSON; `zim_libraries` is lean (about 40 tokens a library), bounded (`limit`, `total`, `truncated`) with `verbose` for detail; `zim_outline` takes `max_tokens`; search hits drop the per-hit `cite` and `edition` (one `editions` map; `zim_cite` builds citations) and show a `section` only when it covers two or more query words; constants and empty lists are omitted. `zim_libraries` 884 to 333 tokens for 6 libraries, search 1,076 to 572, an outline page 4,006 to 1,551.
- **Found by looking up `x509` in the cryptography docs** (a ZIM built from its sdist in the Docker sandbox): the Sphinx `genindex` page ranked first (the packager now drops it); a one-word query attached an arbitrary section (a single-word query now needs the word in the heading or in at most 3 blocks of the page); outline rows repeated the library and path on every row (now `{text, level|kind, anchor}` under one page `ref`); `zim_cite` still carried a constant; the server instructions now say how to follow a link inside page text.
- **Converter structure fixes from the eight generator prototypes** (`docs/prototypes/*/DEFECTS.md`; tests in `tests/test_converter_structure.py`, each mutation-verified): `<br>` and per-line wrappers (`span.line`, one `<code>` per line) inside `<pre>` are newlines, so TypeDoc, Dokka and javadoc 8 snippets keep their lines; HTML's implied end tags for table rows and cells (a javadoc table without `</td>`/`</tr>` kept its body); a one-column table whose cell holds block content (a Texinfo `@cartouche`) is emitted as blocks, a `<pre>` in a data table stays an inline code span; javadoc 17+ `div.summary-table` grids become pipe tables; fences carry their language from `<pre>`, `<code>`, wrapper `div`s (Sphinx, Material, pandoc, highlight.js, Rouge); `<details id>` is an anchor named by its `<summary>`; `<dt><a>` item lists keep their links; sphinx-tabs labels lead their panels; admonition kinds lead their paragraph (`**Note:** ...`); the rustdoc `§` glyph and `Expand description` are dropped; literal `*args, **kwargs` in a definition is escaped instead of deleted.
- **Verification.** 81 tests, none needing a ZIM; ruff and mypy strict clean; passed on CPython 3.12 and 3.14
  (Windows), the 3.12 run also under `python -O`; wheel and sdist built, `twine check --strict` passed, and the
  sdist's suite passed from a clean extraction (3.12, with the `mcp` extra). Linux, macOS and 3.13 not run.
