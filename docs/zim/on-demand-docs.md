# Design: on-demand documentation for a purl (resolve, plan, build, install)

Status: **design, 2026-11-07; only the T2 build step has a prototype** (the prototype `docs/prototypes/purl-sphinx-docker/`, kept in the archived zimlore repository: `pkg:pypi/cryptography@50.0.2` to a ZIM in a network-less Docker sandbox in 26 s). Nothing else here is built. It refines `future-docs-by-purl.md` and settles the shape of
the agent-facing install question left open in `library-management.md` section 6: installing is not "download a
catalogue ZIM", it is **look up a package URL, find out what official documentation exists for exactly that
version, and obtain it the safest way available, possibly by generating it in a sandbox.**

## 1. The flow

```
purl --> RESOLVE --> PLAN --> (human or policy approves) --> FETCH or BUILD --> VERIFY --> PACKAGE --> INSTALL
         registry    options                                 prebuilt artefact   stub/version  ZIM +      sidecar
         metadata    + trust                                 or sandboxed build  /hash checks  metadata   with purl
                     + cost
```

1. **Resolve** `pkg:pypi/flask@3.1.0` into evidence, not guesses: the registry record (PyPI `project_urls`, npm
   `homepage`, crates.io `documentation`, Maven POM), the source repository, and the exact version's artefacts.
2. **Plan** returns a list of *options*, each with a trust tier, what it downloads or runs, the approximate size
   and time, and what it needs (network only, or a container runtime). Nothing is fetched or run yet. If no option
   exists, the plan says `none` and why; it never substitutes `latest` for a pinned version.
3. **Approve.** The plan is shown to the human, or accepted automatically only when policy says so (section 4).
4. **Fetch or build** the chosen option.
5. **Verify**: the artefact is not a stub, documents the requested version, and matches any hash the registry
   publishes.
6. **Package** into a ZIM (libzim `Creator`; metadata `Name`, `Date`, `Source`, `Tags`, plus a `purl` tag and the
   real release) and **install** with a provenance sidecar that records the purl, the option used, the source
   commit or artefact hash, and the recipe digest for built docs.

## 2. Options, in trust order

| Tier | Option | Executes untrusted code? | Evidence it exists (2026-11-07, see research notes) |
|---|---|---|---|
| T0 | **Prebuilt artefact for the exact version**: Maven `-javadoc.jar`; Read the Docs `htmlzip` of a version; docs.rs `/crate/<n>/<v>/download` zip | no: unzip and convert, treat as data | Maven: 17 of 20 sampled latest releases had a real javadoc jar (2 were 261-byte stubs); RTD: one htmlzip fetched; docs.rs endpoint works but is undocumented |
| T1 | **Official hosted docs at that exact version**, crawled politely (robots, size cap), page set checked against `objects.inv` when present | no | PyPI: 20 of the top 30 declare a docs URL, none pinned to a version; Flask's RTD has only `latest` and `stable` |
| T2 | **Build from the package's own source at that version in a sandbox** (sdist or tag): Sphinx, MkDocs, Javadoc/Doxygen/TypeDoc, rustdoc, `makeinfo --html` | **yes**: `conf.py`, build plugins and doc extensions are arbitrary code | texinfo to HTML verified in WSL; Docker 29.3.1 with a Linux engine is present on this machine |
| T3 | Docs for a *different* version (latest, nearest) | n/a | **refused by default**; allowed only with an explicit flag, and labelled in the ZIM and every citation |

T0 and T1 need nothing but HTTPS. T2 is the "container task". A plan lists only options whose requirements are met
on this machine and says which were skipped and why (for example, "T2 needs a container runtime").

## 3. The sandboxed build (T2)

Building documentation executes the package's own code (a Sphinx `conf.py` is Python; a Maven doc plugin runs a
build). So the build is a **separate, disposable, network-less step**:

- **Two containers, not one.** (a) *fetch*: network on, runs no project code, downloads the sdist/tag, verifies the
  registry hash, writes it to a volume. (b) *build*: **`--network none`**, read-only root, the source volume
  mounted read-only plus a writable output volume, non-root user, CPU/memory/pids/time limits, no host mounts.
  Build dependencies come from a **pinned recipe image** (one per generator, versions and digest recorded), not
  from the package, so the package cannot choose what runs beyond its own config.
- **Recipes** are small data files in the producer repository (generator, image digest, command, expected output
  directory, how to detect success), reviewed like code. A package with no matching recipe gets `none`.
- **Output is data**: the build writes an HTML tree; only that tree leaves the container, and it is treated as
  untrusted content by the same converter and size limits as any ZIM.
- **Reproducibility**: the sidecar stores recipe id, image digest, source hash and the build's start/end; the
  ZIM `Date` is the build date, `Source` the upstream docs URL, and a tag carries the purl.
- Not decided: Docker versus Podman support (only Docker is verified here), Windows path/volume details, and
  whether to use `docker build` with a Dockerfile per recipe or `docker run` of a prebuilt image.

## 4. What an agent may do (answers `library-management.md` section 6, question 4)

The earlier sketch had one `zim_install(name)` behind an environment variable. With purls the risk is higher
(arbitrary packages, possible code execution), so the proposal is **two-phase and asymmetric**:

- `zim_docs_plan(purl)`: **read-only**, but it uses the network (registry lookups), so it is a *network tool*:
  separate from the offline tools and enabled only with `ZIMLORE_ALLOW_NETWORK=1`. It returns options, trust tiers,
  sizes and the exact command to run. It writes nothing.
- `zim_docs_build(purl, option)`: **disabled by default.** With `ZIMLORE_ALLOW_BUILD=T0,T1` it may run only the
  tiers listed; `T2` (anything that executes code) must be named explicitly, and even then only with a recipe
  already trusted in the user's config. Every build is logged with the plan it executed.
- When a tool is disabled it returns the CLI command (`zimlore docs build pkg:... --option T0`) for the human.
- The server never installs outside `ZIMLORE_HOME`, never deletes (there is still no agent-facing remove), and a
  failed or cancelled build leaves nothing that scans as a library.

Whether MCP elicitation (asking the user from inside a tool call) is available and reliable in the clients in use
has **not** been checked; it would be the cleaner approval mechanism than environment variables.

## 5. SBOM front end

`zimlore docs sbom FILE` reads CycloneDX or SPDX, extracts each component's purl, and prints a table:
`component | version | docs: installed / T0 / T1 / T2 / none | cost`. `--build-all T0,T1` executes the safe tiers
for everything that has them. The table is the coverage report the producer promised, and the honest answer to "can
this SBOM read the docs".

## 6. Where it lives and what to build first

Recommendation unchanged: a **producer** separate from the reader (zimlore stays offline and never runs project code
itself; a `zimlore docs ...` CLI group may live in the producer and call zimlore's `add`). First slice, smallest
that proves the idea end to end:

1. `purl` parsing and normalisation (needs the real ECMA-427 rules; note the 1st edition has no per-type rules,
   see `research-producer-and-more-zims.md` section D).
2. T0 for **Maven javadoc jars** only (exact version, no code execution, a stub check, a Javadoc-to-ZIM
   conversion using the existing converter), then T0 for Read the Docs htmlzip.
3. The plan output and the sidecar fields, before any build capability.
4. Only then the sandboxed T2 recipe for one generator (Sphinx), proving the network-less container design.

## 7. Open questions for the maintainer

- Is the asymmetric agent model acceptable (plan allowed with network opt-in, build off by default, code-executing
  tiers only with an explicit trusted recipe)?
- New repository or a subpackage in this one? (Recommendation: new repository, because it needs network, a
  container runtime and per-ecosystem rules, none of which the reader should carry.)
- ~~Licence gating~~ (decided 2026-11-07, maintainer): no licence checks. The one rule is the existing one: the
  tools never redistribute content (no built ZIM is committed, published or uploaded by any command here).
- Which ecosystems first, in priority order? Evidence so far favours Maven (javadoc jars), then PyPI via Read the
  Docs, then crates via docs.rs.
