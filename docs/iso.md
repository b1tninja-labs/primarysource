# iso: the owner's own purchased ISO publications (proposed, not built)

Recorded 2026-11-13. This document was asked for when the owner bought ISO standards as PDFs and asked where
official copies should go. It records three things:
- where the files go;
- why they stay out of every image;
- what must be read before anything indexes them.

## 1. Where the files go

```
$PRIMARYSOURCE_HOME/iso/purchased/     # default: %LOCALAPPDATA%\primarysource\iso\purchased
```

- The folder exists on the owner's machine, with a README.
- It is the `iso` collection's home (`home.collection_home("iso")`), so a future importer and index find it
  with no extra setting.
- Put one PDF per publication there, exactly as delivered (watermarked in the buyer's name).
- Never put the files in this repository. `.gitignore` already refuses `*.pdf`, and `AGENTS.md` forbids
  document text in the tree.

## 2. Placement: personal volume, never an image

- **Not an image layer.** A container image is a copy that gets pushed, pulled and cached, so it would
  distribute the text.
- **Not a shared server.** A shared HTTP server answering several clients is networking.
- **What ISO says:** its store and help pages describe purchased PDFs as **single-user**. One user may access
  them, and posting them to a shared server or intranet needs a multi-user arrangement through the national
  member body (ISO help articles 664356 and 376041, read 2026-11-13).
- **What is still open:** whether a stdio server on the buyer's own machine counts as "personal" use.
- **How to serve it, if it is ever indexed:** this collection is mounted read-only into the buyer's own
  container, or served over stdio on the buyer's own machine. It is never baked into an image or published.

## 3. Licence: blocked on reading the paid-tier agreement

- **What ISO's terms forbid:** its no-cost access agreement and its Online Browsing Platform terms forbid
  text and data mining, scraping, harvesting, and use in "training, development, or operation" of an AI or
  machine-learning system. ISO also opts out of statutory text-and-data-mining exceptions, including EU
  Directive 2019/790 Art. 4.
- **What was not read:** the agreement for a purchase is the End Customer Licence Agreement
  (`iso.org/terms-conditions-licence-agreement.html`), and its page returned 403 to an automated fetch on
  2026-11-13.
- **Until a person reads that agreement, nothing here extracts, indexes or serves ISO text to an agent.**
  That includes the FTS5 index, the readers and the MCP tools. Whether that use is permitted for the copy the
  owner bought is the owner's call, made by reading the agreement that came with the purchase.

If it is permitted, the collection is small, because every part already exists:
- `readers/pdf.py` and `readers/bookmarks.py` (ISO PDFs carry bookmarks);
- `index.py`;
- a `<designation>§<clause>¶n` grammar such as `ISO/IEC 9899:2024§6.5.2`;
- an `import` command modelled on `ieee802 import`: it records the designation, edition, sha256 and buyer
  watermark, and never fetches.

## 4. Freely available ISO text, and bulk collections

Measured 2026-11-13:

- **Free JTC 1 standards.** About 300 ISO/IEC JTC 1 standards are available at no charge. The old ITTF page
  (`standards.iso.org/ittf/PubliclyAvailableStandards/`) is closed and now points to the ISO and IEC
  webstores. The no-cost terms above apply to them too, so they are not a corpus for this package either.
- **ISO Online Browsing Platform** and **ANSI's Incorporated by Reference portal.** Both are read-only
  viewers, with no download, print or copy. The ANSI portal covers ISO standards cited in US federal
  regulations. Neither is a source an importer may scrape.
- **Public.Resource.Org.** It posts standards incorporated by reference into US law, and *ASTM v.
  Public.Resource.Org* (D.C. Cir. 2023) held that noncommercial posting of incorporated standards is fair use.
  The ruling covers incorporated standards only, in the US only, and no ISO collection from it was found in
  this search.
- **Bulk unofficial dumps.** Copies of paid ISO standards on file-sharing sites or archives are infringing
  copies. They are not a source for this package, and nothing here looks for them.
