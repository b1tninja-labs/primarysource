# Reference corpora for the Bluetooth LE / ELM327 / OBD effort: a decision document

Researched 2026-11-14 for the sibling effort (`obd-bridge`, `obdlink-re`, `volt`): a host-side BLE-to-TCP bridge for
an ELM327/STN adapter, which carries ELM327 ASCII AT/ST commands over GATT, ISO 15765-2 CAN transport, ISO 14229 UDS
and GMLAN. Nothing here is reader code and no document text is in the tree. Every fact has its source; **(m)** marks
a statement from memory, **(unverified)** one I tried and could not confirm. Licence terms are paraphrased.

## 1. Recommendation, ranked

| # | Candidate | Value to the effort | Licence / effort cost | Verdict |
|---|---|---|---|---|
| 1 | Bluetooth SIG **Assigned Numbers** YAML (company ids, 16-bit UUIDs) | High: names `0xFFF0`..`0xFFF2`, resolves company ids in advertisements | **No open licence**; file header says proprietary, "furnishing does not grant any licence" (§2.4). Trivial reader (YAML) | **Add as a fetched-by-user volume** (like `usb`/`nist`): never in the tree, never redistributed |
| 2 | **pcapng + pcap link-type registry** (IETF drafts, tcpdump.org table) | High: the capture format the bridge debugging uses, link types 187/201/251/254/256 | IETF Trust provisions (drafts), BSD-3-Clause (tcpdump/libpcap code); the link-type page states no licence (§3). Tiny | **Add**: small, citable, redistributable enough; the draft part is an extra on the existing `draft` collection if it handles these |
| 3 | **btsnoop** (FTE spec page) | Medium: Android "HCI snoop log" is the practical capture source | FTE page, no licence read. Small | **Link-only** now; cite Wireshark `btsnoop.c` and RFC 1761 (already in `rfc`) |
| 4 | Bluetooth **Core Specification** (HTML/PDF) | Highest in substance (ATT, GATT, HCI) but the corpus is ~3,800 pages | Free to download for viewing; **redistribution terms not found** (§2.1). Needs a reader for the SIG's HTML or a PDF cut | **Add last, as a purchased-style personal volume** (the `iso` model: the owner downloads, only the extraction stays local). Do not fetch for the user until the licence question in §6 is answered |
| 5 | **GATT Specification Supplement** (PDF, plus YAML in the same repository as #1) | Low-medium: characteristic formats; the effort mostly uses vendor characteristics | Same as #1 | Come with #1 (same repository, same reader) |
| 6 | **ELM327 datasheet** (ELM Electronics) | **Very high**: the AT command set is *the* wire protocol | Copyright Elm Electronics; no redistribution grant found. PDF, no bookmarks | **Link-only**, plus a personal-volume import (`iso` model) if the owner wants search. The official PDF URL could not be confirmed (§4.1) |
| 7 | **STN11xx/STN21xx datasheets and FRPM** (OBD Solutions) | **Very high**: all `ST...` commands, `ATPP`, power save | Copyright OBD Solutions, LLC; no redistribution text read | Same as #6 |
| 8 | ISO 15765-2, ISO 14229-1, SAE J1979/J2534 | High, paywalled | Cannot be redistributed; the owner buys, `iso` collection imports | **The `iso` import path already exists** (ISO/IEC 7816 were imported on 2026-11-13); SAE is a new identification rule. Cite by number only otherwise |
| 9 | Windows/Android platform docs | Medium for implementation | Vendor documentation, not standards (§5) | **Note only** |

First to add: **#2** (cheap, safe), then **#1+#5** (one reader, one repository, but fetched by the user and kept out of
git), then **#6/#7** as owner-supplied imports if the `iso` path generalises. **#4** waits for the licence answer.

## 2. Bluetooth (publisher: Bluetooth SIG, Inc.)

### 2.1 Core Specification

| Fact | Finding | Source, read 2026-11-14 |
|---|---|---|
| Publisher | Bluetooth Special Interest Group (Bluetooth SIG, Inc.) | `https://www.bluetooth.com/specifications/specs/` |
| Current version | **Core 7.0, "Adopted"**. Core 6.0 and later are also listed; the page gives no adoption date (unverified) | same; `.../specs/core-specification-7-0/` |
| Obtaining | A per-version page offers the **HTML** and a **PDF**, plus test suites (TS), ICS and an IXIT spreadsheet, per layer (L2CAP, ATT, GATT, GAP, SM, HCI, LL...). A search result for 6.0 described the specification as publicly downloadable from the SIG's site. Whether a login or click-through agreement stands in front of the PDF was **not** determined | the same pages; a web search |
| Redistribution | **Not found.** The Terms of use give non-members a limited, revocable permission to view and use site content for evaluating the technology, say the SIG and its members own the content and all draft and adopted specifications, and reserve everything not granted. The Copyright policy is only a DMCA notice procedure. The *Bluetooth Patent/Copyright License Agreement* (members) is referred to, not reproduced, and I did not read it | `https://www.bluetooth.com/terms-of-use/`, `.../copyright-policy/` |
| Format | HTML (online) and PDF; ~3,800 pages for 6.0 (secondary source) | search result |
| Reader feasibility | Core is one very large document with its own part/volume numbering. A PDF cut through `readers/pdf.py` works only if the PDF has bookmarks; with 3,800 pages it exceeds the reader's page ceiling today (`test_a_pdf_with_no_bookmarks_junk_or_too_many_pages_is_refused`). The HTML needs a new reader. Per-volume imports are the realistic shape |  `primarysource/readers/pdf.py` |

Where each protocol lives, **(m)** from the 5.x layout, **not re-checked against 7.0**, which may have moved parts:

| Layer | Volume / Part (m) |
|---|---|
| Architecture overview | Vol 1 |
| BR/EDR controller (LMP, baseband) | Vol 2 |
| Host: L2CAP | Vol 3 Part A |
| Host: SDP | Vol 3 Part B |
| Host: GAP | Vol 3 Part C |
| Host: ATT | Vol 3 Part F |
| Host: GATT | Vol 3 Part G |
| Host: Security Manager | Vol 3 Part H |
| HCI functional specification | Vol 4 Part E |
| HCI transports (UART H4, USB, three-wire) | Vol 4 Parts A-D |
| LE controller (link layer) | Vol 6 |

The test-suite page confirms only the layer *names* above, not the volume numbers.

### 2.2 GATT Specification Supplement (GSS)

Defines GATT characteristics and descriptors that are not defined in Core or in a service specification. The page gives
**no version or date** (unverified). Offered as PDF and as YAML in the public repository below; earlier versions via an
archive link. `https://www.bluetooth.com/specifications/gss/`.

### 2.3 Assigned Numbers

Contains the company identifiers and the 16-bit UUIDs (services, characteristics, members, SDOs). The SIG states the
numbers are also published as YAML in a public repository, `https://bitbucket.org/bluetooth-SIG/public` (described there
as "Public YAML files for Bluetooth SIG Assigned Numbers, GATT Specification Supplement, and Device Properties"; last
updated the day of this research). Layout read through Bitbucket's API: `assigned_numbers/{company_identifiers,core,
mesh,profiles_and_services,service_discovery,uuids}`, `gss`, `dp`. The `uuids/` directory holds `member_uuids.yaml` (727
entries), `service_uuids.yaml` (76), `characteristic_uuids.yaml` (512), `sdo_uuids.yaml` (17) and others.

Format: YAML. Feasibility: the cheapest reader of any candidate here (the `usbids` pattern: one import, one lookup tool).

### 2.4 The licence of that YAML, read from the files themselves

The repository has **no `LICENSE` or README** at the root (API listing: `MSC_tool_styles`, `assigned_numbers`, `dp`,
`gss`, `.gitignore`). The only terms are a comment block at the head of each YAML file. Paraphrased: the document is
*not* a "Bluetooth Specification" as the Patent/Copyright License Agreement defines it; members' use is governed by
their agreements; it is provided as is; it is **proprietary to the SIG**, and furnishing it grants no licence to any
intellectual property; copyright 2020-2026 Bluetooth SIG, Inc. That is a disclaimer, not a grant: nothing says it may
be copied, mirrored or redistributed. Consequence for this repository: the tree must not contain it (AGENTS.md: "No
document text in the tree"), and a collection would fetch it per user, as `usb` does. I read two files in full
(`member_uuids.yaml`, plus the head of `company_identifiers.yaml`); the other files are assumed to carry the same header
(unverified).

### 2.5 Why `0xFFF0` is not what a vendor adapter thinks it is

The 16-bit UUID space is the SIG's. Members get 16-bit UUIDs from the `0xFCxx`-`0xFExx` range (the `member_uuids.yaml`
list spans `0xFC1E`..`0xFEFF`); the `0xFFEF`-`0xFFFE` range is held by the **SDO** list. In the registry as read today
(`sdo_uuids.yaml`):

- `0xFFF0` = **Public Key Open Credential (PKOC)**
- `0xFFF1` = **ICCE Digital Key**
- `0xFFF2` = **Aliro**

`0xFFF0` is not in `member_uuids.yaml`, `service_uuids.yaml` or `characteristic_uuids.yaml`. So the `FFF0`/`FFF1`/`FFF2`
service and characteristics that cheap ELM327 BLE adapters expose are **not an assignment to the adapter's maker**: they
are a squat on 16-bit values the SIG has since assigned to credential and digital-key standards. The obvious
consequence for the bridge: **never identify a device by `0xFFF0` alone**, match by GATT property (as the OBDLink app
does, `obdlink-re-findings.md`), name or company id. I do not know when these assignments were made, so whether a
given older adapter predates them is **unverified**.

## 3. Capture and interchange formats

| Format | Publisher / location | Status read | Licence | Format; feasibility |
|---|---|---|---|---|
| **pcapng** | IETF OPSAWG, `draft-ietf-opsawg-pcapng`, `https://datatracker.ietf.org/doc/draft-ietf-opsawg-pcapng/` | **Internet-Draft -06, 2026-09-19, intended Informational, "I-D Exists", expires 2027-03-23. Not an RFC.** | Copyright IETF Trust and the authors; BCP 78 and IETF Trust Legal Provisions; code components under Revised BSD | Text. Check `rfc_info`: the `rfc` collection holds RFCs only, so a draft is read through the existing `draft` collection (`docs/draft.md`) |
| **Link-type registry** | tcpdump.org, `https://www.tcpdump.org/linktypes.html` (the page says an IETF process, `draft-ietf-opsawg-pcaplinktype`, will replace it with an IANA registry; that draft's state was not read) | Rows: **187** `BLUETOOTH_HCI_H4` (HCI UART transport packets), **201** `BLUETOOTH_HCI_H4_WITH_PHDR` (with a direction pseudo-header), **251** `BLUETOOTH_LE_LL`, **254** `BLUETOOTH_LINUX_MONITOR`, **256** `BLUETOOTH_LE_LL_WITH_PHDR`, and 255 `BLUETOOTH_BREDR_BB` | **Page states no licence**, only "© 1999-2026 The Tcpdump Group" and usage rules (values must match the stated headers exactly, 147-162 are private use). libpcap/tcpdump *code* is BSD-3-Clause | HTML table. A `usbids`-style lookup is one importer; the licence of the *page* is the gap |
| **btsnoop** | Frontline Test Equipment (FTE), "BT Snoop File Format" at `https://fte.com/webhelpii/hsu/Content/Technical_Information/BT_Snoop_File_Format.htm` | Version 1; header magic `btsnoop`, then big-endian version and datalink type. Datalinks: 1001 un-encapsulated HCI (H1), 1002 HCI UART (H4), 1003 BSCP, 1004 H5; 0-1000 reserved for RFC 1761 compatibility | Not read | HTML page. BlueZ also writes 2001 (Monitor) and 2002 (Simulator), which Wireshark's reader rejects |
| **RFC 1761 snoop v2** | RFC Editor | **Already in this repository's `rfc` collection**: `rfc_info RFC1761` returns "Snoop Version 2 Packet Capture File Format", INFORMATIONAL, current, no errata | RFC (IETF Trust) | Covered; nothing to add |
| **Wireshark Bluetooth dissectors** | Wireshark project | De-facto reference for how 187/201/254 and btsnoop are decoded; its `wiretap/btsnoop.c` is the readable statement of the format | GPL-2.0-or-later **(m)**, not re-read | Source code, not a corpus; cite by file and commit, do not import |

`rfc_search` finds no document for "pcapng packet capture file format" and none for Bluetooth LE or GATT, so **nothing
in the `rfc` collection overlaps** apart from RFC 1761. (`usb` is USB-IF's; no overlap either.)

## 4. Automotive and OBD

### 4.1 ELM327 (ELM Electronics)

The datasheet is the command reference for `AT...` (`ATZ`, `ATE0`, `ATSP`, `ATSH`, `ATCRA`, `ATFCSH`, `ATPP`...). Copies
found, **none from elmelectronics.com** (the two URLs I tried there returned 404, so the official location is
**unverified**): revisions DSH (76 pages, on scantool.net as `elm327dsh.pdf`), DSI (82), DSJ (94, a later revision); the
copies cite "Copyright 2005... by Elm Electronics Inc." Format: PDF, text-based, no bookmarks confirmed. No
redistribution statement was found. The page-count growth across revisions means the revision matters when citing.
Many "ELM327" devices are clones implementing an older subset.

**Read 2026-11-14, a copy the owner pointed at:** `https://cdn.sparkfun.com/assets/learn_tutorials/8/3/ELM327DS.pdf`
(SparkFun's CDN, not Elm Electronics). It is **ELM327DSI**, "ELM327 OBD to RS232 Interpreter - v2.0", 82 pages, PDF
created 2013-06-12 with Acrobat PDFWriter on a Mac, 387.6 KB. It is **encrypted** (permission flags, not a rights
statement), has **no bookmark tree**, and its text extracts cleanly with pypdf. The AT command summary is on pp. 9-11,
descriptions pp. 11-27, programmable parameters pp. 57-62, error messages pp. 78-80, and the index on pp. 81-82. Its
only terms, on p. 80: "All rights reserved. Copyright 2005 to 2013 by Elm Electronics Inc.", plus a no-warranty,
no-liability and patent disclaimer. **It grants no right to copy or redistribute**, so a third-party host does not
change the position. DSI (2013) is older than the DSJ revision (94 pages) seen elsewhere, so commands added later
(the v2.1+ set, if any) may be missing from it: confirm the revision before citing a command as absent. The copy was
saved by the fetch tool outside the repository and is not in the tree.

### 4.2 STN (OBD Solutions, LLC; ScanTool.net is the same company)

- Documents on `https://www.scantool.net/stn1110/` (copyright footer "OBD Solutions, LLC"): the **STN1110 datasheet**,
  the **STN1100 Family Reference Manual** (`stn11xx21xx_frpm-c.pdf`, the `ST...` command reference), "STN1110 vs ELM327",
  and the **STN11xx PowerSave** note. A separate STN2120 datasheet is on scantool.net and states it must be used with the
  FRPM; the STN21xx family shares the STN11xx command set per obdsol.com. The STN2120 is marked discontinued.
- **Who owns/licenses them:** OBD Solutions, LLC (same entity as ScanTool.net). I found **no redistribution terms**; the
  ScanTool page's copyright line links to a separate page I did not read. Third parties (SparkFun, Core Electronics,
  Scribd, Parallax) host copies; that does not make redistribution permitted.
- Citable but not copyable. Format: PDF.

### 4.3 ISO 15765-2, ISO 14229-1 and SAE

| Standard | Current edition found | Obtaining | Notes |
|---|---|---|---|
| ISO 15765-2 (DoCAN transport/network layer) | **ISO 15765-2:2024**, 4th edition, published 2024-04 (replaces 2016), per ISO's catalogue entry and resellers | Paid (ISO, national bodies, ANSI webstore); previews on ANSI | `iso` import path handles the PDF once bought |
| ISO 14229-1 (UDS) | **Unclear.** 14229-1:2020 (+Amd 1:2022) is still sold as current; a **2026 fourth edition (dated 2026-06)** is listed by ANSI and a UK shop, with one reseller showing the 2020 edition's validity ending 2026-06-05. Whether the 2026 edition is in force: **unverified** | Paid | Confirm on iso.org before citing a clause number; clause numbers can change between editions |
| SAE J1979 / J1979-2 (OBD services; OBDonUDS) | J1979-2 **202604** (revised 2026-04-21 per SAE Mobilus listing); a reseller says May 2026 | Paid (SAE Mobilus) | J1979's current revision letter not confirmed |
| SAE J2534-1 / -2 (pass-thru) | J2534-1 **5.00** (2022-05) most likely current, conflicting listings, **unverified**; Mobilus page not reached | Paid | The API *header* and DLL conventions are widely mirrored; the standard text is not free |

**Publicly citable substitutes, all (m) and not read here:** ISO 15031-5 is the ISO sibling of J1979 and equally paid;
the **SAE J1979 PID tables and OBD-II PID list** are reproduced in Wikipedia and in free vendor guides (secondary, not
authoritative); **ISO 14229 service ids** are mirrored in open-source stacks (e.g. Linux `can-utils` and several UDS
libraries) with their own licences. None is a primary source in this repository's sense. The honest options are: buy and
import, or cite the standard by number and say the clause was not checked.

## 5. Platform API references (note only)

Microsoft Learn's `Windows.Devices.Bluetooth` and `.GenericAttributeProfile` namespace pages and the BLE overview/FAQ
exist at `learn.microsoft.com` (found, not read for licence). Android's Bluetooth LE guide is at
`developer.android.com` (not fetched). I **could not verify** either site's licence: from general knowledge, Learn text
is CC BY 4.0 and Android docs CC BY 4.0 with Apache-2.0 samples **(m, unverified)**. They are vendor documentation
describing one implementation, change without versioning, and are not standards; leave them as link-only pointers.

## 6. Open licensing questions for the owner

1. **Is a user-side fetch of the Core Specification and Assigned Numbers acceptable** for the owner's personal volume
   (the `iso` model), given non-members get only a limited, revocable permission "for evaluating" the technology?
   The SIG's PDF download page and the PCLA were not read. A member (or the owner's employer) may have different rights.
2. The Assigned Numbers YAML header is a disclaimer with **no grant**; the SIG's page offers the repository publicly but
   states no licence. Ask the SIG (assigned-numbers support) before any mirror or any fixture contains a real entry.
3. **ELM327 / STN datasheets:** may the owner's personal copy be indexed? Neither Elm Electronics nor OBD Solutions
   states redistribution terms in anything read. A written permission request to both would settle it.
4. **tcpdump.org linktypes** and **FTE btsnoop** pages carry no licence; the factual values (numbers and names) are
   likely uncopyrightable, but that is a legal call for the owner.
5. Should `iso import` be generalised to recognise **SAE** covers (J1979, J2534)? That is code, but it is a new
   identification rule per the existing `iso` design.

## 7. What I could not verify

- The Core 7.0 adoption date, the exact current Core volume/part layout, and any download agreement in front of the PDF.
- The GATT Specification Supplement's version and date.
- Whether the YAML header repeats in every file of the repository; I read two.
- The official Elm Electronics datasheet URL and the current revision letter (the SparkFun copy is DSI, 2013, and a DSJ
  exists); every STN redistribution statement. The ELM327 DSI terms themselves were read (§4.1): all rights reserved.
- Whether ISO 14229-1:2026 is in force; the J1979 and J2534 latest revisions on SAE Mobilus; their prices.
- The licence of the tcpdump.org link-type page, of the FTE btsnoop page, and of Wireshark's dissectors (GPL from memory).
- The state of `draft-ietf-opsawg-pcaplinktype`.
- Android and Microsoft documentation licences.
- The Bluetooth SIG Patent/Copyright License Agreement and the specification download terms: not read.
