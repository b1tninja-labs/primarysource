# Bluetooth / OBD reference candidates

Researched 2026-11-21 against the live `bluetooth`, `iso` and `gm` corpora, for the OBD-to-TCP bridge and its
BLE/ATT/GATT, ISO 15765-2 and UDS layers. Supersedes the open part of the failed `ps-bt-candidates` session.

Scope: serial/UART GATT, ATT and L2CAP basics; ISO-TP (ISO 15765-2); UDS (ISO 14229); the OBD connector and
emissions services; GM's Mode $06 and diagnostic parameter files. **Out of scope and not listed: medical,
health, bio and body-sensor profiles** (glucose, thermometer, CGM, heart rate, blood pressure, pulse oximeter,
weight scale, insulin, body composition, generic health sensor and similar).

Nothing here is document text. Each row names a source identifier and a clause pointer. A pointer marked
**verified** was read or returned as a search hit in this session; **unpinned** means the subject is known to
be in the document but its clause number in the held edition was not confirmed.

- **Held** = in the live collection today.
- **Candidate** = not held; to acquire, or to add to the collection's catalogue.

## 1. `bluetooth` (Bluetooth SIG)

Primary edition held: **Core Specification 7.0** (`core-specification-7-0`, status `final`, 1978 sections;
the Part footers read "Version Date: 2026-11-02"; `bluetooth_info` reports 2026-09).

| Layer | Source id | Clause pointer | Status | Note |
|---|---|---|---|---|
| L2CAP (Vol 3 Part A) | `core-specification-7-0` | §8.4.7 (Exception conditions, footer "Vol 3, Part A Page 1130"); §4.21 `L2CAP_CONNECTION_PARAMETER_UPDATE_RSP` (verified, Part A p.1026) | Held | The Part A top heading was not located in the 7.0 outline (§2.4.1 does not exist). Fixed-channel CIDs (`0x0004` LE ATT, `0x0005` LE-U signalling) are in `core-specification-6-3§3.3.7` and the 5.x amendments; the 7.0 location is **unpinned**. |
| ATT (Vol 3 Part F) | `core-specification-7-0` | §2.4.6 Part F header (verified); §3.4.9 Attribute PDU response summary, which lists `ATT_HANDLE_VALUE_NTF` and `ATT_HANDLE_VALUE_IND` (verified); §3.2.9 Long attribute values, `ATT_READ_BLOB_REQ` (verified) | Held | The Part F header page carries "Version 5.1" inside a 7.0 document. Cite the 7.0 section, not the 5.1 label. |
| GATT (Vol 3 Part G) | `core-specification-7-0` | §2.4.7 Part G header (verified); §3.3.3.6 sub-procedures, including Discover All Primary Services (`ATT_READ_BY_GROUP_TYPE_REQ`) (verified). The heading on that section reads "Characteristic Aggregate Format"; the sub-procedures are under it. | Held | Characteristic Properties and CCCD clauses returned only as a table fragment in §2.5.2.1 (verified as a hit, not a clean clause). Treat the CCCD clause as **unpinned**. |
| HCI UART transport (Vol 4 Part A, H4/H5) | `core-specification-7-0` | §2.5.1 Parts A to D: Transport Layers (verified header) | Held | The H4 packet and SLIP text is not located inside §2.5.1 in 7.0. In `core-specification-amended-5-0` the UART transport layer is Vol 4 Part A page 2442 (TOC). The 7.0 position is **unpinned**. |
| HCI functional spec (Vol 4 Part E) | `core-specification-7-0` | §2.5.2 Part E header (verified) | Held | Needed only if the bridge talks HCI, not via the OS stack. |
| Link Layer (Vol 6 Part B) | `core-specification-7-0` | §2.7.2 Part B header (verified) | Held | For LE connection and advertising. |
| Architecture (Vol 1 Part A) | `core-specification-7-0` | §3.4 Physical links, Vol 1 Part A p.280 (verified); §3.5 Logical links; §3.6 L2CAP channels | Held | Background for the ATT/L2CAP mapping. |
| GATT Specification Supplement (GSS, 2026-09-09) | `gatt-specification-supplement` | §4.1 Valid Range (the one descriptor it defines); §2.3 Values and represented values | Held (2026-11-21) | Added by hand in the catalogue, kept to the clauses in `docs/bluetooth.md` §5. §3 (characteristics) is not kept. Cite with `bluetooth:gatt-specification-supplement§<clause>`. |
| Assigned Numbers (2026-11-16) | `assigned-numbers` | §3.4 GATT Services; §3.6 Declarations; §3.7 Descriptors (CCCD `0x2902`); §3.8 Characteristics; §2.5 PSMs and SPSMs; §2.9 LE-U CID (reserved range only in this edition) | Held (2026-11-21) | The PDF from the SIG's page, not the YAML repository. Chapter 3 has no heading, so §3.4, §3.6, §3.7 and §3.8 are located by their heading lines (`docs/bluetooth.md` §5). The fixed LE CIDs are not in §2.9; the Core is the source for them. |
| Serial Port Profile 1.2 + RFCOMM 1.2 | `serial-port-profile-1-2`, `rfcomm-1-2` | clauses not yet pinned | Held | **Conditional.** Only if a classic (BR/EDR, non-LE) adapter is targeted. Not part of the BLE GATT scope. |

Core Specification 6.0 to 6.3, the 5.x amendments and the 7.0 "Version 5.1" Parts are also held. Use 7.0 for
new citations; the older editions are for diffing only.

## 2. `iso` (ISO / ISO-IEC; paid, personal volumes)

| Subject | Source id | Clause pointer | Status | Note |
|---|---|---|---|---|
| ISO-TP / transport layer | `iso:15765-2@2016` | §9 Transport layer protocol; §9.3 Multiple-frame transmission (BS/STmin); §9.5.2 CAN frames from N_TAtype/TX_DL; §9.5.3 verifying received frames; §9.6.5 FlowControl N_PCI; §9.6.5.4 STmin; §9.8 Network layer timing; §10.4 DLC (verified by search) | Held (2016 edition) | The 2016 edition is held. The **2024 (4th) edition** is reported by the publisher and resellers and is **not held**; confirm before citing a clause number, since the numbering may move. |
| ISO-TP normative refs | `iso:15765-2@2016` | §2 Normative references: ISO 11898-1:2015 (verified) | Held | The CAN data-link part is the next candidate. |
| CAN data link | `ISO 11898-1` | — | **Candidate** | Cited by 15765-2 §2. Not held. |
| UDS application services | `iso:14229-1@2013` | §6 Application layer services; §9.8.1 Service description; §11.3.1, §13.2.1 (verified by search); §5 document overview (layer figure places UDSonCAN in 14229-3) | Held (2013 edition) | **2020 edition (+Amd 1) and 2026 edition** are not held. Edition status is unverified: see the decision note. |
| UDS on CAN | `ISO 14229-3` | cited in `iso:14229-1@2013` §5 and in `iso:15765-2@2016` bibliography | **Candidate** | Needed for UDSonCAN service-level details. Not held. |
| OBD connector pinout | `iso:15031-3@2004` | §6.3.5 Contact 6 (CAN high, ISO 15765-4); §6.3.8 Contact 14 (CAN low) (verified) | Held | Fixes the connector pins the adapter uses. |
| CAN-based emissions diagnostics | `ISO 15765-4` | cited in `iso:15031-3@2004` §6.3.5 | **Candidate** | The OBD-over-CAN standard that §6.3.5 relies on for contact 6. Not held. |
| Emissions-related diagnostic services | `ISO 15031-5` | cited in `iso:15765-2@2016` bibliography entry [11] (located at the heading `§n-ae`) | **Candidate** | The ISO sibling of SAE J1979 (paid). Not held. |

## 3. `gm` (GM's own published OBD documents; local copies)

| Subject | Source id | Clause pointer | Status | Note |
|---|---|---|---|---|
| Mode $06 definitions, CAN (GMLAN) | `mode6-can` (`GM Mode $06 data definitions (CAN)`, 2020-05, final, 436 sections) | `mode6-can§01-08` (test 01-08); `mode6-can§05-10` (test 05-10, GMLAN footnotes); `mode6-can§07-8C` (GMLAN rev4) (verified) | Held | GMLAN revision 4 is cited in the footnotes. |
| Mode $06 definitions, J1850 / Class 2 | `mode6-class2` | `mode6-class2§05-C7`, `§05-87`, `§05-88`; `§footnotes` (verified) | Held | Needed only for pre-CAN GM vehicles. |
| Per-group diagnostic parameter files | `17OBDG01-hybrid`, `17OBDG03-transmission`, `17OBDG04-engine`, `17OBDG04-transmission`, `17OBDG05-engine`, `17OBDG06-engine` and others | e.g. `17OBDG04-engine§P080A` (references GMLAN message `$4E9` and rolling counts), `§U0106-2` (GMLAN timeout of message `$C9`) (verified) | Held | Maps DTCs to GMLAN message IDs. Points at the GMLAN message set, which is not held as its own document. |
| GMLAN message and physical-layer specification (GM) | `gmlan` — **not held** | none | **Candidate** | The message and bit-timing source behind `mode6-can`'s "GMLAN rev4" footnotes. Confirm whether GM publishes it before adding. |

## 4. `ieee802` (IEEE 802 family)

| Subject | Source id | Clause pointer | Status | Note |
|---|---|---|---|---|
| Bluetooth as an IEEE WPAN standard | `IEEE 802.15.1` | — | **Candidate** | Not in the ieee catalogue (`ieee/catalogue.json` lists 802.3-2022 and others; no 802.15 entry). Relevance is low: the Bluetooth SIG spec is the primary. Check its status (withdrawn or superseded) before adding. |
| CAN / Ethernet / Wi-Fi | — | — | Not needed | Not in the bridge's path. |

## 5. Outside the four collections (pointer only)

These do not belong in `bluetooth`, `iso`, `gm` or `ieee802`. Keep them in their own collections or links.

| Subject | Where it belongs | Note |
|---|---|---|
| pcapng capture format | `draft` (IETF `draft-ietf-opsawg-pcapng`) | Internet-Draft; not an RFC. Read through `draft`. |
| Link-type registry (Bluetooth HCI/LE link types) | link only | tcpdump.org page carries no licence statement. |
| btsnoop | link only | FTE page; no licence read. |
| RFC 1761 (snoop v2) | `rfc` | Already held. |
| ELM327 and STN datasheets | owner's personal volumes, if at all | No redistribution terms found. |
| SAE J1979, J2534 | paid; owner imports | Cite by number only; not held. |

## 6. Gaps and what is not verified

- The 7.0 clause position of: L2CAP fixed-channel CIDs, the H4 UART packet format, the CCCD and Characteristic
  Properties clauses. These are unpinned, not guessed.
- GSS and Assigned Numbers were added to the bluetooth catalogue on 2026-11-21 (`docs/bluetooth.md` §5), so their
  clause pointers in §1 are checked against the PDFs. Their licence is the SIG's non-member evaluation terms, as for
  the other specifications (`docs/bluetooth.md` §2 and §5). The serial/UART GATT service is not in either document.
- ISO 15765-2 2024 and ISO 14229-1 2020/2026: edition status not confirmed against iso.org in this session.
- GMLAN message specification: not located in the gm corpus.

## 7. Where the registration code lives

`bluetooth` and `gm` are not registered on this branch. The `bluetooth` package exists on `cursor/library-subjects`
and in the combined checkout `ps-all-local`; the `gm` package exists on `claude/bt-obd-reference-candidates-cbc1b5`. Their identify
rules and any candidate catalogue must be changed on those branches. This document is the candidate register
for all four collections, so the change there can be checked against it. Nothing here was merged or pushed.
