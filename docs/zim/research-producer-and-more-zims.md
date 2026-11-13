# Findings from two research passes (2026-11-07)

Both passes were run by subagents; the full notes are in the shared notes folder
(`research-formats-purl.md`, `measure-more-zims.md`). I re-checked the claims that changed a decision (listed
below) and rebuilt the numbers for the converter fixes; everything else here is as reported, with its source in
those notes. Where this file and `future-docs-by-purl.md` / `future-formats-and-sources.md` disagree, **this file
is newer**.

## A. Corrections to earlier documents

- **PyPI `chm` 1.5.0 is not a CHM reader.** Its description is "Python tools for working with the Canadian
  Hydrological Model (CHM)" (re-checked on `pypi.org/pypi/chm/json`; the one-line summary is just "python tools for
  CHM", which misled me). Remove it from the CHM candidate list; `pychm` 0.8.6 (GPL) remains unevaluated.
- The purl text the research pass read was the repository's `main` branch, which carries second-edition notes,
  **not** the December 2025 ECMA-427 PDF. Treat grammar details as provisional until the PDF is read.

## B. Producer feasibility (what exists per ecosystem)

| Finding | Number or fact |
|---|---|
| Sphinx `objects.inv` parses; its `Version` is the short Sphinx version | Python 3 docs: 20,502 entries; Flask: 628 entries; Flask reports `3.1.x` while PyPI has 3.1.3, so an inventory can sanity-check major.minor but **cannot pin an exact release** |
| Maven Central javadoc jars | 19 of 20 sampled latest releases have a `-javadoc.jar`; 2 are 261-byte stubs (manifest only), so **17 of 20 usable**; a builder must detect stubs |
| PyPI `project_urls` documentation link | 20 of the top 30 declare one; 14 of those on Read the Docs; none pinned to a version. Flask's RTD has only `latest` and `stable` |
| Read the Docs | API v3 documented, 5 requests/min unauthenticated and 60 authenticated; per-version `htmlzip` downloads exist for some projects (one fetched: 3.3 MB zip including its `objects.inv`) but availability is per project and version |
| pkg.go.dev | now has a versioned JSON API |
| docs.rs | `/crate/<name>/<ver>/download` returned a docs zip; **undocumented**, so fragile |
| Kiwix `License` metadata | optional; **0 of 29** sampled ZIMs (all 10 MB or smaller) carry it, and the OPDS feed has no licence field |
| GNU manuals | the GFDL manuals for gcc and glibc have Invariant Sections: a ZIM built from them is not freely modifiable text |

Implications for the producer design: detect stubs and refuse to build an empty ZIM; take the exact release from
the purl and registry, record both; never substitute `stable` for a pinned version; sources that ship per-version
artefacts (Maven, RTD zips, docs.rs zips) beat crawling. Not done: rendering any texinfo with `makeinfo`;
reading any CHM; a `pychm` evaluation.

## C. More real ZIMs through the converter (240 MB, SHA-256 verified, about 82,700 articles, 0 exceptions)

| ZIM | Verdict (as measured) |
|---|---|
| `www.mankier.com_en_all` 2026-10-27 | structure faithful, search 6/6; **stray `[` before headings on 91% of sampled pages: fixed** |
| `peps.python_en_all` | good, search 6/6; excerpt "Discourse thread" is page chrome |
| `devhints.io_en_all` | good, 6/6; **690 of 1,037 entries are Disqus iframes** (not articles) plus one stray OAuth iframe page |
| `archlinux_en_all` | conversion good, **search 2/6**: translated duplicates of pages crowd the top 5 |
| `devdocs_en_typescript` | good, 6/6; prev/next navigation cards leak ("Next", a heading) at the end of 29 of 79 pages |
| `devdocs_en_react` | clean, 5/6 (the miss is arguably a bad expected path) |
| `devdocs_en_django` | clean, 5/6 |

Every ZIM had a full-text index. The "fences != `<pre>`" gaps were all `<pre>` inside a table cell (PEPs and the
TypeScript handbook) and are now an inline code span with `<br>` between lines, because a pipe table cannot hold
a fence. Re-measured after the fixes (`stray '['` blocks / `<pre>` vs fences): mankier sample 1 stray in 1,802
articles; PEPs 0 stray, 6,647 `<pre>` vs 6,614 fences (the 33 are cell code spans); TypeScript 0 stray, 1,653 vs
1,641 (12 cell code spans); React and Django 0 stray and fences equal `<pre>`.

Remaining defects, not fixed: navigation-card text on TypeScript pages; Disqus-iframe "articles" in devhints
(they inflate counts and should be excluded by mimetype or size); translated duplicates in the ArchWiki ZIM
(search should prefer or filter the language the user asks for); PEP excerpt chrome.

## D. Round 2 (2026-11-07, subagent; full notes `research-round2.md` in the shared notes folder)

I re-ran the Windows lock test myself; the rest is as reported.

- **Windows file locks (verified twice).** libzim opens files without share-delete: with an `Archive` alive,
  `os.unlink` and `os.rename` fail with WinError 32 and `os.replace` over the file with WinError 5; unlinking works
  once the last `Archive` reference is dropped. So `remove`/`update` must release handles first (`library.close_all()`
  is necessary but not sufficient while a long-running `zimlore mcp` process holds its own), and an update must
  write a **new dated file** rather than replace the old one in place, as the design already says.
- **ECMA-427.** The December 2025 PDF extracts cleanly with `pdftotext`. The 1st edition defines **no per-type
  rules** (maven, pypi, npm, cargo, golang) and no ABNF: those live only in the repository's `main`. npm and golang
  case rules differ between the registry v1.0.0 and `main` (insensitive and lowercase versus sensitive). A purl
  resolver therefore needs to say which rule set it applies, and must not treat `main` as the standard.
- **Texinfo.** `makeinfo` is absent on Windows but present in WSL (texinfo 7.3). The Bash manual converted with 0
  errors and matching counts (178 `pre` / 178 fences, 154 / 154 headings); `--split=chapter` produced 117 redirect
  stubs beside 15 content pages, so a producer should use the monolithic form or follow the stubs. The licence
  appears only in an HTML comment. gnu.org stopped answering mid-run, so the prebuilt split pages were not fetched.
- **CHM.** `pychm` 0.8.6 needs an external CHMLIB and failed to build on Windows with Python 3.14 (missing
  `chm_lib.h`). 7-Zip 26.00 (installed, not on PATH) unpacked a real CHM, and the converter kept 2491/2491 fences
  and 1886/1886 headings on it. So the CHM adapter can be "unpack with 7-Zip, convert the HTML", and the only open
  question is licensing of the particular manuals, not the format.
