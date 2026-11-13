# Parser validation, 2026-11-13

Each collection's parser was checked against a second source for the same documents, on the owner's real corpora
(read-only), and the disagreements were spot-checked by hand. No document text is quoted here: only ids, counts and
line numbers. The scripts and their full outputs are in the side-session notes,
`primarysource-validation-2026-11-13/{rfc,nist,itu,usb}/`; rerun them to measure a fix.

The ROADMAP rows that come out of this are named `val.*` (shared) and `rfc.*`, `ns.*`, `ia.*`, `us.*` (per collection).

## One shared failure: the cascade

The numbered-heading splitters in rfc (`index/txtseg.py`), nist and usb (`ingest/extract.py`) accept a heading only
when its number is the expected next one. One missed heading therefore drops every later sibling and child:

| Collection | Misses explained by the cascade |
|---|---|
| usb | 1,485 of 1,749 missing headings (85%) |
| rfc | 194 of 392 missing sections, plus 41 directly (a heading followed straight by its child is rejected) |
| nist | most of the 93 documents whose first wrong id is a false positive (footnote, list step, sample outline) that takes the real heading's number |

The fix is the same everywhere: let an independent list of expected headings (the document's own table of contents,
its PDF bookmarks, or an OSCAL catalogue) admit a heading the sequence rule rejected, and reset the sequence there.
That belongs in the core segmenter (`cl.segment_numbered`), not in three copies.

## rfc: plain text against RFCXML (all 1,384 RFCs that have both)

- Section tree: 1,356 RFCs (98.0%) agree exactly. 392 of 46,607 sections (0.84%) are missed, mostly at depth 4 or
  deeper. There are no wrong numbers. The XML parser has one bug of its own (rfc9694: an unnumbered References
  section read as numbered).
- Extra sections are not XML errors, as first written here: 46 of the 49 that the text side reports beyond the XML
  are rfc9592's quoted Tao numbering under Appendix A, which the XML rightly leaves unnumbered (now
  `txtseg._unnumber_quoted`). The other 3 are appendices the XML marks `numbered="false"` while the text prints
  "Appendix A." (rfc10049, rfc9773): a labelling choice, not a bug on either side.
- Measured again on 2026-11-13 after the fixes below (cascade, title gate, depth, quoted numbering, plus rfclib's
  lowercase-directive titles): 1,372 of 1,384 RFCs agree exactly, 36 sections are missed, 3 are extra (from 1,361,
  182 and 49 on `claude/rfc-contract-6a191a`). On the 8,457 text-only RFCs the same changes add 773 headings and
  drop 5 (a depth-7 heading swallowed into its parent's title in rfc6505, and prose in rfc803 and rfc1700). Still
  missed: titles whose first line ends in a comma and wraps (rfc9788 C.3.13.x, rfc9288 4.4.19) and lowercase-led
  identifiers ("pNFS Client", rfc8881 12.2.3).
- Headings land on the right line for 53,299 of 53,300 matched sections. Section text agrees at a median similarity
  of 1.0.
- Titles: 1,068 mismatches in 401 RFCs (truncated, or built from the contents' first line plus the heading's second).
- Causes, in `txtseg.py`:
  - `_followed_by_body` rejects a heading followed by its child (rfc9288 line 338);
  - the title check rejects lowercase, `<`, trailing `.digit` and comma titles (rfc8991:556, rfc9031:1549); now
    widened on the structurally guarded scan only: single lowercase directive names, `<`-led titles, and comma
    titles under multi-level numbers (`_guarded_title`);
  - `parse_toc` mishandles contents without page numbers, which is every RFC from 8650 on (rfc8953:66, rfc9930:70,
    rfc8700:70);
  - `segment` builds titles from the contents (rfc9787:2025);
  - `_NUM` allows only 6 levels (rfc8878:941); now 8.
- Not covered: RFCs before 8650 have no XML, so the page-numbered layout (most of the 9,841) is unvalidated. By eye,
  RFC 2119's keyword list becomes sections.

## nist: PDF text against OSCAL and against PDF bookmarks

- Extraction (affects nist and usb): the `pdftotext` on PATH is xpdf 4.00, not poppler. It writes non-BMP characters
  as surrogate pairs, so 86,455 U+FFFD land in 26 files (mostly FIPS 203–205 maths). Ligatures are left
  un-normalised in 18 files, and in fips197, sp800-188 and sp800-203 they are dropped entirely.
- **Fixed here:** the shared reader (`pdfcorpus.corpus.text_lines`) broke lines on a lone CR, so every line after one
  (sp800-38g:449, sp800-166:2187) was off by one.
- SP 800-53r5 controls against OSCAL: 1,189 of 1,196 found, with 0 extra and the same order. The 7 missing are
  version drift, because the stored PDF predates OSCAL 5.2.0. Statement text has a mean similarity of 0.996. 69 titles
  are cut at a wrap or lose a parenthesised suffix. SP 800-171r3, 172r3 and 218 have 0 controls indexed although the
  PDF text has them.
- `oscal._select_text` drops `<insert>` inside `<choice>`: 71 choices in 53r5 render as "[one-or-more: | …]".
- Sections against bookmarks, over 183 PDFs with numbered outlines: 55.6% of the bookmarked ids are found and the
  median agreement is 0.70. Three splitter fixes, tried on a copy (strip the running header, compare parent ids as
  integers, accept `Appendix X:`), raise the median from 0.60 to 0.87 and the number of documents at 0.9 or above
  from 31 to 70.
- Bookmarks can be wrong too: 36 outlines point their first chapters at the contents page. So use them as an ingest
  cross-check, not as the segmenter, and take ids and titles from OSCAL where it exists.

## itu: clauses against PDF bookmarks, editions against each other

- 1,420 of 1,424 numbered or annex bookmarks are found, and there are no duplicate or out-of-order clause ids. So the
  `warning` never fires, and every failure is a silent merge.
- Failures:
  - annex letters are fixed at `[A-I]`: X.680 J, K and L are lost into §I.4.4 (55,084 characters), and `parse_ref`
    rejects `J.1`;
  - annexes without their own bookmark vanish into the previous clause (X.690-2008/2015 Annex B, X.691 A–F);
  - short unbookmarked headings fall under the 20-character floor (X.680 §52.8, X.690-2008 §8.1.2);
  - edition-specific figure text.
- X.690 2008, 2015 and 2021 share 252 clause ids. The only real textual change in shared clauses is §2.1.
- ASN.1: modules parse from page text but not from clause bodies, because `tidy` collapses the newlines that
  `asn1mod` relies on (X.680 D.2 yields 1 of 14 assignments). `XER INSTRUCTIONS`/`PER INSTRUCTIONS` headers and
  `LINK-DEFINITIONS` are rejected.
- Sentences (¶n): "e.g.", "i.e." and clause numbers never split falsely. Keeping "etc." as an abbreviation merges 10
  pairs; about 20 quote-initial sentences are not split. Colons end 21% of ¶ boundaries, so ¶1 of every definition is
  only the term. Whether a colon should end a ¶ is a decision, not a bug.

## usb: splitter against PDF bookmarks and the printed contents

- On 54 gradable outlined documents: recall 0.785, precision 0.978, median agreement 0.90. 6 documents are below 0.5
  (MBIM compliance 0.13, eUSB2 PHY 0.21, OpenUSBDI 0.24).
- On 35 documents without bookmarks, checked against the printed contents: recall 0.727, precision 0.941.
- USB splitter against the NIST copy on the same text: where only one has an entry, USB is right 1,134 times and
  wrong 20; NIST is right 88 times and wrong 290. So the USB splitter is the better base, but it should become the
  core segmenter (`us.base_segmenter`) only after the cascade is fixed. Its `_CHAPTER` rule is wrong on Source Power
  (line 931).
- `usb-split-measure.json` labels 19 documents "good" that agree with the bookmarks below 0.8. Its counting checks
  cannot see a cascade, so it is superseded by this comparison.
