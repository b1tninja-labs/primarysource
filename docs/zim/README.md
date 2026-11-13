> **Moved into primarysource (2026-11-13).** This is zimlore's README as of `1903b46`, kept for its design
> content. In this repository the package is `primarysource.zim`; install it with
> `pip install "primarysource[zim,mcp]"`; `zimlore <command>` is `primarysource zim <command>`;
> `ZIMLORE_HOME`, `ZIMLORE_ZIM_PATH` and `ZIMLORE_MAX_ENTRY_BYTES` still work, beside `PRIMARYSOURCE_ZIM_HOME`,
> `PRIMARYSOURCE_ZIM_PATH` and `PRIMARYSOURCE_ZIM_MAX_ENTRY_BYTES`. The tools return text with a footer (`cite:`,
> `next:`, ...) rather than the JSON objects described below, and a read's `next:` is a ref, not `{"ref", "start"}`
> (ROADMAP.md section 3a and `cl.adopt_zimlore`).

# zimlore

A [Kiwix](https://kiwix.org) library (ZIM files) served to AI agents over MCP: **offline, citable,
token-budgeted documentation**. It is the offline counterpart of [Context7](https://github.com/upstash/context7):
instead of asking a hosted service for snippets, an agent searches and reads ZIM files you hold on disk, and
every answer carries the ZIM's name, edition date and entry path.

You supply the ZIMs. **None are shipped**, and `.gitignore` names every way one could be staged
(see [NOTICE](NOTICE)).

```
pip install "zimlore[mcp]"
zimlore catalog flask              # search the public Kiwix catalogue
zimlore get devdocs_en_flask       # download it, verified by SHA-256, into ~/.zimlore/zim
zimlore search "application factory" -l flask
zimlore read flask§patterns/appfactories/index
zimlore mcp                        # the MCP server, on stdio
```

Managing what is installed (none of these touch the network):

```
zimlore du                         # disk use per library
zimlore verify [--adopt]           # check files against their provenance record and libzim's checksum
zimlore remove flask --yes         # delete (dry run without --yes; --edition DATE or --all when several)
zimlore prune --keep 2 --yes       # drop old zimlore-installed editions and stale partial downloads
                                   # (--include-unmanaged also deletes files zimlore did not install)
```

Putting ZIMs in place (`add` is local; `sync` and `get` use the network and resume an interrupted download):

```
zimlore add some.zim [--link]      # copy (or link) a local ZIM in after libzim opens it and its checksum holds
zimlore sync --group web-testing --dry-run   # plan against a manifest or a named group; sizes are approximate
zimlore sync --manifest .zimlore.toml [--update]   # install what is missing; --update stages newer editions
```

A manifest (`./.zimlore.toml`, else `$ZIMLORE_HOME/libraries.toml`) names catalogue entries only, never URLs or
paths, so it can be committed: `libraries = ["devdocs_en_python"]`, `groups = ["infra"]`, `max_age_days = 365`,
`budget = "2GB"` (the library may not grow past it). `sync` never removes anything. The shipped groups
(`languages-core`, `web-testing`, `infra`) are an editorial default awaiting the maintainer's decision.

Every download records a sidecar (`<file>.zimlore.json`: source URL, verified SHA-256, time). A file without one
reports `provenance: unrecorded` in `zim_libraries`, `zim_resolve` and `zim_cite`; it is never presented as official.

Register it with a client (this edits your client's configuration, so it is yours to run):

```
claude mcp add --scope user zimlore -- <venv>\Scripts\zimlore.exe mcp
```

## Installing documentation, by hand or by an agent with a shell

Any agent that can run a command can install documentation; nothing needs the MCP server for that. Every
missing-library error already names the command. The Kiwix catalogue is searchable (`q`, `lang`, `tag`,
`maxsize`; the OPDS description lists them), so:

```
zimlore catalog playwright                       # search the live catalogue
zimlore catalog --tag devdocs --max-mb 1         # every DevDocs ZIM of at most 1 MB (140 on 2026-11-07)
zimlore available flask                          # the same, offline, from a cached snapshot (catalog --refresh)
zimlore get devdocs_en_flask                     # download, verified against the .meta4 SHA-256
zimlore add ~/Downloads/some.zim                 # a ZIM you already have: opened, checksum-checked, recorded
zimlore sync --group languages-core --dry-run    # plan a whole set first; drop --dry-run to install
```

Each install writes a provenance record, so `zim_cite` can say where a file came from. Installing never needs
the MCP server, and the MCP server never installs: planned on-demand installation from a package URL
(`pkg:pypi/flask@3.1.0` to that version's official docs) is designed in `docs/on-demand-docs.md`, not built.

## Where the files live

`ZIMLORE_HOME` (default `~/.zimlore`), subdirectory `zim/`. Set `ZIMLORE_ZIM_PATH` (a list separated by `;` on
Windows, `:` elsewhere) to read an existing Kiwix library where it already is. Nothing is ever written inside
the repository. An optional `$ZIMLORE_HOME/aliases.json` maps your own names: `{"py": "devdocs_en_python"}`.

## The tools

| Tool | Does |
|---|---|
| `zim_libraries` | installed libraries with edition date, size, search type, `freshness`; ranks them against a name |
| `zim_resolve` | one name or alias (`flask`, `python`, `security.stackexchange.com`) to exactly one library; an ambiguous name returns the candidates |
| `zim_search` | one library or all of them; hits are refs with an excerpt and a citation |
| `zim_read` | an article, a section (`#anchor`), an API definition, or one block (`¶n`) as markdown or text, paged by a token budget |
| `zim_outline` | headings and API definitions with anchors, or a page of a library's articles |
| `zim_links` | links out, internal ones resolved to refs and marked `in_zim` |
| `zim_cite` | the citation string, edition, freshness and licence note |
| `zim_available` | **offline** search of the cached catalogue snapshot: what could be installed, the exact `zimlore get <name>` command, and the snapshot's age |

One reference grammar, accepted everywhere: `devdocs_en_flask§blueprints/index#why-blueprints¶3`. The library
may be any alias (`flask§…`), `::` is the ASCII spelling of `§`, and a bare path works when `library` is given.
`¶n` counts blocks of *our conversion* of the article, so the entry path and anchor are the durable part.

Conventions inherited from `rfclib` and `itulib`:

- A missing or empty library is an **`error` object that names the fix**, never an empty list. `hits: []` means
  the search matched nothing, not that the topic is undocumented.
- Long reads end with `next` (`{"ref", "start"}`); pass it back. A page always makes progress, even when one code
  block alone exceeds the budget (it is returned whole and flagged `oversize`).
- Every response states `freshness` (`date`, `age_days`, `stale`). A ZIM is a snapshot, and one with no `Date`
  metadata reports `stale: null`, never "fresh".
- HTML becomes markdown with **code blocks (and their language), tables, headings, lists and definition lists
  kept**; scripts, navigation chrome and inline base64 images are dropped (images appear as `[image]`).

## Offline catalogue

`zimlore catalog --refresh` (the one command here that uses the network, besides `catalog QUERY`, `get` and
`outdated`) stores the English Kiwix catalogue in `$ZIMLORE_HOME/catalog.json`, about 0.4 MB for 1,309 entries.
After that `zimlore available flask` and `zimlore catalog --offline [flask]` say what could be installed and the
exact `zimlore get <name>` to run, with no network and with the snapshot's age. The MCP server reads the same
file: `zim_available`, and a `zim_resolve`/`zim_search` miss carries `obtainable` (the top five), so an agent can
tell the user what to install instead of concluding a topic is undocumented. Without a snapshot the answer is an
error naming `zimlore catalog --refresh`; a damaged snapshot is an error too, never an empty list.

## Against Context7

| | Context7 | zimlore |
|---|---|---|
| Where it runs | hosted MCP server `mcp.context7.com`; the MCP server is MIT, the crawler and API are private | your machine; no network after the download |
| Rate limits | yes; unkeyed requests get low limits, a free key raises them | none |
| Privacy | queries go to a third party | nothing leaves the machine |
| Library names | `resolve-library-id` → `/owner/repo[/version]` | `zim_resolve` → a ZIM `Name` plus its edition date |
| Versions | pin `/owner/repo/vX.Y.Z`; falls back to the nearest indexed | **pinned by ZIM date**; a ZIM does not record the upstream release number, the pages do |
| Freshness | continuously re-crawled by the service | as fresh as the ZIM you hold (`zimlore outdated` compares with the catalogue) |
| Coverage | very large and growing; any GitHub repo can be added | what Kiwix publishes: see below |
| Result shape | curated code and info snippets ranked by the service | whole pages, or one section/definition, as markdown, cut to your budget |
| Ranking | service-side, semantic, tuned | Xapian keyword search; **no semantic matching** (see Limits) |
| Citations | library id | ZIM name, edition date, entry path, anchor |

Pick Context7 when you need the newest release of a fast-moving library and are online. Pick zimlore when you
are offline, behind a policy that forbids sending queries out, want a reproducible snapshot, or want the same
documents every run. They are not exclusive.

## What Kiwix has for developers

Measured against the live catalogue on 2026-11-07 (`docs/research.md` has the method):

- **243 DevDocs ZIMs**, 0.67 GB in total (median 0.85 MB, largest scikit-learn at 58 MB), dated 2026-05-04 to
  2026-10-31: Python, Rust, Go, Node, React, Vue, TypeScript, Django, Flask, FastAPI, PostgreSQL, Docker,
  Kubernetes, Terraform and more. This is the Context7-shaped part, and it is tiny.
- `docs.python.org_en_all` (3.96 GB, 2026-08-28), `peps.python_en_all`, `devhints.io_en_all`, `archlinux_en_all`,
  `gentoo_en_all`, `www.mankier.com_en_all` (man pages), `php.net_en_all` (**2024-08-13**, old).
- **Stack Exchange**: 181 English-filter ZIMs, 191 GB in total; `stackoverflow.com_en_all` alone is 114.9 GB
  (2026-07-02).

## Limits

- **Keyword search, not semantic.** On 34 questions paraphrased from page titles (`scripts/eval_retrieval.py`,
  DevDocs Flask and Python), the right page was first for **10/34**, in the top 5 for **23/34**, MRR 0.436.
  Questions that share words with the page do well; "isolated environment for project packages" does not find
  "Virtual Environments and Packages". Searching with the library's own vocabulary works much better. With no
  library given, 1 of 4 questions found its page: results from different ZIMs are interleaved because libzim
  exposes no comparable score.
- **No upstream version.** The ZIM date says when the docs were scraped; which release they document is on the
  pages.
- **Licences are not in the ZIMs we measured.** Neither DevDocs ZIM had a `License` metadata key; `zim_cite`
  says "not stated in the ZIM" rather than guessing. DevDocs itself is MPL-2.0, but the text it archives is
  each upstream project's.
- **`libzim` is GPL-3.0-or-later** (the binding; the C++ library is GPL-2.0 per its repository). zimlore is MIT
  and imports it at run time; see `PLAN.md` for what that means for redistribution.
- Wheels exist for Windows x64, macOS and Linux (glibc and musl) on CPython 3.11+. On Windows ARM64 `pip
  install zimlore` succeeds without `libzim`, and every tool reports the missing binding and the remedy.

## Development

```
python -m pip install -e . --group dev      # pip 25.1+
python -m pytest -q                  # no ZIM needed: tests build a synthetic one with libzim's writer
python -m ruff check . ; python -m ruff format --check . ; python -m mypy zimlore tests
python scripts/eval_retrieval.py     # needs devdocs_en_flask and devdocs_en_python installed
```

[ROADMAP.md](ROADMAP.md) lists every obligation with the test that would fail if it regressed;
[PLAN.md](PLAN.md) records the design decisions; [docs/research.md](docs/research.md) the sources.
