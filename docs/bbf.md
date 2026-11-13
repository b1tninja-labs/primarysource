# `bbf`: Broadband Forum data models and Technical Reports

```
pip install "primarysource[bbf]"                  # pypdf, needed only to import a PDF; add ,mcp to serve it
primarysource bbf import-models tr-181-2-22-0-ssh        # data-model XML, pinned to a commit (layer-safe)
primarysource bbf import-report tr-069-1-6-1             # TR-069 Amendment 6 Corrigendum 1 (a volume)
primarysource bbf read "tr-069-1-6-1§3.5"
primarysource bbf read "tr-181-2-22-0-ssh§Device.SSH.Server.{i}.Enable¶1"
primarysource mcp --collection bbf                # tools bbf_read, bbf_search, bbf_outline, bbf_cite, bbf_docs
```

The repository holds **no Broadband Forum text**: the code, `catalogue.json` (ids, titles, sizes, sha256) and
invented test files. Text lives under `$PRIMARYSOURCE_HOME/bbf/`.

## 1. Two sources, two licences, two placements

| | Data models | Technical Reports |
|---|---|---|
| Source | the XML files of <https://github.com/BroadbandForum/cwmp-data-models> | the PDF at `broadband-forum.org/pdfs/tr-069-1-6-1.pdf` |
| Pin | commit `049759159f40499f5155be0d21f2573c6381969f` (10 November 2026), sha256 per file | sha256 `21622e4a...ba115`, 3,066,832 bytes |
| Licence | each file opens with a BSD-3-Clause-style notice (redistribution with or without modification, notice kept; a licence under copyright only, patents are in the Forum IPR policy) | page 2 of the PDF: a licence to use the report to build and sell compliant products; no right to sublicense, modify or make derivative works (except code in the report); every copy of the report or a portion carries that page's notices |
| Placement | **image layer allowed** | **volume**: the user fetches it |
| Reader | stdlib XML, hardened | `pypdf` bookmarks, `pdftotext` for text when on PATH |

106 data-model files are catalogued: every `tr-181-2-22-0-*.xml` (TR-181 Issue 2 Amendment 22, split into
components) and `tr-069-biblio.xml`. TR-181 is the owner's preferred structured source and cwmp's data model.

**Not catalogued, and why.** `tr-106-types.xml` (the data types TR-181 imports) opens with an internal DTD that
declares seven entities (regular-expression fragments such as `&num;`). The parser refuses any DTD, so the file
is not imported; supporting it needs a decision on a literal-entity allowlist (roadmap row). The USP data models
(`usp-data-models`) and older TR-181 amendments are later catalogue entries, not different code. The TR PDF is
the only report so far; TR-181's own text is the XML.

## 2. Refs

```
bbf:tr-069-1-6-1§3.5¶2
bbf:tr-181-2-22-0-ssh§Device.SSH.Server.{i}.Enable¶1
```

The `bbf:` prefix is optional. The document is the Forum's file stem: `tr-069-1-6-1` is TR-069 1.6.1
(Amendment 6 Corrigendum 1), `tr-181-2-22-0-ip` is the IP component of TR-181 Issue 2 Amendment 22 Corrigendum 0.

**A report.** `§` is a clause number as the PDF's 314 bookmarks give it (`3.5`, `3.7.1.3`, `A.3.2.3`), `A` for
`Annex A.`, `Appendix-I` for `Appendix I.`, or the slug of an unnumbered bookmark (`normative-references`).
`¶n` is the nth **sentence** of the clause's span: its own text, then each subsection as a `§3.5.1 Title` line
and its text. A PDF gives sentences, not paragraphs, and the split is heuristic (after `. ! ?` before a capital,
digit or bracket, not after `e.g.`, `i.e.`, `etc.`); tables and bullets come out as `pdftotext` or `pypdf` gives
them. The same sentence index is stable only for the same extractor: the stored JSON records which one.

**A data-model file.** `§` is the full path of a node:

| Node | Address |
|---|---|
| object | `Device.IP.Interface.{i}` (a trailing dot is accepted) |
| parameter | `Device.IP.Interface.{i}.Enable` |
| command | `Device.Reboot()`; arguments `Device.Reboot().Input.Delay`, `Device.Reboot().Output.X` |
| event | `Device.Boot!` |
| profile | `Baseline:1` |
| data type, model | `IPAddress`, `Root:2.22` |

`¶n` is the nth **paragraph** of the node's description (blank-line separated; a profile's units are its
description and then one line per object or parameter it requires). A header line precedes the description:
kind, path, access, version, type with its size, range and enumeration values, default, unique keys. BBF's
template macros (`{{param}}`, `{{enum}}`, `{{numentries}}`) are left exactly as published; expanding them is the
Forum's HTML renderer's job. An object read lists the names it contains. A node defined twice in a file warns and
reads the first. A ref to a file alone gives its overview (title, spec, imports, node counts).

Every result's `unit:` footer says which unit `¶n` counts (`sentence` or `paragraph`); the collection's declared
unit is `block`.

## 3. Tools and commands

| Tool | What it does |
|---|---|
| `bbf_read(ref, start, max_tokens)` | the text of a ref; `next: start=N` continues |
| `bbf_search(query, doc, limit, start)` | units containing every word (else at least half, flagged `relaxed:`); a data-model node whose path matches is a hit with no `¶` |
| `bbf_outline(doc, under, limit, start)` | a report's clauses with pages; a model's objects, or everything under a node |
| `bbf_cite(ref)` | `cite:`, `unit:` and `span:` lines |
| `bbf_docs(filter)` | the catalogue and what is imported |

`primarysource bbf import-models | import-report | docs | outline | read | search | cite` are the same operations.
`import-report --file PDF` takes a PDF you downloaded yourself (checked against the same sha256).

## 4. The XML parser and what it distrusts

`_xml.py` drives `xml.parsers.expat` directly. It refuses any document type declaration (no DTD, so no entity of
any kind, internal or external, can be declared: no expansion bomb, no file or URL read, no parameter entity), also
when the encoding hides it (the expat handlers refuse it as well as a byte scan). It never processes XInclude,
XSLT or a schema. It caps the input (16 MiB), nesting (64), elements (1.5 million) and attributes per element
(64), and refuses an over-bound document instead of truncating. Namespace prefixes are dropped from names. This
is a private stand-in for the hardened XML decision owned by devicespy.

Importers fetch only `https://raw.githubusercontent.com/...` and `https://www.broadband-forum.org/...`, at most one
request per second, refuse a body over twice the pinned size, verify the sha256 **before** parsing or writing,
parse each XML file once with the hardened parser (a file that does not parse is not installed), and write
`install.json` last. A stored file that no longer matches its recorded sha256 is refused when read. A PDF is
extracted into a temporary name and moved into place only if extraction succeeded.

## 5. Real imports (2026-11-13)

- `tr-181-2-22-0-ssh.xml`: 43 nodes (36 parameters, 6 objects, 1 model), one request.
- `tr-069-1-6-1.pdf`: 276 pages, 314 bookmarked sections (304 headings located as text), 3,690 sentences, 21 empty
  sections (clauses that only have subsections), `pdftotext` backend, about one second.
- The brief's example resolves: `bbf:tr-069-1-6-1§3.5` is "Use of SOAP".
- With `pypdf` alone the same PDF extracts with broken word spacing ("t he", "S ession") and about 15 s; the
  `pdftotext` path (poppler or Xpdf) is therefore preferred when it is on PATH, and the stored JSON records which
  produced the text.

## 6. Open

See the `bbf.*` roadmap rows in the coordinator's report: the internal-DTD allowlist for `tr-106-types.xml`, USP
data models, more TRs, `{{macro}}` expansion as an explicit opt-in view, and the core PDF, XML and FTS5 pieces
these modules stand in for.
