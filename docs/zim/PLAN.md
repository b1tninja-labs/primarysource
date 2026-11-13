# zimlore plan

zimlore serves a Kiwix library (ZIM files) to AI agents over MCP as an offline-first alternative to Context7.
This file records the decisions and why. Facts behind them are in [docs/research.md](docs/research.md); status
of each obligation is in [ROADMAP.md](ROADMAP.md).

## 1. Scope

In: find a library by name, search it, read an article/section/definition/block as markdown or text under a token
budget, follow links, cite with the ZIM's edition date, say how stale a snapshot is, and fetch ZIMs from the
public catalogue with a verified hash.

Out, on purpose:

- **Shipping or caching ZIM content.** Files live in `ZIMLORE_HOME`, never in the repository.
- **Semantic retrieval.** libzim gives Xapian keyword search and a title index. An embedding index would be a
  second corpus to build and keep in step with each ZIM; if it is wanted it is a separate extra, not a promise
  made here (ROADMAP `zl.semantic_search`, `[ ]`).
- **Re-hosting upstream documentation as curated snippets.** Context7's value is curation; zimlore returns the
  page, section or definition as published.
- **Replacing kiwix-serve.** It is a library for agents, not a web server for people.

## 2. Decisions

**Name: `zimlore`.** Free on PyPI (`names.py`: simple 404, json 404) with *zero* one-keystroke neighbours in the
931,439-name snapshot, free as a GitHub repository name under `b1tninja` (404), and not in the workspace. Rejected:
`zimlib` (ten live neighbours incl. `ziplib`, `zilib`), `zimdoc`/`zimdocs` (one keystroke from `simdoc`/`vimdoc`
and from each other), `docsmith` (taken), `zimdex` (neighbours `zindex`, `imdex`). Sibling pattern is
`rfclib`/`itulib`; `lib` would have been natural but every `zim*lib` form collides.

**One module owns the native import (`_libzim.py`).** `libzim` is a compiled extension with wheels for Windows
x64, macOS, Linux (glibc, musl) and no Windows ARM64 wheel. The dependency carries a marker that excludes only
Windows-on-ARM, so installation succeeds there and every tool answers with the missing-binding remedy instead of
a compiler error. Everything that does not read a ZIM (CLI `info`, the reference grammar, the converter, the
catalogue client) works without it. This is the `rfclib[zim]` pattern inverted: rfclib writes ZIMs and makes
libzim optional; zimlore *is* a ZIM reader, so it is a hard dependency.

**HTML to markdown with the standard library only.** `html.parser`, no BeautifulSoup/lxml/markdownify. The
measured inputs (DevDocs) are regular, and a hand-written converter is the only way to guarantee the three
things an agent needs and generic converters lose: code blocks with their language, anchors on headings and API
definitions (so `#anchor` reads work), and the removal of inline base64 images that would cost thousands of
tokens each. Cost: Stack Exchange and Wikipedia HTML has not been exercised (ROADMAP `zl.html_other_scrapers`).

**The unit of paging is the block.** A paragraph, heading, list item, table, definition or code fence is never
split. A page always contains at least one block, so a single oversized block (a 400-line log) is returned whole
and flagged rather than cut, because a cursor that cannot advance is worse than a long page. `¶n` is the nth
block; it indexes zimlore's conversion, so it is documented as less durable than the entry path and anchor.

**Sections and definitions are first-class.** DevDocs pages are whole chapters (the `os` page is the whole module).
`#anchor` reads one `<section id>` or one `<dt id>` definition and its body, which is what makes "just
`os.getcwd`" cost 40 tokens instead of 20,000.

**Library identity is the ZIM `Name`, version is the ZIM `Date`.** Aliases are derived (DevDocs slug, title
without "Docs", Stack Exchange host, user `aliases.json`) and *ranked*: exact > all words > prefix > substring >
fuzzy. A tie is an error listing the candidates, never a coin flip. Two editions of one `Name` resolve to the
newest and the response lists the others. The response says outright that a ZIM does not record the upstream
release (Context7's `/org/repo/vX.Y.Z` has no equivalent), because the honest alternative to a version number is
a date.

**Versions are not editions; a library has a family.** Producers that build documentation per package version
name each build differently (`golang_github.com_spf13_cobra_v1.8.1`, `pypi_cryptography_50.0.2`), so by the rule
above each version is its own library, and measured on the Go prototype that made `cobra` resolve to v1.8.1 over
v1.10.2 (the alias is one character shorter and the ambiguity guard compared only scores). A `Book` therefore has
a derived `family` and `version`, with no change to the ZIM format or any stored state. The family is the `purl:`
tag without its version when the ZIM carries one (the producer's own statement), else the `Name` without a
trailing `_v?<digits>(.<alnum>)*(-<alnum>)?` token; a `_YYYY-MM` date suffix is an edition marker and is dropped
first, and a bare integer of more than two digits or a four-digit year (`wikipedia_en_100`, `ubuntu_en_all_2024`)
is a count or a date, not a release. A name with no such token is its own family with no version, which is every
DevDocs and Stack Exchange ZIM, so nothing changes for them. Resolution scores a *family* (the best of its members,
so versions of one library never tie each other and alias length cannot pick a version), then picks inside it:
no version asked means the newest by `library.version_key` (numeric components, `v` ignored, pre-releases below
releases, a version with no number last); a version asked (`cobra v1.8.1`, `cobra==1.8.1`, `cobra@1.8`, a purl's
`@version`) means that exact string, else the newest whose components start with it (`3.1` never matches `3.10`),
reported as `exact` or `prefix`; no match is an error listing the installed versions, and it names no build
command because none exists. A whole `Name` always selects that very ZIM. A purl is accepted wherever a library
name is (`zimlore/purl.py` reads nine types and refuses the rest): it matches a ZIM's `purl:` tag on type,
namespace and name, and falls back to the package name for ZIMs that carry no tag. Deleting stays per `Name`:
`prune` keeps the newest N *editions* of each Name and never counts another version as one, and `remove` of a
package with several versions refuses until a version or `--all-versions` is given. The cost accepted: a ZIM with
a purl tag and one without are different families even for one package.

**Staleness is data.** Every response carries `freshness {date, age_days, stale, stale_after_days}`. `stale` is
`age > 365` days, a stated convention; `null` when the ZIM has no date. `zimlore outdated` compares with the
catalogue (network).

**Search = title matches + full-text, with a documented fallback.** Exact-title hits first, then strict
full-text, then remaining title hits, then partial matches marked `some terms`. Partial matches come from
per-word searches fused by `ln(pages / pages matching)` weights and a title boost, because libzim's parser
requires every term (found by running it; first eval run scored hit@1 8/34). Across libraries, results are
interleaved rank by rank and the response says so, since libzim exposes no comparable score. The 34-case eval
(MRR 0.436, hit@5 23/34) is the honest summary: lexical, and weak on paraphrase.

**Citations are built, not typed.** `Title [Name], ZIM edition DATE, entry PATH#anchor`, plus the ZIM's `License`
metadata or the sentence "not stated in the ZIM". No ZIM we measured had a licence key, and inventing one from
the project name would be an unverifiable claim.

**Network is confined to `catalog.py`, and downloads are verified.** The hash comes from kiwix.org's `.meta4`;
bytes may come from any mirror (the `.zim` URL redirects to third-party hosts); a mismatch discards the file.
Only `https` (or `http` to localhost, for tests) is accepted. Nothing in the MCP server touches the network, which
is the point of the project.

**ZIM content is untrusted data.** A ZIM is third-party content: its article text, titles and metadata (`Title`,
`Name`, `Source`, and therefore the `cite` strings built from them) must be quoted and cited, never followed as
instructions. The MCP server instructions say so, and the read path is bounded against hostile files (an entry
size budget, a converter output ceiling, capped list indentation, bounded redirect chains).

**Licence of the code: MIT, with a flagged tension.** `libzim` (the binding) is GPL-3.0-or-later and zimlore
imports it. MIT code that imports a GPL library is fine to publish and to use, but a *combined* binary or image
that redistributes both is GPL-3.0 as a whole. The siblings (`rfclib[zim]`) take the same position. This is a
decision for the maintainer (section 5), not something this file can settle.

## 3. Verification model

Tests build a tiny synthetic ZIM with libzim's writer (invented text, DevDocs-shaped markup) so the suite needs
no download; `tests/test_license.py` is the tripwire against ZIM content entering the tree. What the suite cannot
prove (converter behaviour on real pages, ranking) is measured by `scripts/eval_retrieval.py` and by the live
MCP run recorded in `docs/research.md`, and ROADMAP rows that depend on them stay `[part]`.

## 4. Portfolio position

`PORTFOLIO.md` §4 defines "reference libraries - not tiered" as the corpora every protocol project *cites from*
(`rfclib`, `itulib`), justified "by a citation some other project could not make". zimlore is **not** that:
it is a developer-documentation corpus for agents, not a source for protocol citations. It is therefore not
sequenced in a wave and does not count against the two-project rule, but it also is not covered by the existing
sentence. A proposed entry is in [docs/portfolio-entry.md](docs/portfolio-entry.md); `PORTFOLIO.md` has **not**
been edited, because the workspace root is shared and the classification is the maintainer's call.

## 5. Decisions waiting for the maintainer

1. **Does `PORTFOLIO.md` list zimlore, and as what?** Recommendation: a third "reference library" row with the
   sentence widened to "or that agents read from", no wave, no tier.
2. **Licence of zimlore** given GPL-3.0-or-later `libzim`. Recommendation: stay MIT (library use is the norm),
   state it in NOTICE (done), and revisit if a bundled distribution is ever planned.
3. **Name `zimlore`**, and whether the GitHub repository is `b1tninja/zimlore`. Nothing has been pushed or created.
4. **Registering the MCP server** with Claude Code / Cline (`claude mcp add ...`): edits the user's configuration,
   so not done.
5. **Publishing to PyPI**, and the release workflow's trusted-publisher setup. Not done.
6. **Which ZIMs to install by default** (a starter set). The DevDocs set is 0.67 GB in total and is the natural
   candidate; Stack Overflow is 115 GB and is not.
