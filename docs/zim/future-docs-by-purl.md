# Future: documentation by package URL (purl), so an SBOM can "read the docs"

Status: **an idea, recorded 2026-11-07, not started.** Nothing here is implemented or promised. The point is that
the pipeline `SBOM -> purl -> version-exact docs -> ZIM -> zimlore` is mostly joining things that already exist.

## The idea

Today zimlore resolves a *name* (`flask`) to a ZIM someone else built. An SBOM names *exact packages*, by purl
(`pkg:pypi/flask@3.1.0`). If a purl could be mapped to that exact version's generated documentation, built into a
ZIM, and found by zimlore, then an agent given an SBOM could read the documentation of what the project actually
depends on, at the versions it depends on. That removes zimlore's weakest property today: a ZIM records its
scrape date but not the release it documents (ROADMAP `zl.upstream_version`).

A correction worth keeping: a purl is not a CVE identifier. It names a *package*; SBOMs (CycloneDX, SPDX) carry
it, and vulnerability sources such as OSV key on it, which is why it joins docs, SBOMs and advisories without a
lookup table of our own.

## What was checked (2026-11-07)

| Fact | Evidence |
|---|---|
| purl is standardised as **ECMA-427** (1st edition, December 2025), shape `pkg:type/namespace/name@version?qualifiers#subpath`; CycloneDX has a per-component purl field and SPDX carries it as an external reference of type `purl` (from 2.2). | web search summarising the purl repository, a FOSSA article and the Ecma PDF. **The clauses and both SBOM specs were not read** (the PDF text did not extract), so field details need checking against primary text before any code. |
| Registries usually hold a docs link, not the docs. PyPI `flask`: `project_urls.Documentation = https://flask.palletsprojects.com/`. npm `playwright`: `homepage = https://playwright.dev`. crates.io `tokio`: `documentation = null` (homepage and repository only). | JSON from `pypi.org`, `registry.npmjs.org`, `crates.io` |
| Sphinx sites publish a machine-readable inventory: `https://flask.palletsprojects.com/en/stable/objects.inv` and `https://docs.python.org/3/objects.inv` both answer 200. | HTTP; the file's format was **not** parsed or verified |
| **Maven Central ships Javadoc as a versioned artefact**: `com/google/guava/guava/33.0.0-jre/` lists `guava-33.0.0-jre-javadoc.jar` beside the jar and sources. | directory listing |
| docs.rs has per-crate pages and a download link on `docs.rs/crate/tokio/latest`; its build/offline guarantees were not checked. | page scrape only |

**Not verified at all:** Read the Docs' API and version model; Sphinx `objects.inv` internals; how many
packages in each registry have any docs link, or a link that is docs rather than a marketing page (the npm
example's `homepage` is a site, not necessarily a docs root); Go (`pkg.go.dev`) and NuGet; licences of generated
documentation (see below).

## Sketch

1. **Resolve** `purl -> docs source`, by a chain, best evidence first:
   - the artefact itself when the ecosystem ships docs (Maven `-javadoc.jar`, exact GAV, exact version);
   - a published inventory (Sphinx `objects.inv`) to confirm the version and enumerate the page set;
   - the registry's documentation URL (PyPI `project_urls`, npm `homepage`, crates.io `documentation`);
   - per-ecosystem conventions (Read the Docs `/en/<version>/`, docs.rs `/<crate>/<version>/`), each recorded
     with the evidence that it holds, never assumed.
2. **Build** a ZIM from that source: unpack a javadoc jar or crawl a Sphinx tree, convert with the existing
   markdown converter's ideas, write with libzim's `Creator` (as `rfclib` and the test fixture already do).
   Record the purl in ZIM metadata (`Source`, plus a `purl` tag) and the real release in the name or tags.
3. **Serve**: zimlore learns one new alias source (the purl) and `zim_resolve pkg:pypi/flask@3.1.0` answers with an
   exact ZIM, or an error naming the build command. Staleness becomes "documents 3.1.0, you depend on 3.1.0".
4. **SBOM front end**: read a CycloneDX or SPDX file, list each component as `docs available / buildable / none`,
   and build the missing ones. That listing is the honest coverage report.

## Where it should live

Recommendation: **a sibling producer repository**, with zimlore staying a reader. Building (crawling, jar
handling, per-ecosystem rules, network, rate limits) has a different failure profile from serving, and zimlore's
rule that its MCP server never touches the network is worth keeping. The only change zimlore itself needs is purl
aliases in `library.Book.aliases` and a `purl` field in `zim_resolve`. No name has been checked for the sibling.

## Risks, stated up front

- **Redistribution.** Decided 2026-11-07 (maintainer): no per-package licence checks. The only rule is that nothing
  redistributes content: zimlore's NOTICE policy (never ship, commit or upload ZIM content) extends to the producer.
- **Coverage is uneven.** Some packages have no hosted docs, some have only a README, some only a marketing site.
  The coverage report must say "none" rather than build an empty ZIM.
- **Crawling is hostile-input handling**: robots rules, size caps, and treating fetched HTML as data, which the
  existing converter already does for ZIM content.
- **Version drift**: "latest" docs for a pinned dependency are the wrong answer; a build must fail rather than
  silently substitute another version.
