# can: the Bosch CAN Specification 2.0, from the owner's own copy

Recorded 2026-11-15. The owner has `can20.pdf`, the Bosch *CAN Specification 2.0* (1991, 72 pages), from the clone
`awesome-vehicle-security-and-safety` (branch `windows-safe`, path `vehicle protocol/CAN/can20.pdf`; the clone was
read, not modified). This records what the file says about copying, what that does and does not establish, and how
the collection works.

```
pip install "primarysource[can,mcp]"                # pypdf, needed only to import; mcp to serve
primarysource can import "path\to\can20.pdf"       # or put it in the can home and run: primarysource can import
primarysource can search "bit stuffing"
primarysource can read "can:bosch-2.0§3.1"
primarysource mcp --collection can                  # can_read, can_search, can_outline, can_cite, can_docs
```

Every command above refuses until `PRIMARYSOURCE_CAN_ACCEPT_TERMS` is set by the owner: see `docs/terms-gate.md`.

## 1. What the PDF says about copying

Re-read on 2026-11-15 with pypdf, in a scratch script outside the repository. The statement is on **PDF page 2**
(the page after the cover), under the cover's title block. It says that **the document as a whole "may be copied and
distributed without restrictions"** (Robert Bosch GmbH, *CAN Specification Version 2.0*, 1991, p. 2). It goes on to
say that using it, in parts or as a whole, in other documents needs the consent of Robert Bosch GmbH, and that Bosch
may change the document without notice and accepts no liability.

What that gives the owner: the whole document may be copied and distributed as it is. What it does not: reuse in
another document, whether a part or the whole, is not covered and needs Bosch's consent.

Limits of this record, stated plainly:

- This is **the in-document statement only**. Bosch's own site terms for the file were **not verified**, and the
  official download page was not found. The gate therefore passes no terms URL.
- **This repository does not ship the PDF.** The collection reads the owner's copy from the owner's own folder; nothing
  is copied into the repository, an image or a release.
- The statement belongs to this document. **The CAN FD specification (`can_fd_spec.pdf`, version 1.0, 2012) is not
  covered**: its first pages carry a copyright line and no such grant, so it is not recognised by this collection
  and is skipped if put in the home.
- An index of the text is a use the statement does not mention. That is the owner's to judge, which is why the
  gate is there (`PRIMARYSOURCE_CAN_ACCEPT_TERMS`).

## 2. How the collection works

- **Home.** `$PRIMARYSOURCE_CAN_HOME`, else `$PRIMARYSOURCE_HOME/can`, else `%LOCALAPPDATA%\primarysource\can`. A
  file named `can20.pdf` (also `CAN2.0.pdf`, `can_2.0 ...pdf`) is `can:bosch-2.0`, labelled *Bosch CAN Specification
  2.0*. Another name is skipped as not known.
- **Cutting.** The PDF has 46 bookmarks, so it is cut at them (`readers.bookmarks.cut`) into sentences, the same unit
  as `iso`. Part A and Part B both number their clauses from 1, so the second occurrence of a number takes a suffix:
  `1` and `1-1`, `3.1` and `3.1-1`. Bookmarks without a number take a slug (`recital`, `part-a`, `contents`).
- **Refs.** `can:bosch-2.0§3.1¶2`: the document, a clause, and the nth sentence of the clause's span. `can_outline`
  lists every clause as a ref with its PDF page.
- **Recognition.** `primarysource identify` reads the cover (`CAN Specification`, then `Version 2.0` on its own line)
  and reports `Bosch CAN Specification 2.0` with the import command. The CAN FD cover is not matched.
- **Same mechanism as `gm`.** The shared volume is `primarysource/localpdf/` (derived from `primarysource/iso/`
  without its designation logic); `docs/gm.md` §3 says why `pdfcorpus` was not reused.

## 3. Trial on the real file (2026-11-15, nothing imported)

`readers.pdf.extract(..., numbered=True)` called directly on `can20.pdf` with `pdftotext 4.00`; no importer, no gate
variable, no collection home, output only to a scratch folder, since deleted.

- 72 pages, 192,556 bytes, 46 sections (46 of 46 bookmarks located), segmenter `bookmarks`, 0.3 s, 39 MB peak, no
  failure. 674 sentences in about 87 KB of text.
- **Front matter:** the cover and page 2 (the grant above) come before the first bookmark (`recital`, page 3). The
  collection keeps them as a leading section, `can:bosch-2.0§front-matter` (`front_matter=True` on the spec, an opt-in
  of `readers.bookmarks.cut` that no other collection uses), so the in-document statement is readable and searchable.
- 11 ids carry a duplicate suffix (the Part A and Part B clauses). Six sections have no text of their own (`part-a`,
  `3`, `6`, `part-b`, `3-1`, `7-1`): their bookmarks are followed at once by a subsection or a divider page. Reading one that
  has no subsections says it has no text and points at the outline; reading one that has subsections includes them.
- The longest sentence is 2,028 characters: figures and tables come out as run-on text, as for any PDF read through
  these backends.
