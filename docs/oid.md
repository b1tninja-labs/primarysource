# oid: root arcs 0, 1 and 2

The international object-identifier tree has three arcs from the root. Rec. ITU-T X.660 | ISO/IEC 9834-1
assigns them in annex A.2.2: `0` is administered by ITU-T, `1` by ISO, and `2` jointly. [oidref.com](https://oidref.com/)
is a snapshot of millions of nodes collected from those trees plus vendor MIB dumps, national registers and
the RFC Editor. This collection is not that snapshot.

```
primarysource oid roots
primarysource oid read 0
primarysource oid export
```

`roots` and `read` print the arcs and cite `X.660§A.2.2`. `export` prints an `oid-node/1` JSON document and
nothing else, so a Rust or JavaScript reader can parse it without this package. The clause stays in the ITU
library (`primarysource itu fetch X.660`, then `primarysource itu index X.660`).

MIB modules are a later importer. They hang under one arc of this tree and stay the job of the MIB parser,
which should read `oid-node/1` rather than grow its own copy of the root. A separate project is the right
home once a second importer exists (IANA numbers, an RFC module, a national register). Until then the file
format is the contract and this command is the only writer.

`export` now includes the child modules after the three roots, in this order: `arc0`, `arc0_more`, `arc1`,
`arc1_more`, `arc2`, `j_low`, `j_mid`, `j_high`, `j_late`, and `rfc_arcs`. One oid is one node (names union,
first cite, first parent that is set), sorted by the integer tuple of the oid. `read` accepts any oid in
that set, including `oid:1.3.6.1`. `roots` is still only arcs 0, 1 and 2.
