"""Invented registry XML shaped like IANA's. Every name, value and citation here is made up."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from primarysource.iana.importer import Response

HEAD = (
    "<?xml version='1.0' encoding='UTF-8'?>\n"
    '<?xml-stylesheet type="text/xsl" href="{name}.xsl"?>\n'
    '<?xml-model href="{name}.rng" schematypens="http://relaxng.org/ns/structure/1.0" ?>\n'
)

WIDGETS = (
    HEAD
    + """<registry xmlns="http://www.iana.org/assignments" id="{name}">
  <title>Widget Protocol Parameters</title>
  <updated>2031-02-03</updated>

  <registry id="{name}-1">
    <title>Widget Message Types</title>
    <xref type="rfc" data="rfc9901"/>
    <registration_rule>Standards Action</registration_rule>
    <expert>Ada Example</expert>
    <note>Values above 200 follow <xref type="rfc" data="rfc9902" section="3.1"/> and are hardware specific.</note>
    <range>
      <value>0-9</value>
      <hex>0x00-0x09</hex>
      <registration_rule>Standards Action</registration_rule>
      <note>core types</note>
    </range>
    <record>
      <value>0</value>
      <name>Reserved</name>
    </record>
    <record date="2030-01-02">
      <value>1</value>
      <name>HELLO</name>
      <description>says hello to a gadget</description>
      <xref type="rfc" data="rfc9901" section="4.2"/>
      <xref type="person" data="Ada_Example"/>
    </record>
    <record updated="2031-02-03">
      <value>010</value>
      <name>FROB</name>
      <xref type="rfc" data="rfc9901"/>
      <xref type="draft" data="draft-example-widget-frob-03"/>
      <xref type="rfc-errata" data="4242"/>
    </record>
    <record>
      <value>11-199</value>
      <name>Unassigned</name>
    </record>
    <record>
      <value>0xC8</value>
      <name>VENDOR</name>
      <description>see <xref type="rfc" data="rfc9902"/> for the format</description>
    </record>
  </registry>

  <registry id="{name}-2">
    <title>Widget Flags</title>
    <registration_rule>IETF Review</registration_rule>
    <record>
      <bit>bit 3</bit>
      <flag>QZ</flag>
      <description>quiesce the gizmo</description>
      <xref type="rfc" data="bcp14"/>
    </record>
    <registry id="{name}-sub">
      <title>Widget Subflags</title>
      <record>
        <value>65535</value>
        <hex>0xFFFF</hex>
        <name>ALL</name>
        <reference><xref type="rfc" data="rfc9903"/></reference>
      </record>
    </registry>
  </registry>

  <people>
    <person id="Ada_Example">
      <name>Ada Example</name>
      <uri>mailto:ada&amp;example.invalid</uri>
      <updated>2030-05-06</updated>
    </person>
  </people>
</registry>
"""
)

NAME = "demo-widgets"


def widgets(name: str = NAME) -> bytes:
    return WIDGETS.replace("{name}", name).encode("utf-8")


def install(home: Path, name: str = NAME, body: bytes | None = None, manifest: bool = True) -> Path:
    """Put a registry file (and, by default, its manifest entry) under `<home>/iana/` without any network."""
    import json

    target = home / "iana"
    target.mkdir(parents=True, exist_ok=True)
    data = widgets(name) if body is None else body
    (target / f"{name}.xml").write_bytes(data)
    if manifest:
        entry = {"url": "x", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "updated": "2031-02-03"}
        (target / "manifest.json").write_text(json.dumps({"schema": 1, "files": {name: entry}}), encoding="utf-8")
    return target


class FakeIana:
    """A transport that serves registry files from a dict, records every request and honours If-Modified-Since."""

    def __init__(self, files: Mapping[str, bytes]) -> None:
        self.files = dict(files)
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.last_modified = "Tue, 03 Feb 2031 00:00:00 GMT"

    def __call__(self, url: str, headers: Mapping[str, str]) -> Response:
        self.requests.append((url, dict(headers)))
        name = url.rsplit("/", 1)[-1].removesuffix(".xml")
        if name not in self.files:
            return Response(404, {}, b"")
        if headers.get("If-Modified-Since") == self.last_modified:
            return Response(304, {}, b"")
        return Response(200, {"Last-Modified": self.last_modified}, self.files[name])
