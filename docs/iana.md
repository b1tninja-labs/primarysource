# iana: IANA protocol registries

The `iana` collection serves the IETF protocol registries as authoritative data: DHCP options and message types, DNS
classes, RR types and DNSSEC algorithms, BGP parameters, STUN attributes, TLS and HTTP registries. Each record comes with
its registry's registration procedure and its RFC citations. Nothing is shipped in the package: the user (or an image
build) imports the XML.

    primarysource iana import dns-parameters bootp-dhcp-parameters     # or --all for the catalogue
    primarysource iana lookup "bootp-dhcp-parameters§message-type-53" 5
    primarysource iana read "bgp-parameters§bgp-parameters-2#14"
    primarysource iana search stun software
    primarysource mcp --collection iana                                 # tools iana_read, iana_lookup, iana_search, iana_list

Code is stdlib only. Serving needs `mcp`.

## Source, read 2026-11-13

- **Registry files.** `https://www.iana.org/assignments/<name>/<name>.xml`, served as `application/xml` with a
  `Last-Modified` header and no `ETag`. Beside each are `<name>.xsl` (stylesheet) and `<name>.rng`.
- **Schema.** There is no single XSD. Each file has its own RELAX NG (`dns-parameters/dns-parameters.rng`) that
  includes the shared `https://www.iana.org/assignments/_support/iana-registry.rng`. The namespace is
  `http://www.iana.org/assignments`. Every file opens with an `xml-stylesheet` and an `xml-model` processing
  instruction, which the reader drops.
- **Listing.** No XML index of the registries was found (`assignments/index.xml` and `assignments.xml` return 404). The
  index is the HTML page `https://www.iana.org/protocols` (about 640 distinct `/assignments/` file names at the time of reading), whose links read
  `/assignments/<file>#<registry-id>`; `<file>` is the file name and `<registry-id>` the id of a sub-registry inside it.
  That fragment form is IANA's own citable URL (the schema's `citable_url`).
- **File layout.** The root `<registry id="<file name>">` has `title`, `updated` (a date) and nested `<registry id>`
  elements, then a `<people>` table. A registry has `registration_rule`, `expert`, `note`, `range` (a number span, its
  `hex` form and its rule), `xref`, `footnote`, and `<record>` rows. A record's columns are plain child elements whose
  names differ by registry (`value`, `name`, `description`, `type`, `code`, `length`, `bit`, `flag`, ...). A record may
  carry `date` and `updated` attributes. A citation is `<xref type="rfc" data="rfc4271" section="4.3"/>`; the schema
  allows types rfc, rfc-errata, draft, uri, registry, person, note, text and unicode, and an RFC fragment of section,
  appendix, page, table, figure or anchor.
- **Terms.** The Protocol Registries, meaning the data linked from iana.org/protocols and ietf.org/assignments, are under
  the joint IANA/IETF statement at `https://www.iana.org/help/licensing-terms` (revised 2021-11-10): they "may be freely
  used by any party for any purpose" and any copyright is dedicated to the public domain under **CC0 1.0**, with no
  warranty and no guarantee about third-party rights. RFC 8722 section 2.4 puts the IPR in the registries with the IETF
  Trust. **Excluded** from the statement: the root zone, .INT and .ARPA, the IDN repository, the number registries and RIR
  allocation data (IPv4/IPv6 address space, AS numbers) and the Time Zone Database. The catalogue holds none of them, and
  a user who imports one by name takes it under whatever terms IANA states for it. The ICANN terms of service
  (`icann.org/privacy/tos`, effective 2020-06-12) say nothing about automated access or reuse of registry data.
- **Placement: image layer.** CC0 permits redistribution, so a build may fetch the files into an image layer. A user's
  machine keeps them under `$PRIMARYSOURCE_HOME/iana/`. Either way no registry text goes in this repository, and the
  tests use invented registries.
- **Polite use.** `robots.txt` is `User-agent: *` with an empty `Disallow`, and no page found states a request rate. The
  importer sends at most one request per second (an `interval` below 1.0 is refused), identifies itself in the
  User-Agent, sends `If-Modified-Since` so an unchanged file costs a 304, follows no redirects, fetches only the
  `assignments/<name>/<name>.xml` URL, and stops at the first failure.

## What the importer stores

`$PRIMARYSOURCE_HOME/iana/<name>.xml` is the file byte for byte. `manifest.json` records, for each: `url`, `sha256`,
`size`, `updated` (the registry's own date from the XML), `fetched` (UTC) and `last_modified`. A file is parsed
before it is stored, with the hardened reader, and its root `id` must equal the name. Reading checks the file against
its recorded sha256 and puts a `warning:` line in the result if they differ or there is no entry.

The reader (`xmlsafe.py`) is built on expat and refuses any DOCTYPE, entity, notation or external reference, any
encoding but UTF-8, and input over 32 MB, nesting over 32, over 600,000 elements, attributes over 4,096 characters,
and text over 1 MB in one node. It follows the approach of devicespy's `xmlsafe`, with processing instructions dropped
instead of refused.

## Refs

Grammar, on the core's `RefGrammar`: `<file>[§<registry-id>][#<value>][¶<n>]`, with `iana:` accepted as a prefix.

| Ref | Reads |
|---|---|
| `dns-parameters` | the file: every registry in it, indented by nesting, each with the ref that reads it |
| `dns-parameters§dns-parameters-4` | one registry: procedure, ranges, experts, notes, then its records |
| `dns-parameters#dns-parameters-4` | the same, in IANA's own fragment spelling |
| `bgp-parameters§bgp-parameters-2#14` | the record(s) whose value is 14; a range that contains 14 counts |
| `bgp-parameters§bgp-parameters-2¶15` | the 15th record of the registry, in file order |

- `§` names a registry by its IANA id (`[A-Za-z_][A-Za-z0-9_.-]*`), `::` is the ASCII spelling.
- `#` after a `§` is a **value**; with no `§` it names a registry. A value is a decimal or `0x` hex number, a range such
  as `6-255`, or text. A number matches a record whose value or `hex` column is that number or a range containing it
  (`010` is ten). Text matches a value equal to it ignoring case; if no value does, a column equal to it (`A` finds RR
  type A in `dns-parameters-4`).
- `¶n` counts records in file order, so it is stable until IANA inserts a row. The unit is the record. A value ref is the
  durable one for code that wants "DHCP message type 5"; `¶n` is for citing a row you just read.
- A registry id is unique within its file, so `<file>§<id>` is unambiguous. Registry ids are not globally unique.

A result's `cite:` footer reads `IANA, "<title>", value <v>, <iana.org URL>#<registry-id>, file updated <date>`. Each
row lists its citations as `refs: RFC4271, Section 4.3`; the `rfc` collection reads `RFC4271§4.3`. Inline citations in notes
appear as `[RFC9108]`.

## Measured, 2026-11-13

A real import of four registries (names and counts are IANA's, not in the tree):

| File | `updated` | Registries | Records | Bytes |
|---|---|---|---|---|
| `dns-parameters` | 2026-11-09 | 28 | 408 | 95,028 |
| `bootp-dhcp-parameters` | 2026-02-02 | 20 | 317 | 61,628 |
| `bgp-parameters` | 2026-09-09 | 42 | 313 | 62,175 |
| `stun-parameters` | 2024-12-20 | 7 | 143 | 25,151 |

## Not done

- No full-text index: search scans parsed rows in memory (one file parsed once per mtime), which is enough at this size.
- The catalogue is the registries the portfolio is thought to need (`likely_users` is indicative). Only the four above were
  imported and read end to end; the other URLs were confirmed to answer HTTP 200 on 2026-11-13.
- CSV, HTML, text and JSON renderings of the registries are not used. A registry's `hide` and `file`
  (MIB, YANG, template links) elements and a range's `entry_size` are ignored; a record's `file` column is kept as text.
- Registries with columns that are not flat text (none seen in the four) would be flattened to their text.
