"""An invented Broadband Forum data-model file and a catalogue that pins it and an invented report. No real text."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path

from pdffixture import standard

from primarysource.bbf.catalogue import Catalogue, Model, Report, Terms

COMMIT = "fedcba9876543210fedcba9876543210fedcba98"
BASE = "https://raw.githubusercontent.com/BroadbandForum/cwmp-data-models/"
REPORT_URL = "https://www.broadband-forum.org/pdfs/tr-999-1-0-0.pdf"

MODEL_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<!--
  Invented Data Model: Widgets [Widget]

  Copyright (c) 2026, Nobody
-->
<dm:document xmlns:dm="urn:invented:datamodel-1-0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    spec="urn:invented:tr-999-1-0-0-widget" file="tr-999-1-0-0-widget.xml">
  <import file="tr-999-biblio.xml" spec="urn:invented:tr-999"/>
  <dataType name="Gasket">
    <description>A gasket identifier.</description>
    <string><size maxLength="16"/></string>
  </dataType>
  <component name="Widget">
    <object name="Device.Widget." access="readOnly" minEntries="1" maxEntries="1" version="2.0">
      <description>
        The top-level widget object.

        It has a second paragraph about sprockets.
      </description>
      <parameter name="Enable" access="readWrite">
        <description>Enables the widget. {{param}} is a template macro.</description>
        <syntax><boolean/><default type="object" value="false"/></syntax>
      </parameter>
      <parameter name="Mode" access="readWrite" version="2.1">
        <description>The mode of the widget. {{enum}}</description>
        <syntax>
          <string>
            <enumeration value="Fast"/>
            <enumeration value="Slow"/>
            <size maxLength="8"/>
          </string>
        </syntax>
      </parameter>
      <command name="Spin()" access="readOnly">
        <description>Spins the widget.</description>
        <input>
          <parameter name="Turns" access="readWrite">
            <description>How many turns to spin.</description>
            <syntax><unsignedInt><range minInclusive="1" maxInclusive="9"/></unsignedInt></syntax>
          </parameter>
        </input>
        <output>
          <parameter name="Done" access="readOnly">
            <description>True when spinning finished.</description>
            <syntax><boolean/></syntax>
          </parameter>
        </output>
      </command>
      <event name="Jammed!">
        <description>The widget jammed.</description>
      </event>
    </object>
    <object name="Device.Widget.Flange.{i}." access="readWrite" minEntries="0" maxEntries="unbounded"
        numEntriesParameter="FlangeNumberOfEntries" version="2.0">
      <description>A flange instance.</description>
      <parameter name="Size" access="readWrite">
        <description>Flange size.</description>
        <syntax><list maxItems="4"><int/></list></syntax>
      </parameter>
    </object>
    <profile name="Baseline:1">
      <description>The baseline profile.</description>
      <object ref="Device.Widget." requirement="readOnly">
        <parameter ref="Enable" requirement="readWrite"/>
      </object>
    </profile>
  </component>
  <model name="Widget:1.0">
    <component ref="Widget"/>
  </model>
</dm:document>
"""

MODELS = {"tr-999-1-0-0-widget": MODEL_XML}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pdf() -> bytes:
    return standard()[0]


def catalogue(
    models: Mapping[str, str | bytes] | None = None, pdf_bytes: bytes | None = None, base: str = BASE
) -> Catalogue:
    items = models if models is not None else dict(MODELS)
    entries = []
    for name, text in items.items():
        data = text.encode("utf-8") if isinstance(text, str) else text
        entries.append(Model(name, f"{name}.xml", name, len(data), sha(data)))
    document = pdf_bytes if pdf_bytes is not None else pdf()
    report = Report(
        "tr-999-1-0-0",
        "TR-999",
        "Invented Standard",
        "Issue 1",
        "https://example.invalid/tr-999",
        REPORT_URL,
        len(document),
        sha(document),
    )
    terms = Terms("BSD-3-Clause", "layer", "https://example.invalid/terms", "2026-11-12", "invented")
    reports = Terms("invented terms", "volume", "https://example.invalid/terms", "2026-11-12", "invented")
    return Catalogue("BroadbandForum/cwmp-data-models", COMMIT, base, terms, reports, tuple(entries), (report,))


def transport(
    models: Mapping[str, str | bytes] | None = None, pdf_bytes: bytes | None = None
) -> Callable[[str, int], bytes]:
    items: dict[str, bytes] = {
        f"{BASE}{COMMIT}/{name}.xml": (t.encode("utf-8") if isinstance(t, str) else t)
        for name, t in (models or MODELS).items()
    }
    items[REPORT_URL] = pdf_bytes if pdf_bytes is not None else pdf()

    def fetch(url: str, max_bytes: int) -> bytes:
        return items[url]

    return fetch


def install(home: Path) -> Path:
    from primarysource.bbf.importer import import_models, import_report

    cat = catalogue()
    import_models(home, cat=cat, transport=transport())
    import_report(home, "tr-999-1-0-0", cat=cat, transport=transport())
    return home
