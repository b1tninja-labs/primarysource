# The `draft` collection: IETF Internet-Drafts

`primarysource mcp --collection draft` serves Internet-Drafts the reader has imported. It exists because the
portfolio tracks documents that are drafts and nothing else (RTR version 2 and the ASPA PDU, ASPA verification,
LibrePGP, the TURN REST API), which the RFC library cannot cite, and because a draft is not a fixed document:
it has revisions and a life cycle, and a result that does not say so is a trap.

Install: `pip install "primarysource[draft,mcp]"` (`draft` has no dependency of its own; it uses the standard
library and the `rfc` collection's text segmenter, which ships in the same package).

## Commands

    primarysource draft import <name>[-rev] ... | --tracked   fetch drafts (one request a second)
    primarysource draft refresh [<name> ... | --tracked]       fetch only the datatracker's current status
    primarysource draft list | info <name> | outline <name>[-rev]
    primarysource draft read <ref> [--start N] [--max-tokens N]
    primarysource draft search <words> [--name N] [--limit N]
    primarysource draft cite <ref>

`import` and `refresh` are the only commands that touch the network, and a person runs them; the MCP tools
(`draft_read`, `draft_outline`, `draft_search`, `draft_cite`, `draft_info`, `draft_list`) read local files only.
`PRIMARYSOURCE_READONLY=1` (or `primarysource mcp --read-only`) makes `import` and `refresh` refuse and stops
the server writing its segmentation cache, so a shared server can run on a read-only volume.

## Refs

`draft-ietf-sidrops-8210bis-17§5.1¶2` is draft, revision, section, paragraph. `¶n` counts the paragraph blocks
of the section (paragraphs, lists, figures, tables), as the `rfc` collection does. A section is named as the
draft prints it (`5.1`; `A.2` is Appendix A.2) or, if it is unnumbered, by a title slug (`abstract`,
`status-of-this-memo`). `draft-x-y-03:100-120` reads lines 100 to 120 of the stored text, numbered as in the
file.

A ref without a revision (`draft-ietf-sidrops-8210bis§5.1`) resolves to the latest **stored** revision, and the
result says so in its `warning:` line. A trailing `-NN` of exactly two digits is the revision, which is how the
datatracker reads names; a draft whose own name ends in two digits has to be written with its revision.

## What `info` and every result say about the draft's standing

The datatracker's state (Active, Expired, Replaced, RFC, Withdrawn by Submitter, Withdrawn by IETF), the expiry
date, the draft that replaces this one (`relateddocument` relationship `replaces`), the RFC it became
(`became_rfc`), and when that was last checked. A draft that is not alive, or a revision that is not the latest
the datatracker listed, gets a banner as the first line of every read, outline and cite, and the same words in
`warning:`. A draft still marked Active but past its expiry date is reported expired. A status older than 14
days says so. RFC 2026 §2.2 is why: an Internet-Draft has no formal status, is removed after six months
unchanged, and is subject to change or removal at any time; the only way to cite one is "Work in Progress", which
is the shape of the `cite:` line (`Authors, "Title", Work in Progress, Internet-Draft, name-NN, date, <URL>,
Section 5.1, paragraph 2.`, with the datatracker's own `#section-5.1` anchor).

## The sources, read in primary documents (2026-11-13)

- **Datatracker API** (`datatracker.ietf.org/api/`, tastypie, read-only, no key). Used: `/doc/<name>/doc.json`
  (the "simplified documents API": title, state, latest revision, expiry, authors, the whole revision history with
  posting dates) and `/api/v1/doc/relateddocument/?target__name=...&relationship__slug=replaces` and
  `?source__name=...&relationship__slug=became_rfc`. Draft states are `/api/v1/doc/state/?type=draft`: Active,
  Expired, RFC, Replaced, Withdrawn by Submitter, Withdrawn by IETF. The API notes page states no rate limit;
  one request per second is this importer's own courtesy.
- **Archive** `https://www.ietf.org/archive/id/<name>-<rev>.txt` and `.xml`, every revision of every draft,
  active and expired. Missing files answer 404 with an HTML body. The IETF's access page
  (`ietf.org/standards/ids/internet-draft-mirror-sites/`) names two bulk routes for the whole archive: that
  directory over http and `rsync.ietf.org::id-archive`. Neither is used: the collection is for named drafts, and
  mirroring every draft would be the wrong placement (below). `1id-index.txt` in the archive is an index of
  **active** drafts only.
- **Formats.** The `.txt` exists for every draft checked and is the cited rendering. The `.xml` is the author's
  *submitted* source, not the prepared one: no `pn` ids, no section numbers. Of the five tracked drafts, three
  ship xml2rfc **v2** (`<!DOCTYPE rfc SYSTEM "rfc2629.dtd">`, no `version` attribute) even in 2026, one declares
  entities (refused), and one (2013) has none. No draft checked ships v3. RFC 7749 (v2) is obsolete, replaced by
  RFC 7991 (v3), which RFC 9920 updates; the prep tool is RFC 7998.

## Segmentation: what is reused from `rfc`, and what is not

`primarysource.rfc.index.txtseg` reads a draft's `.txt` unchanged (it is the same xml2rfc rendering): table of
contents as the answer key, headings found in order, paragraphs re-joined across page breaks. Added here:
line coordinates equal the file's (form feeds and exotic separators removed first), a draft's page header
(`Internet-Draft  Title  Month Year`) is respelled to the form the segmenter skips (otherwise it leaks into
paragraphs; the RFC form it knows does not match), a draft with no headings keeps its first line, and hostile text
(NUL, a line over 2,000 characters, over 8 MB) is refused before the segmenter sees it.

`primarysource.rfc.index.rfcxml` is **not** reused: it needs prepared RFCXML v3 (`pn` ids, derived numbers).
The stored `.xml` is read for the root element's facts only (`ipr`, `docName`, `category`, format version).
A proposed core change: a shared "prep-lite" that numbers a submitted v2/v3 source the way xml2rfc does, so
paragraph ids could come from the author's XML. Until then the txt is the structure.

## Licence and placement: **volume**, not image layer

Read: BCP 78 (RFC 5378 §3.1, §3.6, §5.4) and the IETF Trust's Trust Legal Provisions 5.0 (§1.b, §1.c, §3.c,
§3.d, §6.c). Authors keep the copyright in their drafts; the Trust holds non-exclusive rights and may
sublicense. TLP 5.0 §3.c lets anyone copy and distribute a Contribution "in full and without modification", or
unmodified portions with attribution and, above a fifth of the text, the legends; §3.d withholds any licence to
modify, or to distribute without the legends. That covers only Contributions submitted after 2015-03-25; older
drafts stay under the policy in force when they were submitted (§1.c), and a draft's own legend can withdraw the
right to modify (`noModificationTrust200902`, `noDerivativesTrust200902`, `pre5378Trust200902`; RFC 7991
Appendix A.1.1). So there is no blanket grant for "the drafts": it depends on each draft's date and legend. The
collection therefore stores nothing in an image and nothing in the tree; the reader fetches the drafts they need
onto their own volume, and `info` reports each stored draft's copyright year and legend. Results are
extracts of the stored text (the segmentation re-joins wrapped lines inside a paragraph and strips its
indent; figures keep their lines) and always carry the `cite:` attribution. This is information, not legal advice.

## Storage

    $PRIMARYSOURCE_HOME/draft/<name>/status.json
    $PRIMARYSOURCE_HOME/draft/<name>/<rev>/draft.txt, draft.xml, meta.json, sections.json

A revision directory appears whole (built beside, then renamed) or not at all, and is never overwritten.
`sections.json` is a cache, rebuilt from `draft.txt` when missing or made by another parser version.

## Pins

`primarysource/draft/tracked.json` (package data, metadata only) records, per tracked draft, why it is tracked,
the revision last read, the state then, the replacement, and the sha256 of the `.txt` and `.xml` fetched. An
import of a revision with a pin refuses a different file and stores nothing; a revision without one is trusted
on first use and its digest recorded in `meta.json` (`import --print-pin` prints it for the catalogue). The
digests are of immutable archive revisions, so a mismatch means damage or a changed archive. `--sha256` pins one
explicit revision's text from the command line.

## What is not done

The ROADMAP rows are in the coordinator's report. In short: the `.xml` is not segmented; a draft with no `.txt`
(XML-only submissions) cannot be imported; there is no bulk mirror; search is an in-process BM25 over sections
and not the core's FTS index (which does not exist yet); `import` does not walk replaced-by chains to import the
successor; the legend detector reads the standard legends only.
